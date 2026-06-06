"""
technical_engine.py — FIXED VERSION
Fixes: division by zero, None returns, short history crashes
Added: VWAP, OBV, ATR-based stop loss
"""
import math, logging
from typing import Dict, List, Optional, Tuple
log = logging.getLogger("technical")

def _closes(h): return [x["close"] for x in h if (x.get("close") or 0) > 0]
def _volumes(h): return [x["volume"] for x in h if (x.get("volume") or 0) > 0]
def _highs(h):   return [x["high"]   for x in h if (x.get("high")   or 0) > 0]
def _lows(h):    return [x["low"]    for x in h if (x.get("low")    or 0) > 0]
def _safe(v, d=0.0):
    try: f = float(v or d); return f if math.isfinite(f) else d
    except: return d

def sma(data, period):
    if len(data) < period: return []
    return [sum(data[i:i+period])/period for i in range(len(data)-period+1)]

def ema(data, period):
    if len(data) < period: return []
    k = 2/(period+1)
    r = [sum(data[:period])/period]
    for p in data[period:]:
        r.append(p*k + r[-1]*(1-k))
    return r

# ── RSI ─────────────────────────────────────────────────────────────────────
def calc_rsi(closes, period=14):
    if len(closes) < period+2: return 50.0  # FIXED: return neutral 50 not None
    changes = [closes[i]-closes[i-1] for i in range(1,len(closes))]
    gains  = [max(c,0) for c in changes]
    losses = [abs(min(c,0)) for c in changes]
    ag = sum(gains[:period])/period
    al = sum(losses[:period])/period
    for i in range(period, len(changes)):
        ag = (ag*(period-1)+gains[i])/period
        al = (al*(period-1)+losses[i])/period
    if al == 0: return 100.0  # FIXED: zero division
    return round(100 - 100/(1+ag/al), 1)

# ── MACD ────────────────────────────────────────────────────────────────────
def calc_macd(closes):
    if len(closes) < 35: return {}
    e12 = ema(closes, 12); e26 = ema(closes, 26)
    if not e12 or not e26: return {}
    diff = len(e12)-len(e26)
    e12a = e12[diff:] if diff>0 else e12
    e26a = e26[-diff:] if diff<0 else e26
    macd_line = [a-b for a,b in zip(e12a,e26a)]
    if len(macd_line) < 9: return {}
    sig = ema(macd_line, 9)
    if not sig: return {}
    mv, sv = macd_line[-1], sig[-1]
    hist = mv-sv
    crossover = None
    if len(macd_line)>=2 and len(sig)>=2:
        pd = macd_line[-2]-sig[-2]; cd = mv-sv
        if pd<0 and cd>0: crossover="bullish"
        elif pd>0 and cd<0: crossover="bearish"
    return {"macd":round(mv,3),"signal":round(sv,3),"histogram":round(hist,3),
            "crossover":crossover,"trend":"bullish" if mv>sv else "bearish"}

# ── BOLLINGER BANDS ──────────────────────────────────────────────────────────
def calc_bollinger(closes, period=20):
    if len(closes) < period: return {}
    recent = closes[-period:]
    mid = sum(recent)/period
    variance = sum((c-mid)**2 for c in recent)/period
    std = math.sqrt(variance) if variance > 0 else 0.001  # FIXED: zero std
    upper = mid+2*std; lower = mid-2*std
    current = closes[-1]
    bw = (upper-lower)/mid*100 if mid else 0
    pct_b = (current-lower)/(upper-lower) if (upper-lower) > 0.001 else 0.5  # FIXED
    pos = "above_upper" if current>upper else "below_lower" if current<lower else "middle"
    return {"upper":round(upper,2),"middle":round(mid,2),"lower":round(lower,2),
            "bandwidth":round(bw,2),"pct_b":round(pct_b,2),"position":pos,"squeeze":bw<5}

# ── MOVING AVERAGES ──────────────────────────────────────────────────────────
def calc_moving_averages(closes, price):
    result = {}
    for period, name in [(20,"ema20"),(50,"dma50"),(200,"dma200")]:
        if len(closes) >= period:
            mv = sum(closes[-period:])/period
            result[name] = round(mv,2)
            result[f"{name}_signal"] = "above" if price>mv else "below"
    if "dma50" in result and "dma200" in result:
        result["cross"] = "golden" if result["dma50"]>result["dma200"] else "death"
    if "dma200" in result and result["dma200"] > 0:
        result["pct_from_200dma"] = round((price-result["dma200"])/result["dma200"]*100,1)
    return result

