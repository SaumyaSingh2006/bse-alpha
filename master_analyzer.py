"""
master_analyzer.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Combines ALL 18+ factors into final probability score:

FUNDAMENTAL (50 points max):
  [1]  QoQ profit growth        — 15 pts
  [2]  YoY profit growth        — 8 pts
  [3]  Profit trend consistency — 7 pts
  [4]  Revenue growth           — 5 pts
  [5]  EBITDA margin trend      — 7 pts
  [6]  Debt/Equity ratio        — 5 pts
  [7]  ROE / ROCE               — 3 pts

ANNOUNCEMENTS (25 points max):
  [8]  New order / contract     — 10 pts
  [9]  Concall / investor meet  — 4 pts
  [10] Buyback / dividend       — 3 pts
  [11] Capacity expansion       — 3 pts
  [12] Acquisition / JV         — 3 pts
  [13] Credit rating upgrade    — 2 pts
  [14] Management change        — -6 pts

TECHNICAL (35 points max):
  [15] RSI signal               — 8 pts
  [16] MACD crossover           — 8 pts
  [17] Moving averages          — 7 pts
  [18] Volume surge             — 6 pts
  [19] Support/Resistance       — 4 pts
  [20] Candlestick patterns     — 2 pts

MACRO / MARKET (15 points max):
  [21] FII/DII buying           — 6 pts
  [22] Sector performance       — 4 pts
  [23] Global market sentiment  — 3 pts
  [24] Promoter buying/holding  — 2 pts

Total max = 125 → normalized to 0-95%
"""

import logging, math
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from technical_engine import run_technical_analysis

log = logging.getLogger("master_analyzer")

TIMEFRAMES = [
    {"label":"🔥 AAJHI INTRADAY",  "days":0,  "min_prob":80, "color":"#FF4400"},
    {"label":"⚡ 1-3 DIN MEIN",    "days":2,  "min_prob":70, "color":"#FF8800"},
    {"label":"📈 3-7 DIN MEIN",    "days":5,  "min_prob":62, "color":"#FFCC00"},
    {"label":"📊 1-2 HAFTE MEIN",  "days":10, "min_prob":54, "color":"#AADD00"},
    {"label":"🌱 2-4 HAFTE MEIN",  "days":21, "min_prob":46, "color":"#00DD88"},
]

def _f(v, d=0.0):
    try: return float(v or d)
    except: return d

def _qoq_yoy(quarterly):
    if len(quarterly) < 2: return 0.0, 0.0
    p0 = _f(quarterly[0].get("net_profit"))
    p1 = _f(quarterly[1].get("net_profit"))
    p4 = _f(quarterly[4].get("net_profit")) if len(quarterly)>4 else 0
    qoq = ((p0-p1)/abs(p1)*100) if p1 else 0
    yoy = ((p0-p4)/abs(p4)*100) if p4 else 0
    return round(qoq,1), round(yoy,1)

def _revenue_growth(quarterly):
    if len(quarterly) < 5: return 0.0
    r0 = _f(quarterly[0].get("revenue"))
    r4 = _f(quarterly[4].get("revenue"))
    return round((r0-r4)/abs(r4)*100, 1) if r4 else 0

def _margin_trend(quarterly):
    if len(quarterly) < 3: return "stable", 0.0
    def m(q): r=_f(q.get("revenue")); e=_f(q.get("ebitda")); return e/r*100 if r else 0
    delta = m(quarterly[0]) - m(quarterly[2])
    return ("expanding",round(delta,1)) if delta>1.5 else ("contracting",round(delta,1)) if delta<-1.5 else ("stable",round(delta,1))

def _profit_trend(quarterly):
    pts = [_f(q.get("net_profit")) for q in quarterly[:4]]
    if len(pts) < 2: return 50.0
    ups = sum(1 for i in range(1,len(pts)) if pts[i-1]>pts[i])
    return (ups/(len(pts)-1))*100

