"""
data_collector.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Collects ALL data needed for 18-factor analysis:

SOURCE 1 — BSE API
  • Live price, volume, PE ratio
  • Quarterly results (last 8 quarters)
  • Announcements (orders, concall, mgmt change)
  • Shareholding pattern (promoter %)

SOURCE 2 — Yahoo Finance (via yfinance)
  • 1-year daily OHLCV price history
  • FII/DII data (institutional holdings)
  • Global indices: Dow, Nasdaq, Nikkei, Hang Seng
  • Crude oil, USD/INR

SOURCE 3 — NSE India
  • Sector index performance
  • FII/DII daily buy/sell data

SOURCE 4 — Calculated (from price history)
  • RSI (14), MACD, Bollinger Bands
  • 50DMA, 200DMA, EMA20
  • Support / Resistance levels
  • Volume vs 20-day average
  • Candlestick patterns

All requests use jitter anti-block engine.
"""

import asyncio, random, time, logging, json
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import httpx
from bs4 import BeautifulSoup

log = logging.getLogger("data_collector")

# ── Jitter / Anti-block ───────────────────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.82 Mobile Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
]
REFERERS = [
    "https://www.google.co.in/search?q=bse+india+stock",
    "https://www.moneycontrol.com/", "https://economictimes.indiatimes.com/markets",
    "https://finance.yahoo.com/", "https://www.nseindia.com/",
]

def jitter(base, pct=0.3):  return base + random.uniform(-1,1)*base*pct
def rsleep(lo, hi):          return asyncio.sleep(random.uniform(lo, hi))
def backoff(n, b=1.5, c=40): return random.uniform(0, min(c, b*(2**n)))

# Cache: TTL 13 min
_CACHE = {}; _CACHE_TS = {}; CACHE_TTL = 13*60
def cache_get(k): return _CACHE[k] if k in _CACHE and time.time()-_CACHE_TS.get(k,0)<CACHE_TTL else None
def cache_set(k,v): _CACHE[k]=v; _CACHE_TS[k]=time.time()

# Circuit breaker
class CB:
    fails=0; open_until=0; MAX=5
    @classmethod
    def ok(cls): cls.fails=0
    @classmethod
    def fail(cls):
        cls.fails+=1
        if cls.fails>=cls.MAX: cls.open_until=time.time()+jitter(90,0.4); log.warning("CB OPEN")
    @classmethod
    def is_open(cls):
        if cls.open_until and time.time()>cls.open_until: cls.fails=0; cls.open_until=0
        return cls.open_until>time.time()

_client: Optional[httpx.AsyncClient] = None
async def get_client():
    global _client
    if not _client or _client.is_closed:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(15,connect=8), follow_redirects=True, verify=False)
    return _client

def hdrs(ref=None):
    h = {"User-Agent":random.choice(USER_AGENTS),"Referer":ref or random.choice(REFERERS),
         "Accept":"application/json,text/html,*/*","Accept-Language":"en-IN,en;q=0.9",
         "Cache-Control":"no-cache","DNT":"1"}
    items=list(h.items()); random.shuffle(items); return dict(items)

async def safe_get(url, ref=None, retries=3):
    if CB.is_open(): return None
    await rsleep(0.2, 1.1)
    c = await get_client()
    for i in range(retries+1):
        if i: await asyncio.sleep(backoff(i))
        try:
            r = await c.get(url, headers=hdrs(ref))
            if r.status_code in (429,503,502): CB.fail(); await asyncio.sleep(backoff(i+1,3,60)); continue
            if r.status_code==200: CB.ok(); return r
        except Exception as e: CB.fail(); log.debug(f"req err: {e}")
    return None

# ── BSE scrip codes ──────────────────────────────────────────────────────────
BSE_CODES = {
    "RAILTEL":"543635","IRCTC":"542830","HAPPSTMNDS":"543227","HFCL":"500183",
    "ELECON":"505700","SAFARI":"523025","CENTURYPLY":"532548","FINEORG":"541557",
    "KFINTECH":"543720","DATAPATTNS":"543428","MAPMYINDIA":"543425","CRAFTSMAN":"543233",
    "TINPLATE":"504966","MSTCLTD":"542502","DELHIVERY":"543529","GARFIBRES":"530715",
    "PNBHOUSING":"540173","CAPACITE":"540652",
}

