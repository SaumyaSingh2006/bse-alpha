"""
win_tracker.py
Tracks RISE alert accuracy — kitne calls sach mein oopar gaye.
Saves to alerts_history.json (persists across scans).
"""
import json, os, logging
from datetime import datetime
from typing import Dict, List, Optional

log = logging.getLogger("win_tracker")
HISTORY_FILE = "alerts_history.json"

def _load() -> dict:
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE) as f:
                return json.load(f)
        except: pass
    return {"alerts": [], "stats": {"total": 0, "wins": 0, "losses": 0, "pending": 0}}

def _save(data: dict):
    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log.error(f"Win tracker save failed: {e}")

def record_alert(result: dict):
    """Record a new RISE alert for future tracking."""
    data = _load()
    alert = {
        "id":          f"{result['symbol']}_{datetime.now().strftime('%Y%m%d_%H%M')}",
        "symbol":      result["symbol"],
        "name":        result.get("name", ""),
        "alert_time":  datetime.now().strftime("%d %b %Y %H:%M"),
        "alert_price": result.get("price"),
        "target":      result.get("target"),
        "stop_loss":   result.get("stop_loss"),
        "probability": result.get("probability"),
        "timeframe":   result.get("timeframe", {}).get("label", "") if result.get("timeframe") else "",
        "upside_pct":  result.get("upside_pct"),
        "outcome":     "pending",   # pending / win / loss / partial
        "exit_price":  None,
        "actual_return": None,
        "verdict_time":  None,
    }
    data["alerts"].insert(0, alert)
    data["alerts"] = data["alerts"][:200]  # Keep last 200
    data["stats"]["total"] += 1
    data["stats"]["pending"] += 1
    _save(data)
    log.info(f"Win tracker: recorded {result['symbol']} @ ₹{result.get('price')}")

def update_outcome(alert_id: str, outcome: str, exit_price: float):
    """Update alert outcome when price hits target or stop loss."""
    data = _load()
    for alert in data["alerts"]:
        if alert["id"] == alert_id:
            alert["outcome"]      = outcome
            alert["exit_price"]   = exit_price
            alert["verdict_time"] = datetime.now().strftime("%d %b %Y %H:%M")
            if alert["alert_price"] and exit_price:
                ret = (exit_price - alert["alert_price"]) / alert["alert_price"] * 100
                alert["actual_return"] = round(ret, 2)
            # Update stats
            data["stats"]["pending"] = max(0, data["stats"]["pending"] - 1)
            if outcome == "win":     data["stats"]["wins"]   += 1
            elif outcome == "loss":  data["stats"]["losses"] += 1
            break
    _save(data)

def get_stats() -> dict:
    """Get win rate statistics."""
    data = _load()
    stats = data["stats"]
    decided = stats["wins"] + stats["losses"]
    win_rate = round(stats["wins"] / decided * 100, 1) if decided > 0 else 0
    recent = data["alerts"][:10]
    recent_wins = sum(1 for a in recent if a["outcome"] == "win")
    recent_decided = sum(1 for a in recent if a["outcome"] in ("win","loss","partial"))
    recent_rate = round(recent_wins / recent_decided * 100, 1) if recent_decided > 0 else 0

    return {
        "total_alerts":   stats["total"],
        "wins":           stats["wins"],
        "losses":         stats["losses"],
        "pending":        stats["pending"],
        "win_rate":       win_rate,
        "recent_win_rate":recent_rate,
        "decided":        decided,
        "recent_alerts":  recent[:20],
        "best_return":    max((a["actual_return"] or 0 for a in data["alerts"] if a["actual_return"]), default=0),
        "avg_return":     round(sum(a["actual_return"] or 0 for a in data["alerts"] if a["actual_return"]) /
                               max(1, sum(1 for a in data["alerts"] if a["actual_return"])), 2),
    }

def get_history(limit=50) -> List[dict]:
    """Get alert history."""
    data = _load()
    return data["alerts"][:limit]

def auto_check_outcomes(current_prices: Dict[str, float]):
    """Auto-check if pending alerts hit target or stop loss."""
    data = _load()
    updated = False
    for alert in data["alerts"]:
        if alert["outcome"] != "pending": continue
        sym = alert["symbol"]
        if sym not in current_prices: continue
        curr = current_prices[sym]
        target = alert.get("target")
        sl     = alert.get("stop_loss")
        if target and curr >= target:
            update_outcome(alert["id"], "win", curr)
            log.info(f"🎯 Win: {sym} hit target ₹{target}")
            updated = True
        elif sl and curr <= sl:
            update_outcome(alert["id"], "loss", curr)
            log.info(f"🛑 Loss: {sym} hit stop loss ₹{sl}")
            updated = True
    return updated
