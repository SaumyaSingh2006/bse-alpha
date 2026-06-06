"""app.py — BSE Alpha V3 Final — All features integrated"""
import asyncio, json, logging, os, random, time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Dict, List
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from data_collector import collect_all, collect_global, BSE_CODES, jitter, CB
from master_analyzer import analyze_company, enrich_with_news_and_prediction
from market_hours import market_status, is_market_open, next_market_open_seconds
from telegram_alert import send_rise_alert, send_scan_summary, test_telegram, is_configured as tg_ok
from win_tracker import record_alert, get_stats, get_history, auto_check_outcomes
from news_fetcher import get_news_score, fetch_shared_news

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("app")
PORT = int(os.environ.get("PORT", 8000))

COMPANY_INFO = {
    "RAILTEL":    {"name":"RailTel Corporation",      "sector":"Telecom",    "cap":"Small Cap"},
    "IRCTC":      {"name":"Indian Railway Catering",  "sector":"Services",   "cap":"Mid Cap"},
    "HAPPSTMNDS": {"name":"Happiest Minds Tech",      "sector":"IT",         "cap":"Small Cap"},
    "HFCL":       {"name":"HFCL Limited",             "sector":"Telecom",    "cap":"Small Cap"},
    "ELECON":     {"name":"Elecon Engineering",       "sector":"Industrial", "cap":"Small Cap"},
    "SAFARI":     {"name":"Safari Industries",        "sector":"Consumer",   "cap":"Small Cap"},
    "CENTURYPLY": {"name":"Century Plyboards",        "sector":"Consumer",   "cap":"Mid Cap"},
    "FINEORG":    {"name":"Fine Organic Industries",  "sector":"Chemicals",  "cap":"Mid Cap"},
    "KFINTECH":   {"name":"KFin Technologies",        "sector":"Fintech",    "cap":"Mid Cap"},
    "DATAPATTNS": {"name":"Data Patterns India",      "sector":"Defence",    "cap":"Small Cap"},
    "MAPMYINDIA": {"name":"MapMyIndia",               "sector":"IT",         "cap":"Small Cap"},
    "CRAFTSMAN":  {"name":"Craftsman Automation",     "sector":"Auto",       "cap":"Mid Cap"},
    "TINPLATE":   {"name":"Tinplate Company",         "sector":"Metals",     "cap":"Small Cap"},
    "MSTCLTD":    {"name":"MSTC Limited",             "sector":"Services",   "cap":"Small Cap"},
    "DELHIVERY":  {"name":"Delhivery",                "sector":"Logistics",  "cap":"Mid Cap"},
    "GARFIBRES":  {"name":"Garware Tech Fibres",      "sector":"Textiles",   "cap":"Mid Cap"},
    "PNBHOUSING": {"name":"PNB Housing Finance",      "sector":"Finance",    "cap":"Mid Cap"},
    "CAPACITE":   {"name":"Capacite Infraprojects",   "sector":"Infra",      "cap":"Small Cap"},
}

STATE = {
    "results":{}, "alerts":[], "log":[], "scanning":False,
    "last_scan":None, "next_ts":None, "scan_no":0,
    "market_status":"UNKNOWN", "scans_skipped":0,
    "shared_news":{}, "rising_only":[],
}
SSE_QUEUES: List[asyncio.Queue] = []
BASE = 15*60
_alert_cooldown: Dict[str,float] = {}
COOLDOWN = 3600

def slog(msg, lvl="info"):
    e={"t":datetime.now().strftime("%H:%M:%S"),"m":msg,"l":lvl}
    STATE["log"].insert(0,e); STATE["log"]=STATE["log"][:80]
    for q in SSE_QUEUES:
        try: q.put_nowait(json.dumps(e))
        except: pass
    getattr(log,lvl,log.info)(msg)