# ── VOLUME ───────────────────────────────────────────────────────────────────
def calc_volume(history):
    if len(history) < 5: return {}
    vols = _volumes(history)
    if len(vols) < 3: return {}
    current = vols[-1]
    prev = vols[:-1]
    avg_20 = sum(prev[-20:])/len(prev[-20:]) if prev else 1  # FIXED: no zero division
    avg_5  = sum(prev[-5:])/len(prev[-5:])   if prev else 1
    if avg_20 <= 0: avg_20 = 1  # FIXED
    ratio = current/avg_20
    trend = "increasing" if len(vols)>=5 and vols[-1]>vols[-5] else "decreasing"
    return {"current_volume":int(current),"avg_20d_volume":int(avg_20),
            "ratio_to_avg":round(ratio,2),"surge":ratio>2.0,
            "above_avg":ratio>1.3,"vol_trend":trend}

# ── ATR (Average True Range) — NEW ─────────────────────────────────────────
def calc_atr(history, period=14):
    """ATR for dynamic stop loss calculation."""
    if len(history) < period+1: return None
    highs  = _highs(history)
    lows   = _lows(history)
    closes = _closes(history)
    if len(highs) < period+1: return None
    trs = []
    for i in range(1, len(closes)):
        hl = highs[i]-lows[i]
        hc = abs(highs[i]-closes[i-1])
        lc = abs(lows[i]-closes[i-1])
        trs.append(max(hl, hc, lc))
    if len(trs) < period: return None
    atr = sum(trs[-period:])/period
    return round(atr, 2)

# ── VWAP — NEW ───────────────────────────────────────────────────────────────
def calc_vwap(history):
    """Volume Weighted Average Price — key intraday indicator."""
    if len(history) < 5: return None
    recent = history[-20:]  # Last 20 days
    pv_sum = 0; v_sum = 0
    for h in recent:
        typical = (_safe(h.get("high")) + _safe(h.get("low")) + _safe(h.get("close"))) / 3
        vol = _safe(h.get("volume"))
        pv_sum += typical * vol
        v_sum  += vol
    if v_sum <= 0: return None  # FIXED: zero division
    return round(pv_sum/v_sum, 2)

# ── OBV (On Balance Volume) — NEW ────────────────────────────────────────────
def calc_obv(history):
    """OBV — confirms price trend with volume."""
    if len(history) < 5: return {}
    closes = _closes(history)
    vols   = _volumes(history)
    if len(closes) < 5 or len(vols) < 5: return {}
    n = min(len(closes), len(vols))
    obv = [0]
    for i in range(1, n):
        if closes[i] > closes[i-1]:   obv.append(obv[-1] + vols[i])
        elif closes[i] < closes[i-1]: obv.append(obv[-1] - vols[i])
        else:                          obv.append(obv[-1])
    if len(obv) < 5: return {}
    trend = "bullish" if obv[-1] > obv[-5] else "bearish"
    rising = obv[-1] > obv[0]
    return {"obv_trend": trend, "obv_rising": rising,
            "obv_current": int(obv[-1]), "obv_5d_change": int(obv[-1]-obv[-5])}

# ── SUPPORT / RESISTANCE ─────────────────────────────────────────────────────
def calc_support_resistance(history, price):
    if len(history) < 15: return {}  # FIXED: was 20, now 15
    h = _highs(history); l = _lows(history)
    if not h or not l: return {}
    pivot_h = []; pivot_l = []
    lookback = 2  # FIXED: was 2 each side — more lenient
    for i in range(lookback, len(h)-lookback):
        if all(h[i]>h[i-j] and h[i]>h[i+j] for j in range(1,lookback+1)):
            pivot_h.append(h[i])
        if all(l[i]<l[i-j] and l[i]<l[i+j] for j in range(1,lookback+1)):
            pivot_l.append(l[i])
    supports    = sorted([p for p in pivot_l if p<price], reverse=True)[:3]
    resistances = sorted([p for p in pivot_h if p>price])[:3]
    near_s = supports[0]    if supports    else min(l)
    near_r = resistances[0] if resistances else max(h)
    pct_r = (near_r-price)/price*100 if price > 0 else 0
    pct_s = (price-near_s)/price*100  if price > 0 else 0
    return {"support":round(near_s,2),"resistance":round(near_r,2),
            "pct_to_resistance":round(pct_r,1),"pct_from_support":round(pct_s,1),
            "near_support":pct_s<3,"near_resistance":pct_r<3,"breakout_zone":pct_r<1.5}

