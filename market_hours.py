"""
market_hours.py
BSE/NSE market hours: 9:15 AM — 3:30 PM IST, Mon-Fri
Excludes weekends and Indian public holidays 2025-2026
"""
from datetime import datetime, date
import pytz

IST = pytz.timezone("Asia/Kolkata")

# BSE holidays 2025-2026
BSE_HOLIDAYS = {
    date(2025,1,26), date(2025,2,19), date(2025,3,14),
    date(2025,4,10), date(2025,4,14), date(2025,4,18),
    date(2025,5,1),  date(2025,8,15), date(2025,8,27),
    date(2025,10,2), date(2025,10,20),date(2025,10,21),
    date(2025,10,24),date(2025,11,5), date(2025,11,14),
    date(2025,12,25),
    date(2026,1,26), date(2026,3,19), date(2026,4,2),
    date(2026,4,6),  date(2026,4,14), date(2026,5,1),
    date(2026,8,15), date(2026,10,2), date(2026,11,2),
}

def now_ist() -> datetime:
    return datetime.now(IST)

def is_market_open() -> bool:
    """Returns True if BSE is currently open."""
    now = now_ist()
    if now.weekday() >= 5: return False          # Saturday/Sunday
    if now.date() in BSE_HOLIDAYS: return False  # Holiday
    market_open  = now.replace(hour=9,  minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close

def is_pre_market() -> bool:
    """9:00–9:15 AM IST — pre-open session."""
    now = now_ist()
    if now.weekday() >= 5: return False
    if now.date() in BSE_HOLIDAYS: return False
    pre_open  = now.replace(hour=9,  minute=0,  second=0, microsecond=0)
    mkt_open  = now.replace(hour=9,  minute=15, second=0, microsecond=0)
    return pre_open <= now < mkt_open

def next_market_open_seconds() -> int:
    """Seconds until next market opening."""
    now = now_ist()
    candidate = now.replace(hour=9, minute=15, second=0, microsecond=0)
    # If past today's open, go to next trading day
    if now >= candidate:
        from datetime import timedelta
        candidate += timedelta(days=1)
    # Skip weekends and holidays
    from datetime import timedelta
    while candidate.weekday() >= 5 or candidate.date() in BSE_HOLIDAYS:
        candidate += timedelta(days=1)
    diff = (candidate - now).total_seconds()
    return max(0, int(diff))

def market_status() -> dict:
    now = now_ist()
    open_flag = is_market_open()
    pre = is_pre_market()
    if open_flag:
        status = "OPEN"
        close_time = now.replace(hour=15, minute=30, second=0, microsecond=0)
        secs_left = max(0, int((close_time - now).total_seconds()))
    elif pre:
        status = "PRE-OPEN"
        secs_left = next_market_open_seconds()
    else:
        status = "CLOSED"
        secs_left = next_market_open_seconds()
    return {
        "status": status,
        "is_open": open_flag,
        "ist_time": now.strftime("%H:%M:%S"),
        "ist_date": now.strftime("%d %b %Y"),
        "day": now.strftime("%A"),
        "is_holiday": now.date() in BSE_HOLIDAYS,
        "seconds_to_next": secs_left,
    }