# Yahoo Finance symbols
YF_SYMBOLS = {
    "RAILTEL":"RAILTEL.NS","IRCTC":"IRCTC.NS","HAPPSTMNDS":"HAPPSTMNDS.NS",
    "HFCL":"HFCL.NS","ELECON":"ELECON.NS","SAFARI":"SAFARI.NS",
    "CENTURYPLY":"CENTURYPLY.NS","FINEORG":"FINEORG.NS","KFINTECH":"KFINTECH.NS",
    "DATAPATTNS":"DATAPATTNS.NS","MAPMYINDIA":"MAPMYINDIA.NS","CRAFTSMAN":"CRAFTSMAN.NS",
    "TINPLATE":"TINPLATE.NS","MSTCLTD":"MSTCLTD.NS","DELHIVERY":"DELHIVERY.NS",
    "GARFIBRES":"GARFIBRES.NS","PNBHOUSING":"PNBHOUSING.NS","CAPACITE":"CAPACITE.NS",
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SOURCE 1 — BSE API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def bse_quote(symbol: str) -> Dict:
    code = BSE_CODES.get(symbol)
    if not code: return {}
    ck = f"bse_q_{symbol}"; cached=cache_get(ck)
    if cached: return cached
    url = f"https://api.bseindia.com/BseIndiaAPI/api/getScripHeaderData/w?Debtflag=&scripcode={code}&seriesid="
    r = await safe_get(url, ref="https://www.bseindia.com/")
    if not r: return {}
    try:
        d = r.json()
        result = {
            "price":     float(d.get("CurrRate") or 0),
            "prev_close":float(d.get("Prv_Close") or 0),
            "change_pct":float(d.get("PcChg") or 0),
            "open":      float(d.get("Open") or 0),
            "high":      float(d.get("High") or 0),
            "low":       float(d.get("Low") or 0),
            "volume":    int(float(d.get("TradedQty") or 0)),
            "52w_high":  float(d.get("High52") or 0),
            "52w_low":   float(d.get("Low52") or 0),
            "market_cap":float(d.get("Mktcap") or 0),
            "pe_ratio":  float(d.get("PricEarningRatio") or 0),
            "face_value":float(d.get("FaceValue") or 0),
        }
        cache_set(ck, result); return result
    except: return {}

async def bse_quarterly(symbol: str) -> List[Dict]:
    code = BSE_CODES.get(symbol)
    if not code: return []
    ck = f"bse_qt_{symbol}"; cached=cache_get(ck)
    if cached: return cached
    url = f"https://api.bseindia.com/BseIndiaAPI/api/Stocklists/w?Type=EQ&scripcode={code}&Group=&Seriesid="
    r = await safe_get(url, ref="https://www.bseindia.com/")
    if not r: return []
    try:
        data = r.json()
        qts = []
        for item in (data.get("Table") or [])[:8]:
            qts.append({
                "period":    item.get("PERIOD_END",""),
                "revenue":   float(item.get("NET_SALES_INCOME_FROM_OPN") or 0),
                "net_profit":float(item.get("NET_PROFIT_LOSS") or 0),
                "ebitda":    float(item.get("PBDIT") or 0),
                "eps":       float(item.get("BASIC_EPS_BEFORE_EXTRA") or 0),
                "interest":  float(item.get("INTEREST") or 0),
                "tax":       float(item.get("TAX") or 0),
            })
        cache_set(ck, qts); return qts
    except: return []

async def bse_announcements(symbol: str) -> List[Dict]:
    code = BSE_CODES.get(symbol)
    if not code: return []
    ck = f"bse_ann_{symbol}"; cached=cache_get(ck)
    if cached: return cached
    url = (f"https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w?"
           f"scripcode={code}&strCat=-1&strPrevDate=&strScrip=&strSearch=P&strType=C")
    r = await safe_get(url, ref="https://www.bseindia.com/")
    if not r: return []
    try:
        data = r.json()
        anns = []
        for item in (data.get("Table") or [])[:20]:
            hl = (item.get("HEADLINE") or "").lower()
            anns.append({
                "date":           item.get("News_submission_dt",""),
                "headline":       item.get("HEADLINE",""),
                "category":       item.get("CATEGORYNAME",""),
                "is_new_order":   any(w in hl for w in ["order","contract","award","win","bag","loi","tender","supply","empanel"]),
                "is_concall":     any(w in hl for w in ["concall","investor meet","conference call","earnings call","analyst meet"]),
                "is_mgmt_change": any(w in hl for w in ["appoint","resign","director","ceo","cfo","md ","whole time","independent"]),
                "is_result":      any(w in hl for w in ["result","financial result","quarter","unaudited","audited"]),
                "is_buyback":     any(w in hl for w in ["buyback","buy-back","dividend","bonus","split","rights"]),
                "is_expansion":   any(w in hl for w in ["capacity","expansion","plant","facility","capex","greenfield"]),
                "is_acquisition": any(w in hl for w in ["acqui","merger","takeover","stake","subsidiary","joint venture"]),
                "is_credit":      any(w in hl for w in ["rating","upgrade","downgrade","icra","crisil","care "]),
            })
        cache_set(ck, anns); return anns
    except: return []

async def bse_shareholding(symbol: str) -> Dict:
    """Promoter holding % from BSE shareholding pattern."""
    code = BSE_CODES.get(symbol)
    if not code: return {}
    ck = f"bse_sh_{symbol}"; cached=cache_get(ck)
    if cached: return cached
    url = f"https://api.bseindia.com/BseIndiaAPI/api/ShareHoldingPatterns/w?scripcode={code}&flag=C&quarterid="
    r = await safe_get(url, ref="https://www.bseindia.com/")
    if not r: return {}
    try:
        data = r.json()
        items = data.get("Table") or []
        promoter = fii = dii = public = 0.0
        for item in items:
            cat = (item.get("CATEGORY") or "").lower()
            pct = float(item.get("PERCENT") or 0)
            if "promoter" in cat: promoter += pct
            elif "foreign institution" in cat or "fii" in cat or "fpi" in cat: fii += pct
            elif "domestic institution" in cat or "mutual" in cat or "dii" in cat: dii += pct
            elif "public" in cat or "retail" in cat: public += pct
        result = {"promoter_pct": round(promoter,2), "fii_pct": round(fii,2),
                  "dii_pct": round(dii,2), "public_pct": round(public,2)}
        cache_set(ck, result); return result
    except: return {}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SOURCE 2 — Yahoo Finance (price history + global)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def yf_history(symbol: str, period="1y") -> List[Dict]:
    """1-year daily OHLCV from Yahoo Finance."""
    yf_sym = YF_SYMBOLS.get(symbol)
    if not yf_sym: return []
    ck = f"yf_hist_{symbol}"; cached=cache_get(ck)
    if cached: return cached

    end = datetime.now()
    start = end - timedelta(days=365)
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{yf_sym}"
           f"?interval=1d&period1={int(start.timestamp())}&period2={int(end.timestamp())}")
    r = await safe_get(url, ref="https://finance.yahoo.com/")
    if not r: return []
    try:
        data = r.json()
        result_data = data["chart"]["result"][0]
        timestamps = result_data["timestamp"]
        ohlcv = result_data["indicators"]["quote"][0]
        history = []
        for i, ts in enumerate(timestamps):
            try:
                history.append({
                    "date":   datetime.fromtimestamp(ts).strftime("%Y-%m-%d"),
                    "open":   round(float(ohlcv["open"][i] or 0), 2),
                    "high":   round(float(ohlcv["high"][i] or 0), 2),
                    "low":    round(float(ohlcv["low"][i] or 0), 2),
                    "close":  round(float(ohlcv["close"][i] or 0), 2),
                    "volume": int(ohlcv["volume"][i] or 0),
                })
            except: pass
        cache_set(ck, history); return history
    except Exception as e:
        log.debug(f"YF history error {symbol}: {e}"); return []

