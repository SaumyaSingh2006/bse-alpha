"""
price_predictor.py
Calculates:
  1. Price prediction for next 7/15/30 days
  2. Best time to BUY (day of week + time of day)
  3. Best time to SELL for maximum profit
  4. Prediction graph data points
  5. Confidence interval (upper/lower bounds)
"""

import math, logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import pytz

log = logging.getLogger("predictor")
IST = pytz.timezone("Asia/Kolkata")

def _safe(v, d=0.0):
    try: f=float(v or d); return f if math.isfinite(f) else d
    except: return d

# ── Historical pattern analysis ───────────────────────────────────────────────
def analyze_price_patterns(history: List[Dict]) -> Dict:
    """
    Analyze price history for patterns:
    - Average % move per day
    - Volatility (std dev)
    - Momentum (recent vs older trend)
    - Day-of-week performance
    """
    if len(history) < 10:
        return {"avg_daily_return": 0, "volatility": 2.0, "momentum": 0, "trend": "neutral"}

    closes = [_safe(h.get("close")) for h in history if _safe(h.get("close")) > 0]
    if len(closes) < 5:
        return {"avg_daily_return": 0, "volatility": 2.0, "momentum": 0, "trend": "neutral"}

    # Daily returns
    returns = [(closes[i]-closes[i-1])/closes[i-1]*100 for i in range(1,len(closes))]
    avg_return  = sum(returns)/len(returns)
    volatility  = math.sqrt(sum((r-avg_return)**2 for r in returns)/len(returns))

    # Recent momentum (last 10 vs previous 10)
    recent = sum(returns[-10:])/10 if len(returns)>=10 else avg_return
    older  = sum(returns[-20:-10])/10 if len(returns)>=20 else avg_return
    momentum = recent - older

    # Trend
    if avg_return > 0.3 and momentum > 0: trend = "strong_up"
    elif avg_return > 0.1:                trend = "up"
    elif avg_return < -0.3:               trend = "down"
    else:                                 trend = "sideways"

    # 52-week stats
    highs  = [_safe(h.get("high"))  for h in history if _safe(h.get("high"))>0]
    lows   = [_safe(h.get("low"))   for h in history if _safe(h.get("low"))>0]
    h52    = max(highs[-252:]) if len(highs)>=252 else max(highs) if highs else 0
    l52    = min(lows[-252:])  if len(lows)>=252  else min(lows)  if lows  else 0

    return {
        "avg_daily_return": round(avg_return, 3),
        "volatility":       round(volatility, 2),
        "momentum":         round(momentum, 3),
        "trend":            trend,
        "high_52w":         round(h52, 2),
        "low_52w":          round(l52, 2),
    }

# ── Price prediction ──────────────────────────────────────────────────────────
def predict_price(
    current_price: float,
    history: List[Dict],
    probability_score: float,   # 0-100 from master_analyzer
    tech_score: float,          # 0-100 from technical_engine
    news_score: float,          # -10 to +10 from news_fetcher
    fundamental_score: float,   # 0-100 implied
) -> Dict:
    """
    Generate price prediction for 7, 15, 30 days.
    Also generates graph data points.
    """
    if current_price <= 0:
        return {}

    patterns = analyze_price_patterns(history)
    base_daily = patterns["avg_daily_return"]
    vol        = patterns["volatility"]
    momentum   = patterns["momentum"]

    # Adjusted expected daily return based on all signals
    # probability_score 65-95 → 0.2% to 0.6% daily boost
    prob_boost = (probability_score - 50) / 100 * 0.4 if probability_score > 50 else 0
    tech_boost = (tech_score - 50) / 100 * 0.2 if tech_score > 50 else 0
    news_boost = news_score / 100 * 0.15
    mom_boost  = momentum * 0.3

    adjusted_daily = base_daily + prob_boost + tech_boost + news_boost + mom_boost
    adjusted_daily = max(-1.5, min(2.0, adjusted_daily))  # Cap at reasonable range

    # Predictions
    def pred(days):
        # Compound return with some mean reversion
        reversion = 0.02  # 2% per day pull toward 0
        total = adjusted_daily
        for _ in range(days):
            total = total * (1 - reversion) + adjusted_daily * reversion
        compound = current_price * ((1 + adjusted_daily/100) ** days)
        confidence_range = vol * math.sqrt(days) / 100 * current_price
        return {
            "price":     round(compound, 1),
            "change_pct":round((compound-current_price)/current_price*100, 1),
            "upper":     round(compound + confidence_range * 1.5, 1),
            "lower":     round(max(current_price*0.85, compound - confidence_range * 1.5), 1),
        }

    p7  = pred(7)
    p15 = pred(15)
    p30 = pred(30)

    # Graph data — 30 day projection with confidence band
    graph_points = []
    ci = vol / 100 * current_price
    for day in range(31):
        p = current_price * ((1 + adjusted_daily/100) ** day)
        spread = ci * math.sqrt(max(1, day)) * 1.2
        graph_points.append({
            "day":   day,
            "price": round(p, 1),
            "upper": round(p + spread, 1),
            "lower": round(max(current_price*0.8, p - spread), 1),
        })

    return {
        "current_price": current_price,
        "7_days":        p7,
        "15_days":       p15,
        "30_days":       p30,
        "graph_data":    graph_points,
        "daily_return":  round(adjusted_daily, 3),
        "volatility":    vol,
        "trend":         patterns["trend"],
    }