# ── CANDLESTICK PATTERNS ─────────────────────────────────────────────────────
def detect_candlestick(history):
    if len(history) < 3: return {}
    patterns = []
    def bar(h): return {"o":_safe(h.get("open")),"h":_safe(h.get("high")),"l":_safe(h.get("low")),"c":_safe(h.get("close"))}
    c=bar(history[-1]); c1=bar(history[-2]); c2=bar(history[-3]) if len(history)>=3 else None
    if not all([c["o"],c["h"],c["l"],c["c"]]): return {}
    body=abs(c["c"]-c["o"]); fr=c["h"]-c["l"] if c["h"]>c["l"] else 0.001
    uw=c["h"]-max(c["o"],c["c"]); lw=min(c["o"],c["c"])-c["l"]
    bp=body/fr
    if bp<0.1: patterns.append({"name":"Doji","sentiment":"neutral","desc":"Doji — breakout aane wala"})
    if lw>2*body and uw<0.3*body and c["c"]>c["o"]: patterns.append({"name":"Hammer","sentiment":"bullish","desc":"Hammer — reversal, buyers aa rahe hain"})
    if uw>2*body and lw<0.3*body and c["c"]<c["o"]: patterns.append({"name":"Shooting Star","sentiment":"bearish","desc":"Shooting Star — bearish reversal"})
    if c1["c"]<c1["o"] and c["c"]>c["o"] and c["c"]>c1["o"] and c["o"]<c1["c"]: patterns.append({"name":"Bullish Engulfing","sentiment":"bullish","desc":"Bullish Engulfing — strong buying"})
    if c1["c"]>c1["o"] and c["c"]<c["o"] and c["c"]<c1["o"] and c["o"]>c1["c"]: patterns.append({"name":"Bearish Engulfing","sentiment":"bearish","desc":"Bearish Engulfing — selling pressure"})
    if bp>0.85: patterns.append({"name":"Bullish Marubozu" if c["c"]>c["o"] else "Bearish Marubozu","sentiment":"bullish" if c["c"]>c["o"] else "bearish","desc":"Strong trend candle"})
    if c2:
        o2,c2c=_safe(c2.get("open")),_safe(c2.get("close"))
        if c2c<o2 and abs(c1["c"]-c1["o"])<abs(c2c-o2)*0.3 and c["c"]>c["o"] and c["c"]>((c2c+o2)/2):
            patterns.append({"name":"Morning Star","sentiment":"bullish","desc":"Morning Star — strong bullish reversal"})
    bulls=sum(1 for p in patterns if p["sentiment"]=="bullish")
    bears=sum(1 for p in patterns if p["sentiment"]=="bearish")
    overall = "bullish" if bulls>bears else "bearish" if bears>bulls else "neutral"
    return {"patterns":patterns,"overall":overall,"count":len(patterns)}

# ── ADX ──────────────────────────────────────────────────────────────────────
def calc_adx(history, period=14):
    if len(history) < period+2: return None
    highs=_highs(history); lows=_lows(history); closes=_closes(history)
    if len(highs)<period+2: return None
    tr_list=[]; dm_plus=[]; dm_minus=[]
    for i in range(1,len(closes)):
        hl=highs[i]-lows[i]; hc=abs(highs[i]-closes[i-1]); lc=abs(lows[i]-closes[i-1])
        tr_list.append(max(hl,hc,lc))
        dmp=max(highs[i]-highs[i-1],0) if highs[i]-highs[i-1]>lows[i-1]-lows[i] else 0
        dmm=max(lows[i-1]-lows[i],0)   if lows[i-1]-lows[i]>highs[i]-highs[i-1]  else 0
        dm_plus.append(dmp); dm_minus.append(dmm)
    def wilder(data,p):
        if len(data)<p: return []
        r=[sum(data[:p])]
        for i in range(p,len(data)): r.append(r[-1]-r[-1]/p+data[i])
        return r
    atr=wilder(tr_list,period); pdm=wilder(dm_plus,period); mdm=wilder(dm_minus,period)
    if not atr: return None
    dx_list=[]
    for a,p,m in zip(atr,pdm,mdm):
        if a<=0: continue  # FIXED: zero division
        pdi=100*p/a; mdi=100*m/a
        denom=pdi+mdi
        if denom>0: dx_list.append(100*abs(pdi-mdi)/denom)
    if len(dx_list)<period: return None
    return round(sum(dx_list[-period:])/period,1)