def _sector_sentiment(sectors: Dict, company_sector: str) -> Tuple[float, str]:
    """Map company sector to NSE index performance."""
    sector_map = {
        "IT":        ["NIFTY IT"],
        "Telecom":   ["NIFTY IT","NIFTY MEDIA"],
        "Consumer":  ["NIFTY FMCG","NIFTY CONSUMER"],
        "Industrial":["NIFTY METAL","NIFTY INFRA"],
        "Chemicals": ["NIFTY PHARMA","NIFTY CHEMICAL"],
        "Fintech":   ["NIFTY BANK","NIFTY FINANCIAL"],
        "Finance":   ["NIFTY BANK","NIFTY FINANCIAL"],
        "Defence":   ["NIFTY INFRA"],
        "Auto":      ["NIFTY AUTO"],
        "Logistics": ["NIFTY INFRA"],
        "Services":  ["NIFTY MIDCAP 100"],
        "Metals":    ["NIFTY METAL"],
    }
    relevant = sector_map.get(company_sector, [])
    changes = []
    for idx_name, data in sectors.items():
        if any(r in idx_name for r in relevant):
            changes.append(_f(data.get("change_pct")))
    if not changes: return 50.0, "neutral"
    avg_chg = sum(changes)/len(changes)
    score = 50 + avg_chg*5
    sentiment = "bullish" if avg_chg > 0.5 else "bearish" if avg_chg < -0.5 else "neutral"
    return min(80, max(20, score)), sentiment

def _global_sentiment(global_data: Dict) -> Tuple[float, str]:
    """Score based on global market conditions."""
    if not global_data: return 50.0, "unknown"
    score = 50.0
    signals = []
    dow    = global_data.get("dow",{})
    nasdaq = global_data.get("nasdaq",{})
    usdinr = global_data.get("usdinr",{})
    crude  = global_data.get("crude_oil",{})
    vix    = global_data.get("vix",{})
    sensex = global_data.get("sensex",{})

    if sensex.get("change_pct",0) > 0.5: score += 8; signals.append("Sensex up")
    elif sensex.get("change_pct",0) < -0.5: score -= 8; signals.append("Sensex down")

    if dow.get("change_pct",0) > 0.5: score += 4; signals.append("Dow up")
    elif dow.get("change_pct",0) < -1: score -= 5; signals.append("Dow down")

    if nasdaq.get("change_pct",0) > 0.5: score += 3
    elif nasdaq.get("change_pct",0) < -1: score -= 4

    if vix.get("price",20) < 15: score += 5; signals.append("Low VIX (low fear)")
    elif vix.get("price",20) > 25: score -= 8; signals.append("High VIX (high fear)")

    usdinr_chg = usdinr.get("change_pct",0)
    if usdinr_chg > 0.5: score -= 3; signals.append("Rupee weak")
    elif usdinr_chg < -0.3: score += 3; signals.append("Rupee strong")

    crude_chg = crude.get("change_pct",0)
    if crude_chg > 2: score -= 4; signals.append("Crude oil up (inflation risk)")
    elif crude_chg < -2: score += 3; signals.append("Crude oil down (good for India)")

    sentiment = "bullish" if score > 58 else "bearish" if score < 42 else "mixed"
    return min(85, max(15, score)), sentiment