async def run_scan(forced=False):
    if STATE["scanning"]: return
    mkt=market_status(); STATE["market_status"]=mkt["status"]
    if not forced and not is_market_open():
        secs=next_market_open_seconds(); hrs=secs//3600; mins=(secs%3600)//60
        STATE["scans_skipped"]+=1
        slog(f"⏰ Market {mkt['status']} ({mkt['ist_time']} IST) — next open {hrs}h {mins}m. Scan skipped.","warning")
        STATE["next_ts"]=time.time()+min(secs+60,BASE); return

    STATE["scanning"]=True; STATE["scan_no"]+=1
    slog(f"▶ Scan #{STATE['scan_no']} — {mkt['status']} {mkt['ist_time']} IST")
    entry=random.uniform(0,jitter(30,0.3))
    if entry>2: await asyncio.sleep(entry)

    # Global + Shared news
    slog("  → Global + News fetch...")
    try:
        global_ctx, shared_news = await asyncio.gather(collect_global(), fetch_shared_news(), return_exceptions=True)
        if isinstance(global_ctx,Exception): global_ctx={}
        if isinstance(shared_news,Exception): shared_news={}
        STATE["shared_news"]=shared_news
        macro=shared_news.get("macro_sentiment","neutral")
        slog(f"  ✅ Global OK | News macro: {macro} | RBI:{len(shared_news.get('rbi_news',[]))} Govt:{len(shared_news.get('govt_news',[]))} Mkt:{len(shared_news.get('market_news',[]))}")
    except Exception as e:
        global_ctx={}; shared_news={}
        slog(f"  ⚠️ Global/News failed: {e}","warning")

    symbols=list(BSE_CODES.keys()); random.shuffle(symbols)
    new_results={}; current_prices={}

    for sym in symbols:
        await asyncio.sleep(random.uniform(0.4,1.6))
        info=COMPANY_INFO.get(sym,{})
        try:
            raw=await collect_all(sym,info)
            res=analyze_company(raw,global_ctx)
            # News enrichment
            try:
                news=await get_news_score(sym,info.get("name",sym),info.get("sector",""))
                history=raw.get("price_history",[])
                res=enrich_with_news_and_prediction(res,news,history)
                # Store history for chart
                res["price_history_chart"]=history[-30:] if history else []
            except Exception as e:
                log.debug(f"News/predict error {sym}: {e}")
            new_results[sym]=res
            if res.get("price"): current_prices[sym]=res["price"]
            tf=res.get("timeframe") or {}
            tfl=tf.get("label","—") if tf else "—"
            news_s=res.get("news_sentiment","?")
            slog(f"  ✅ {sym:<12} {res['probability']:.0f}%  {res['verdict']:<5}  {tfl}  news:{news_s}")
            if res["verdict"]=="RISE": await _handle_rise(res)
        except Exception as e:
            slog(f"  ❌ {sym}: {e}","error")

    STATE["results"].update(new_results)
    # Rising only list sorted by probability
    STATE["rising_only"]=[r for r in sorted(new_results.values(),key=lambda x:x.get("probability",0),reverse=True) if r.get("verdict")=="RISE"]

    if current_prices:
        try: auto_check_outcomes(current_prices)
        except: pass

    jd=jitter(BASE,0.133); STATE["next_ts"]=time.time()+jd; STATE["last_scan"]=datetime.now().strftime("%d %b %Y %H:%M:%S")
    rise=len(STATE["rising_only"])
    slog(f"✔ Done — {rise} RISE signals. Next {jd/60:.1f}m")
    if tg_ok() and rise>0:
        try: await send_scan_summary(rise,len(new_results),STATE["scan_no"])
        except: pass
    STATE["scanning"]=False

async def _handle_rise(result):
    sym=result["symbol"]; now=time.time()
    if now-_alert_cooldown.get(sym,0)<COOLDOWN:
        return
    _alert_cooldown[sym]=now
    tf=result.get("timeframe") or {}
    entry={
        **{k:result.get(k) for k in ["symbol","name","sector","cap","probability","verdict","price","change_pct","target","stop_loss","upside_pct","rsi","macd_signal","fii_net","dii_net","global_sent","vol_surge","ma_trend","qoq_growth","yoy_growth","rev_growth","margin_trend","pe_ratio","has_new_order","has_concall","has_mgmt_change","has_expansion","alert_msg","score_detail","tech_detail","news_score","news_sentiment","top_news","prediction","timing","risk_reward","price_history_chart"]},
        "timeframe_label":tf.get("label","") if tf else "","timeframe_color":tf.get("color","#DC143C") if tf else "#DC143C","timeframe_days":tf.get("days",99) if tf else 99,"timeframe":tf,
        "signals":[s["text"] for s in result.get("signals",[]) if s.get("bull")][:5],
        "bear_signals":[s["text"] for s in result.get("signals",[]) if not s.get("bull")][:3],
        "time":datetime.now().strftime("%H:%M"),
    }
    STATE["alerts"]=[a for a in STATE["alerts"] if a["symbol"]!=sym]
    STATE["alerts"].insert(0,entry); STATE["alerts"]=STATE["alerts"][:30]
    try: record_alert(result)
    except: pass
    if tg_ok():
        try: await send_rise_alert(result); slog(f"🚨 ALERT+TG: {sym} {result['probability']:.0f}%")
        except Exception as e: slog(f"🚨 ALERT (TG fail): {sym} — {e}","warning")
    else:
        slog(f"🚨 ALERT: {sym} — {result['probability']:.0f}% — {tf.get('label','') if tf else ''}")