async def yf_global_markets() -> Dict:
    """Global indices and commodities."""
    ck = "global_markets"; cached=cache_get(ck)
    if cached: return cached

    symbols = {
        "dow":     "^DJI",      "nasdaq":   "^IXIC",    "sp500":    "^GSPC",
        "nikkei":  "^N225",     "hangseng": "^HSI",     "sensex":   "^BSESN",
        "nifty":   "^NSEI",     "crude_oil": "CL=F",    "gold":     "GC=F",
        "usdinr":  "USDINR=X",  "vix":      "^VIX",
    }
    result = {}
    for name, sym in symbols.items():
        await rsleep(0.1, 0.4)
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=5d"
        r = await safe_get(url, ref="https://finance.yahoo.com/")
        if r:
            try:
                d = r.json()["chart"]["result"][0]
                closes = d["indicators"]["quote"][0]["close"]
                closes = [c for c in closes if c]
                if len(closes) >= 2:
                    result[name] = {
                        "price":      round(closes[-1], 2),
                        "change_pct": round((closes[-1]-closes[-2])/closes[-2]*100, 2),
                        "trend_5d":   round((closes[-1]-closes[0])/closes[0]*100, 2),
                    }
            except: pass
    if result: cache_set(ck, result)
    return result

async def nse_fii_dii() -> Dict:
    """NSE FII/DII daily buy-sell data."""
    ck = "nse_fii_dii"; cached=cache_get(ck)
    if cached: return cached
    url = "https://www.nseindia.com/api/fiidiiTradeReact"
    r = await safe_get(url, ref="https://www.nseindia.com/")
    if not r: return {}
    try:
        data = r.json()
        fii = dii = {"buy":0,"sell":0,"net":0}
        for item in data:
            cat = (item.get("category") or "").lower()
            if "foreign" in cat or "fii" in cat or "fpi" in cat:
                fii = {
                    "buy":  float(item.get("buyValue") or 0),
                    "sell": float(item.get("sellValue") or 0),
                    "net":  float(item.get("netValue") or 0),
                }
            elif "domestic" in cat or "dii" in cat or "mutual" in cat:
                dii = {
                    "buy":  float(item.get("buyValue") or 0),
                    "sell": float(item.get("sellValue") or 0),
                    "net":  float(item.get("netValue") or 0),
                }
        result = {"fii": fii, "dii": dii,
                  "market_sentiment": "bullish" if fii["net"]>0 and dii["net"]>0
                                      else "bearish" if fii["net"]<0 and dii["net"]<0
                                      else "mixed"}
        cache_set(ck, result); return result
    except: return {}