def analyze_company(data: Dict, global_context: Dict) -> Dict:
    """
    Full 18-factor analysis.
    data           = from data_collector.collect_all()
    global_context = from data_collector.collect_global()
    """
    symbol      = data["symbol"]
    name        = data.get("name", symbol)
    sector      = data.get("sector","")
    cap         = data.get("cap","")
    quote       = data.get("quote",{})
    quarterly   = data.get("quarterly",[])
    anns        = data.get("announcements",[])
    shareholding= data.get("shareholding",{})
    history     = data.get("price_history",[])

    global_markets = global_context.get("global_markets",{})
    fii_dii        = global_context.get("fii_dii",{})
    sectors        = global_context.get("sectors",{})

    price      = _f(quote.get("price"))
    change_pct = _f(quote.get("change_pct"))
    pe         = _f(quote.get("pe_ratio"))
    high52     = _f(quote.get("52w_high"))
    low52      = _f(quote.get("52w_low"))

    all_signals = []
    raw_score   = 0.0
    score_detail = {}

    # ════════════════════════════════════════════════
    # BLOCK A: FUNDAMENTAL (max 50 pts)
    # ════════════════════════════════════════════════

    qoq, yoy = _qoq_yoy(quarterly)
    rev_growth  = _revenue_growth(quarterly)
    margin_dir, margin_delta = _margin_trend(quarterly)
    profit_trend_pct = _profit_trend(quarterly)

    # [1] QoQ profit growth (15 pts)
    if   qoq > 35: s=15; all_signals.append({"bull":True,  "cat":"Fundamental","text":f"QoQ profit +{qoq}% — bada jump!"})
    elif qoq > 20: s=12; all_signals.append({"bull":True,  "cat":"Fundamental","text":f"QoQ profit +{qoq}%"})
    elif qoq > 8:  s=8;  all_signals.append({"bull":True,  "cat":"Fundamental","text":f"QoQ growth +{qoq}%"})
    elif qoq > 0:  s=5
    elif qoq > -8: s=2;  all_signals.append({"bull":False, "cat":"Fundamental","text":f"QoQ profit {qoq}%"})
    else:          s=0;  all_signals.append({"bull":False, "cat":"Fundamental","text":f"QoQ profit zyada gira {qoq}%"})
    score_detail["qoq"]=s; raw_score+=s

    # [2] YoY profit growth (8 pts)
    if   yoy > 50: s=8;  all_signals.append({"bull":True,  "cat":"Fundamental","text":f"YoY profit +{yoy}% — exceptional!"})
    elif yoy > 25: s=6;  all_signals.append({"bull":True,  "cat":"Fundamental","text":f"YoY profit +{yoy}%"})
    elif yoy > 8:  s=4
    elif yoy < -15:s=0;  all_signals.append({"bull":False, "cat":"Fundamental","text":f"YoY profit gira {yoy}%"})
    else:          s=2
    score_detail["yoy"]=s; raw_score+=s

    # [3] Profit trend consistency (7 pts)
    if   profit_trend_pct >= 75: s=7; all_signals.append({"bull":True,  "cat":"Fundamental","text":"Lagatar growing profit (3-4 quarters)"})
    elif profit_trend_pct >= 50: s=4
    else:                        s=1; all_signals.append({"bull":False, "cat":"Fundamental","text":"Inconsistent profit trend"})
    score_detail["trend"]=s; raw_score+=s

    # [4] Revenue growth (5 pts)
    if   rev_growth > 20: s=5; all_signals.append({"bull":True,  "cat":"Fundamental","text":f"Revenue +{rev_growth}% YoY"})
    elif rev_growth > 8:  s=3
    elif rev_growth < 0:  s=0; all_signals.append({"bull":False, "cat":"Fundamental","text":f"Revenue giri {rev_growth}%"})
    else:                 s=2
    score_detail["revenue"]=s; raw_score+=s

    # [5] Margin trend (7 pts)
    if   margin_dir=="expanding":   s=7; all_signals.append({"bull":True,  "cat":"Fundamental","text":f"EBITDA margin expand ho rahi hai (+{margin_delta}%)"})
    elif margin_dir=="contracting": s=1; all_signals.append({"bull":False, "cat":"Fundamental","text":f"EBITDA margin compress ho rahi hai ({margin_delta}%)"})
    else:                           s=3
    score_detail["margin"]=s; raw_score+=s

    # [6] Debt/Equity (5 pts) — from shareholding or quarterly interest
    interest = _f(quarterly[0].get("interest")) if quarterly else 0
    ebitda   = _f(quarterly[0].get("ebitda"))   if quarterly else 0
    icr = ebitda/interest if interest > 0 else 99  # Interest Coverage Ratio
    if   icr > 10: s=5; all_signals.append({"bull":True,  "cat":"Fundamental","text":f"Interest coverage strong ({icr:.1f}x)"})
    elif icr > 4:  s=3
    elif icr < 2:  s=0; all_signals.append({"bull":False, "cat":"Fundamental","text":f"Interest coverage weak ({icr:.1f}x) — debt risk"})
    else:          s=2
    score_detail["debt"]=s; raw_score+=s

    # [7] PE ratio (3 pts)
    if   0 < pe < 12: s=3; all_signals.append({"bull":True,  "cat":"Fundamental","text":f"PE {pe:.1f}x — undervalued"})
    elif 12 <= pe < 25: s=2
    elif pe >= 40:    s=0; all_signals.append({"bull":False, "cat":"Fundamental","text":f"PE {pe:.1f}x — overvalued"})
    else:             s=1
    score_detail["pe"]=s; raw_score+=s

    # ════════════════════════════════════════════════
    # BLOCK B: ANNOUNCEMENTS (max 25 pts)
    # ════════════════════════════════════════════════
    recent = anns[:7]
    new_order_ann   = next((a for a in recent    if a.get("is_new_order")),    None)
    concall_ann     = next((a for a in recent    if a.get("is_concall")),      None)
    mgmt_change_ann = next((a for a in anns[:10] if a.get("is_mgmt_change")), None)
    buyback_ann     = next((a for a in anns[:10] if a.get("is_buyback")),     None)
    expansion_ann   = next((a for a in anns[:10] if a.get("is_expansion")),   None)
    acq_ann         = next((a for a in anns[:10] if a.get("is_acquisition")), None)
    credit_ann      = next((a for a in anns[:10] if a.get("is_credit")),      None)

    # [8] New order (10 pts)
    s = 10 if new_order_ann else 0
    if new_order_ann: all_signals.append({"bull":True,"cat":"Announcement","text":f"Naya order: {new_order_ann['headline'][:55]}"})
    score_detail["new_order"]=s; raw_score+=s

    # [9] Concall (4 pts)
    s = 4 if concall_ann else 0
    if concall_ann: all_signals.append({"bull":True,"cat":"Announcement","text":"Concall/Investor meet announce hua"})
    score_detail["concall"]=s; raw_score+=s

    # [10] Buyback/Dividend (3 pts)
    s = 3 if buyback_ann else 0
    if buyback_ann: all_signals.append({"bull":True,"cat":"Announcement","text":f"Buyback/Dividend: {buyback_ann['headline'][:40]}"})
    score_detail["buyback"]=s; raw_score+=s

    # [11] Capacity expansion (3 pts)
    s = 3 if expansion_ann else 0
    if expansion_ann: all_signals.append({"bull":True,"cat":"Announcement","text":f"Capacity expansion: {expansion_ann['headline'][:40]}"})
    score_detail["expansion"]=s; raw_score+=s

    # [12] Acquisition/JV (3 pts)
    s = 3 if acq_ann else 0
    if acq_ann: all_signals.append({"bull":True,"cat":"Announcement","text":f"Acquisition/JV: {acq_ann['headline'][:40]}"})
    score_detail["acquisition"]=s; raw_score+=s

    # [13] Credit rating (2 pts)
    s = 2 if credit_ann else 0
    if credit_ann: all_signals.append({"bull":True,"cat":"Announcement","text":f"Credit: {credit_ann['headline'][:40]}"})
    score_detail["credit"]=s; raw_score+=s

    # [14] Management change (-6 pts)
    s = -6 if mgmt_change_ann else 0
    if mgmt_change_ann: all_signals.append({"bull":False,"cat":"Announcement","text":f"Mgmt change: {mgmt_change_ann['headline'][:45]}"})
    score_detail["mgmt"]=s; raw_score+=s

    # ════════════════════════════════════════════════
    # BLOCK C: TECHNICAL ANALYSIS (max 35 pts)
    # ════════════════════════════════════════════════
    tech = run_technical_analysis(history, price) if history and price > 0 else {}
    tech_score_raw = tech.get("score", 50)

    # Scale tech score (0-100) → contribution to raw_score (0-35)
    tech_contribution = (tech_score_raw / 100) * 35
    score_detail["technical"] = round(tech_contribution, 1)
    raw_score += tech_contribution

    # Add tech signals to master signals
    for sig in tech.get("signals", []):
        all_signals.append({**sig, "cat": "Technical"})

    # ════════════════════════════════════════════════
    # BLOCK D: MACRO / MARKET (max 15 pts)
    # ════════════════════════════════════════════════

    # [21] FII/DII (6 pts)
    fii = fii_dii.get("fii", {})
    dii = fii_dii.get("dii", {})
    fii_net = _f(fii.get("net", 0))
    dii_net = _f(dii.get("net", 0))
    if   fii_net > 500 and dii_net > 0:  s=6; all_signals.append({"bull":True,  "cat":"Macro","text":f"FII +₹{fii_net:.0f}Cr aur DII bhi buying"})
    elif fii_net > 200:                   s=4; all_signals.append({"bull":True,  "cat":"Macro","text":f"FII net buying +₹{fii_net:.0f}Cr"})
    elif fii_net > 0:                     s=3
    elif fii_net < -500:                  s=0; all_signals.append({"bull":False, "cat":"Macro","text":f"FII heavy selling ₹{fii_net:.0f}Cr"})
    elif fii_net < 0:                     s=1; all_signals.append({"bull":False, "cat":"Macro","text":f"FII selling ₹{fii_net:.0f}Cr"})
    else:                                 s=2
    score_detail["fii_dii"]=s; raw_score+=s

    # [22] Sector performance (4 pts)
    sector_score, sector_sent = _sector_sentiment(sectors, sector)
    s = int((sector_score/100)*4)
    if sector_sent == "bullish":  all_signals.append({"bull":True,  "cat":"Macro","text":f"{sector} sector aaj strong chal raha hai"})
    elif sector_sent == "bearish":all_signals.append({"bull":False, "cat":"Macro","text":f"{sector} sector weak hai aaj"})
    score_detail["sector"]=s; raw_score+=s

    # [23] Global sentiment (3 pts)
    global_score, global_sent = _global_sentiment(global_markets)
    s = int((global_score/100)*3)
    if   global_sent=="bullish": all_signals.append({"bull":True,  "cat":"Macro","text":"Global markets positive — Sensex/Dow up"})
    elif global_sent=="bearish": all_signals.append({"bull":False, "cat":"Macro","text":"Global markets negative — risk off mood"})
    score_detail["global"]=s; raw_score+=s

    # [24] Promoter holding (2 pts)
    promoter = _f(shareholding.get("promoter_pct"))
    if   promoter > 65: s=2; all_signals.append({"bull":True, "cat":"Macro","text":f"Promoter holding strong {promoter:.1f}%"})
    elif promoter > 45: s=1
    elif 0 < promoter < 30: s=0; all_signals.append({"bull":False,"cat":"Macro","text":f"Promoter holding low {promoter:.1f}%"})
    else:               s=1
    score_detail["promoter"]=s; raw_score+=s

    # ════════════════════════════════════════════════
    # FINAL PROBABILITY CALCULATION
    # ════════════════════════════════════════════════
    MAX_RAW = 125.0
    probability = max(5, min(95, (raw_score / MAX_RAW) * 100))

    bull_count = sum(1 for s in all_signals if s.get("bull"))
    bear_count = sum(1 for s in all_signals if not s.get("bull"))

    # Verdict
    if   probability >= 65: verdict = "RISE"
    elif probability >= 45: verdict = "WATCH"
    else:                   verdict = "AVOID"

    # Timeframe
    timeframe = None
    if verdict == "RISE":
        catalyst_boost = (8 if new_order_ann else 0) + (5 if concall_ann else 0) + \
                         (4 if tech.get("macd",{}).get("crossover")=="bullish" else 0)
        eff_prob = min(95, probability + catalyst_boost)
        for tf in TIMEFRAMES:
            if eff_prob >= tf["min_prob"]:
                timeframe = tf; break

    # Target / Stop Loss
    target = stop_loss = upside_pct = None
    if verdict == "RISE" and price > 0:
        # Upside scales with probability (65%→3%, 95%→25%)
        upside_pct = round(3 + (probability - 65) * 0.73, 1)
        upside_pct = max(3.0, min(25.0, upside_pct))
        target     = round(price * (1 + upside_pct/100), 1)
        # Stop loss based on ATR or fixed 3%
        if tech.get("support_resistance",{}).get("support",0) > 0:
            sr_sl = tech["support_resistance"]["support"] * 0.99
            stop_loss = round(max(sr_sl, price*0.96), 1)
        else:
            stop_loss = round(price * 0.97, 1)

    # Build alert message
    alert_msg = _build_alert_msg(symbol, name, probability, verdict, timeframe,
                                  price, target, stop_loss, upside_pct,
                                  all_signals, tech, fii_net, global_sent)

    return {
        # Identity
        "symbol":       symbol, "name": name, "sector": sector, "cap": cap,
        # Price
        "price":        price if price>0 else None,
        "change_pct":   change_pct,
        "high_52w":     high52, "low_52w": low52, "pe_ratio": pe if pe>0 else None,
        # Prediction
        "probability":  round(probability, 1),
        "verdict":      verdict,
        "timeframe":    timeframe,
        "confidence":   min(95, int(probability + bull_count*2 - bear_count*2)),
        # Trade setup
        "target":       target, "stop_loss": stop_loss, "upside_pct": upside_pct,
        # Fundamentals summary
        "qoq_growth":   qoq,   "yoy_growth": yoy,
        "rev_growth":   rev_growth, "margin_trend": margin_dir,
        # Announcements
        "has_new_order":  bool(new_order_ann),
        "has_concall":    bool(concall_ann),
        "has_mgmt_change":bool(mgmt_change_ann),
        "has_expansion":  bool(expansion_ann),
        # Technical summary
        "rsi":          tech.get("rsi"),
        "macd_signal":  tech.get("macd",{}).get("crossover") or tech.get("macd",{}).get("trend"),
        "ma_trend":     tech.get("moving_avg",{}).get("cross",""),
        "vol_surge":    tech.get("volume",{}).get("surge", False),
        # Macro
        "fii_net":      round(fii_net, 0),
        "dii_net":      round(dii_net, 0),
        "global_sent":  global_sent,
        # Signals
        "signals":      all_signals,
        "bull_count":   bull_count, "bear_count": bear_count,
        # Scores
        "score_detail": score_detail,
        "tech_detail":  tech,
        # Alert
        "alert_msg":    alert_msg,
        "timestamp":    datetime.now().strftime("%d %b %H:%M"),
    }