async def scheduler():
    slog("BSE Alpha V3 — Market hours + News + Prediction active")
    await asyncio.sleep(3); await run_scan()
    while True:
        await asyncio.sleep(10)
        if STATE["next_ts"] and time.time()>=STATE["next_ts"] and not STATE["scanning"]:
            await run_scan()

@asynccontextmanager
async def lifespan(a):
    t=asyncio.create_task(scheduler()); yield; t.cancel()
    from data_collector import close; await close()

app=FastAPI(title="BSE Alpha V3",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_methods=["*"],allow_headers=["*"])

_last_force=0
@app.get("/api/alerts")
def get_alerts(): return {"alerts":STATE["alerts"],"count":len(STATE["alerts"]),"last_scan":STATE["last_scan"]}

@app.get("/api/rising")
def get_rising():
    """MAIN endpoint — only rising stocks, sorted by probability."""
    return {"rising":STATE["rising_only"],"count":len(STATE["rising_only"]),"last_scan":STATE["last_scan"],"scanning":STATE["scanning"]}

@app.get("/api/results")
def get_results():
    s=sorted(STATE["results"].values(),key=lambda x:x.get("probability",0),reverse=True)
    return {"results":s,"last_scan":STATE["last_scan"],"scanning":STATE["scanning"]}

@app.get("/api/status")
def get_status():
    nxt=STATE["next_ts"]; mkt=market_status()
    return {"scanning":STATE["scanning"],"last_scan":STATE["last_scan"],"next_scan_secs":max(0,int(nxt-time.time())) if nxt else None,"scan_count":STATE["scan_no"],"circuit_breaker":"OPEN" if CB.is_open() else "CLOSED","companies":len(STATE["results"]),"alerts":len(STATE["alerts"]),"market_status":mkt["status"],"market_time":mkt["ist_time"],"market_date":mkt["ist_date"],"scans_skipped":STATE["scans_skipped"],"telegram_active":tg_ok()}

@app.get("/api/news")
def get_news(): return STATE.get("shared_news",{})

@app.get("/api/scan")
async def force_scan():
    global _last_force
    if time.time()-_last_force<60: return {"status":"rate_limited"}
    _last_force=time.time(); asyncio.create_task(run_scan(forced=True))
    return {"status":"started"}

@app.get("/api/log")
def get_log(): return {"log":STATE["log"][:50]}
@app.get("/api/market")
def get_market(): return market_status()
@app.get("/api/winrate")
def get_winrate():
    try: return get_stats()
    except: return {"total_alerts":0,"wins":0,"losses":0,"win_rate":0,"pending":0}
@app.get("/api/history")
def get_hist():
    try: return {"history":get_history(50)}
    except: return {"history":[]}
@app.get("/api/telegram/test")
async def tg_test(): return await test_telegram()
@app.get("/api/stream")
async def sse():
    q=asyncio.Queue(maxsize=200); SSE_QUEUES.append(q)
    async def gen():
        try:
            yield f"data: {json.dumps({'type':'connected'})}\n\n"
            while True:
                try: yield f"data: {await asyncio.wait_for(q.get(),20)}\n\n"
                except asyncio.TimeoutError: yield 'data: {"type":"ping"}\n\n'
        finally:
            if q in SSE_QUEUES: SSE_QUEUES.remove(q)
    return StreamingResponse(gen(),media_type="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})
@app.get("/health")
def health(): return {"status":"ok","scan_count":STATE["scan_no"]}
@app.get("/",response_class=HTMLResponse)
def ui():
    with open("ui.html") as f: return f.read()