async def nse_sector_performance() -> Dict:
    """NSE sectoral indices performance."""
    ck = "nse_sectors"; cached=cache_get(ck)
    if cached: return cached
    url = "https://www.nseindia.com/api/equity-stockIndices?index=SECURITIES%20IN%20F%26O"
    r = await safe_get(url, ref="https://www.nseindia.com/")
    sector_map = {}
    if r:
        try:
            sectors_url = "https://www.nseindia.com/api/allIndices"
            r2 = await safe_get(sectors_url, ref="https://www.nseindia.com/")
            if r2:
                d = r2.json()
                for idx in (d.get("data") or []):
                    name = idx.get("index","")
                    if any(s in name for s in ["NIFTY IT","NIFTY BANK","NIFTY AUTO","NIFTY PHARMA",
                                                "NIFTY METAL","NIFTY FMCG","NIFTY REALTY","NIFTY INFRA",
                                                "NIFTY SMALLCAP","NIFTY MIDCAP"]):
                        sector_map[name] = {
                            "change_pct": float(idx.get("percentChange") or 0),
                            "value":      float(idx.get("last") or 0),
                        }
        except: pass
    if sector_map: cache_set(ck, sector_map)
    return sector_map

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN: Collect everything for one symbol
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
async def collect_all(symbol: str, company_info: Dict) -> Dict:
    """Fetch all data sources for one company with jitter."""
    log.info(f"  Collecting {symbol}...")
    await rsleep(0.3, 1.2)

    # Run all fetches with stagger
    quote_t      = asyncio.create_task(bse_quote(symbol))
    await rsleep(0.15, 0.4)
    quarterly_t  = asyncio.create_task(bse_quarterly(symbol))
    await rsleep(0.15, 0.4)
    announce_t   = asyncio.create_task(bse_announcements(symbol))
    await rsleep(0.15, 0.4)
    holding_t    = asyncio.create_task(bse_shareholding(symbol))
    await rsleep(0.15, 0.4)
    history_t    = asyncio.create_task(yf_history(symbol))

    quote, quarterly, announcements, shareholding, history = await asyncio.gather(
        quote_t, quarterly_t, announce_t, holding_t, history_t,
        return_exceptions=True
    )

    return {
        "symbol":       symbol,
        "name":         company_info.get("name", symbol),
        "sector":       company_info.get("sector", ""),
        "cap":          company_info.get("cap", ""),
        "quote":        quote if isinstance(quote, dict) else {},
        "quarterly":    quarterly if isinstance(quarterly, list) else [],
        "announcements":announcements if isinstance(announcements, list) else [],
        "shareholding": shareholding if isinstance(shareholding, dict) else {},
        "price_history":history if isinstance(history, list) else [],
    }

async def collect_global() -> Dict:
    """Fetch global market data (shared across all companies)."""
    global_t  = asyncio.create_task(yf_global_markets())
    fii_dii_t = asyncio.create_task(nse_fii_dii())
    sectors_t = asyncio.create_task(nse_sector_performance())
    g, f, s   = await asyncio.gather(global_t, fii_dii_t, sectors_t, return_exceptions=True)
    return {
        "global_markets": g if isinstance(g, dict) else {},
        "fii_dii":        f if isinstance(f, dict) else {},
        "sectors":        s if isinstance(s, dict) else {},
    }

async def close():
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