def _build_alert_msg(symbol, name, prob, verdict, tf, price, target, sl, upside,
                     signals, tech, fii_net, global_sent):
    if verdict != "RISE": return ""
    tf_label = tf["label"] if tf else "Jaldi"
    top_bulls = [s["text"] for s in signals if s.get("bull")][:4]
    rsi = tech.get("rsi")
    macd = tech.get("macd",{}).get("crossover") or tech.get("macd",{}).get("trend","")

    lines = [
        f"🚨 RISE ALERT: {symbol}",
        f"📌 {name}",
        f"💰 Price: ₹{price}  ({'+' if (price or 0)>=0 else ''}{round(prob,1)}% probability)",
        f"⏰ {tf_label}",
        f"🎯 Target: ₹{target}  |  🛑 Stop Loss: ₹{sl}",
        f"⬆️  Upside: +{upside}%",
        f"",
        f"📊 Technical: RSI={rsi}  MACD={macd}",
        f"🌍 FII: {'+'if fii_net>0 else ''}₹{int(fii_net)}Cr  Global: {global_sent}",
        f"",
        f"✅ Top Reasons:",
    ] + [f"   • {r}" for r in top_bulls]

    return "\n".join(lines)

# ── News + Prediction integration (added in V3) ──────────────────────────────
from price_predictor import predict_price, get_best_buy_sell_time, calc_risk_reward