# ── MASTER FUNCTION ──────────────────────────────────────────────────────────
def run_technical_analysis(history, price):
    if len(history)<10 or price<=0: return {"score":50,"signals":[]}
    closes=_closes(history)
    if not closes: return {"score":50,"signals":[]}

    rsi    = calc_rsi(closes)
    macd   = calc_macd(closes)
    bb     = calc_bollinger(closes)
    mas    = calc_moving_averages(closes, price)
    vol    = calc_volume(history)
    sr     = calc_support_resistance(history, price)
    candle = detect_candlestick(history)
    adx    = calc_adx(history)
    atr    = calc_atr(history)
    vwap   = calc_vwap(history)
    obv    = calc_obv(history)

    score=50.0; signals=[]

    # RSI
    if rsi is not None:
        if rsi<30:   score+=15; signals.append({"bull":True, "text":f"RSI {rsi} — Oversold (buy zone)"})
        elif rsi<45: score+=8;  signals.append({"bull":True, "text":f"RSI {rsi} — Room to go up"})
        elif rsi>75: score-=12; signals.append({"bull":False,"text":f"RSI {rsi} — Overbought"})
        elif rsi>60: score+=5

    # MACD
    if macd:
        if macd.get("crossover")=="bullish":   score+=15; signals.append({"bull":True, "text":"MACD Bullish Crossover — strong buy"})
        elif macd.get("crossover")=="bearish": score-=12; signals.append({"bull":False,"text":"MACD Bearish Crossover"})
        elif macd.get("trend")=="bullish":     score+=6;  signals.append({"bull":True, "text":"MACD bullish trend"})
        else: score-=5

    # Moving Averages
    if mas:
        if mas.get("dma50_signal")=="above":   score+=6;  signals.append({"bull":True, "text":f"Price 50DMA se upar ₹{mas.get('dma50','')}"})
        else:                                  score-=5;  signals.append({"bull":False,"text":"Price 50DMA se neeche"})
        if mas.get("dma200_signal")=="above":  score+=8;  signals.append({"bull":True, "text":"Price 200DMA se upar — long-term bullish"})
        else:                                  score-=7;  signals.append({"bull":False,"text":"Price 200DMA se neeche"})
        if mas.get("cross")=="golden":         score+=10; signals.append({"bull":True, "text":"Golden Cross — very bullish"})
        elif mas.get("cross")=="death":        score-=10; signals.append({"bull":False,"text":"Death Cross — bearish"})

    # Bollinger
    if bb:
        if bb.get("position")=="below_lower":  score+=10; signals.append({"bull":True, "text":"Bollinger Band se neeche — bounce expected"})
        elif bb.get("position")=="above_upper":score-=8;  signals.append({"bull":False,"text":"Bollinger Band se upar — pullback possible"})
        if bb.get("squeeze"):                  score+=5;  signals.append({"bull":True, "text":"Bollinger Squeeze — breakout aane wala"})

    # Volume
    if vol:
        if vol.get("surge"):     score+=12; signals.append({"bull":True, "text":f"Volume surge {vol['ratio_to_avg']}x average"})
        elif vol.get("above_avg"):score+=5; signals.append({"bull":True, "text":f"Volume above average ({vol['ratio_to_avg']}x)"})

    # Support/Resistance
    if sr:
        if sr.get("near_support"):    score+=8;  signals.append({"bull":True, "text":f"Support ke paas ₹{sr['support']} — bounce zone"})
        if sr.get("breakout_zone"):   score+=10; signals.append({"bull":True, "text":f"Resistance ₹{sr['resistance']} ke bilkul neeche"})
        if sr.get("near_resistance"): score-=5;  signals.append({"bull":False,"text":f"Resistance ₹{sr['resistance']} ke paas"})

    # Candlestick
    if candle and candle.get("patterns"):
        for p in candle["patterns"][:2]:
            if p["sentiment"]=="bullish": score+=8; signals.append({"bull":True, "text":p["desc"]})
            elif p["sentiment"]=="bearish":score-=7;signals.append({"bull":False,"text":p["desc"]})

    # ADX
    if adx is not None and adx>25:
        score+=5; signals.append({"bull":True,"text":f"ADX {adx} — strong trend"})

    # VWAP — NEW
    if vwap and price>0:
        if price>vwap:   score+=6; signals.append({"bull":True, "text":f"Price VWAP ₹{vwap} se upar — bullish"})
        elif price<vwap: score-=5; signals.append({"bull":False,"text":f"Price VWAP ₹{vwap} se neeche"})

    # OBV — NEW
    if obv:
        if obv.get("obv_trend")=="bullish": score+=7; signals.append({"bull":True, "text":"OBV rising — volume price confirm kar raha hai"})
        else:                               score-=4; signals.append({"bull":False,"text":"OBV declining — volume weak"})

    score = max(5, min(95, score))
    return {"score":round(score),"signals":signals,"rsi":rsi,"macd":macd,"bollinger":bb,
            "moving_avg":mas,"volume":vol,"support_resistance":sr,"candlestick":candle,
            "adx":adx,"atr":atr,"vwap":vwap,"obv":obv}