# ── Best buy/sell timing ──────────────────────────────────────────────────────
def get_best_buy_sell_time(
    history: List[Dict],
    current_price: float,
    timeframe_days: int,
    atr: Optional[float] = None,
) -> Dict:
    """
    Calculate best time to buy and sell.

    Buy timing rules (research-based):
    - Intraday: 9:15-9:45 AM (gap-open reversal) or 2:00-2:30 PM (afternoon dip)
    - Short-term: Monday/Tuesday morning (weekend selloff absorbed)
    - Post-result: 2-3 days after quarterly result

    Sell timing rules:
    - Intraday: 3:00-3:20 PM (close-of-day markup)
    - Short-term: Thursday/Friday (institutional week-end buying)
    - Near resistance: Within 1-2% of 52-week high

    Returns specific time windows and reasoning.
    """
    patterns = analyze_price_patterns(history)
    vol = patterns.get("volatility", 2.0)
    trend = patterns.get("trend", "neutral")

    # Intraday timing
    if timeframe_days == 0:  # Intraday
        buy_time  = "9:20 AM – 9:45 AM"
        buy_why   = "Gap-open ke baad sentiment clear ho jaata hai. Sabse accurate entry."
        sell_time = "2:45 PM – 3:15 PM"
        sell_why  = "Institutional buying closes positions near market end."
        if vol > 3:  # High volatility
            buy_time = "10:00 AM – 10:30 AM"
            buy_why  = "High volatility — 10am ke baad price stable hoti hai. Safer entry."

    elif timeframe_days <= 3:  # 1-3 days
        buy_time  = "Monday/Tuesday 9:30 AM – 10:30 AM"
        buy_why   = "Weekend ke baad sentiment clear. Institutional fresh buying Monday pe hoti hai."
        sell_time = "Thursday/Friday 2:00 PM – 3:00 PM"
        sell_why  = "Week-end pe FII/DII position close karte hain. Price higher hoti hai."

    elif timeframe_days <= 7:  # 3-7 days
        buy_time  = "Pehle 2 din andar — morning session (9:30-11:00 AM)"
        buy_why   = "Catalyst fresh hai — zyada wait karne se opportunity miss ho sakti hai."
        sell_time = "5-7 din ke andar — jab 80% target hit ho"
        sell_why  = "Full target wait mat karo — 80% milte hi book karo. Risk reduce hota hai."

    elif timeframe_days <= 14:  # 1-2 weeks
        buy_time  = "Is hafte ke beech (Tue-Wed) dip pe"
        buy_why   = "Weekly chart mein mid-week dip aata hai — better average milta hai."
        sell_time = "Agli week ke Thu-Fri near target"
        sell_why  = "2nd week pe price sustain karta hai agar fundamental strong ho."

    else:  # 2-4 weeks
        buy_time  = "SIP style — 2-3 kiston mein kharido"
        buy_why   = "Ek baar mein mat kharido — price aur neeche aa sakti hai. Average karo."
        sell_time = "Target hit hone pe ya 25-30 din ke andar"
        sell_why  = "Momentum 30 din ke baad slow ho jaata hai. Position close karo."

    # Stop loss recommendation
    sl_pct = max(2.0, min(5.0, vol * 0.8)) if atr else 3.0
    if trend == "strong_up": sl_pct = max(2.0, sl_pct - 0.5)
    elif trend == "down":    sl_pct = min(5.0, sl_pct + 1.0)

    # Position sizing hint
    if vol > 4:
        position_hint = "Chhoti position rakho (max 5-7% of portfolio) — zyada volatile hai"
    elif vol > 2.5:
        position_hint = "Medium position (8-12% of portfolio)"
    else:
        position_hint = "Normal position (10-15% of portfolio) — relatively stable hai"

    return {
        "buy_time":      buy_time,
        "buy_reason":    buy_why,
        "sell_time":     sell_time,
        "sell_reason":   sell_why,
        "stop_loss_pct": round(sl_pct, 1),
        "position_size": position_hint,
        "volatility_rating": "High" if vol>3.5 else "Medium" if vol>2 else "Low",
    }

# ── Risk/reward ratio ─────────────────────────────────────────────────────────
def calc_risk_reward(
    current_price: float,
    target: float,
    stop_loss: float,
) -> Dict:
    if not current_price or not target or not stop_loss:
        return {"ratio": 0, "verdict": "unknown"}

    reward = target - current_price
    risk   = current_price - stop_loss

    if risk <= 0:
        return {"ratio": 99, "verdict": "excellent"}

    ratio = round(reward / risk, 1)

    if   ratio >= 3:   verdict = "🟢 Excellent (3:1+)"
    elif ratio >= 2:   verdict = "🟡 Good (2:1)"
    elif ratio >= 1.5: verdict = "🟠 Acceptable (1.5:1)"
    else:              verdict = "🔴 Poor (<1.5:1) — skip"

    return {
        "ratio":   ratio,
        "reward":  round(reward, 1),
        "risk":    round(risk, 1),
        "verdict": verdict,
    }