def enrich_with_news_and_prediction(result: dict, news_data: dict, history: list) -> dict:
    """
    Add news sentiment score + price prediction + buy/sell timing to result.
    Called after analyze_company() in app.py.
    """
    if not result: return result

    # News score contribution (-5 to +5 pts boost)
    news_score = news_data.get("score", 0) if news_data else 0
    news_boost = news_score * 0.5
    result["news_score"]     = news_score
    result["news_sentiment"] = news_data.get("sentiment","neutral") if news_data else "neutral"
    result["top_news"]       = news_data.get("top_news",[])[:4] if news_data else []
    result["news_count"]     = news_data.get("total", 0) if news_data else 0

    # Adjust probability with news
    new_prob = min(95, max(5, result.get("probability",50) + news_boost))
    result["probability"] = round(new_prob, 1)

    # Price prediction
    if history and result.get("price"):
        try:
            from price_predictor import predict_price, get_best_buy_sell_time, calc_risk_reward
            pred = predict_price(
                current_price      = result["price"],
                history            = history,
                probability_score  = result.get("probability",50),
                tech_score         = result.get("tech_detail",{}).get("score",50),
                news_score         = news_score,
                fundamental_score  = 50,
            )
            result["prediction"] = pred

            tf = result.get("timeframe") or {}
            tf_days = tf.get("days", 5) if tf else 5
            timing = get_best_buy_sell_time(
                history        = history,
                current_price  = result["price"],
                timeframe_days = tf_days,
                atr            = result.get("tech_detail",{}).get("atr"),
            )
            result["timing"] = timing

            rr = calc_risk_reward(result["price"], result.get("target"), result.get("stop_loss"))
            result["risk_reward"] = rr
        except Exception as e:
            import logging; logging.getLogger("master_analyzer").error(f"Prediction error: {e}")

    return result
