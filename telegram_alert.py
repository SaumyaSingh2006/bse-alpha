"""
telegram_alert.py
Sends Telegram messages when RISE signals are detected.
Setup: Create bot via @BotFather, set TELEGRAM_TOKEN + TELEGRAM_CHAT_ID env vars.
"""
import os, logging, asyncio
import httpx

log = logging.getLogger("telegram")

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

def is_configured() -> bool:
    return bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID)

async def send_message(text: str) -> bool:
    """Send a Telegram message. Returns True if successful."""
    if not is_configured():
        log.warning("Telegram not configured — set TELEGRAM_TOKEN and TELEGRAM_CHAT_ID env vars")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                log.info(f"Telegram message sent ✅")
                return True
            else:
                log.warning(f"Telegram error: {resp.status_code} {resp.text[:100]}")
                return False
    except Exception as e:
        log.error(f"Telegram send failed: {e}")
        return False

def build_rise_message(result: dict) -> str:
    """Build a rich Telegram alert message for a RISE signal."""
    tf    = result.get("timeframe") or {}
    tf_label = tf.get("label", "—")
    p     = result.get("probability", 0)
    price = result.get("price", "—")
    target= result.get("target", "—")
    sl    = result.get("stop_loss", "—")
    up    = result.get("upside_pct", 0)
    rsi   = result.get("rsi")
    macd  = result.get("macd_signal", "")
    fii   = result.get("fii_net", 0)
    qoq   = result.get("qoq_growth", 0)

    # Top bull signals
    sigs  = result.get("signals", [])
    bulls = [s["text"] for s in sigs if s.get("bull")][:4]
    reasons = "\n".join(f"   • {r}" for r in bulls) if bulls else "   • Multiple positive signals"

    msg = (
        f"🚨 <b>RISE ALERT — BSE ALPHA</b>\n\n"
        f"📌 <b>{result.get('name', result.get('symbol', ''))}</b>\n"
        f"💹 Symbol: <code>{result.get('symbol', '')}</code>  |  "
        f"{result.get('sector', '')}  |  {result.get('cap', '')}\n\n"
        f"💰 Price: <b>₹{price}</b>  "
        f"({'+' if (result.get('change_pct') or 0) >= 0 else ''}{result.get('change_pct', 0):.1f}%)\n"
        f"📊 Probability: <b>{p:.0f}%</b>\n"
        f"⏰ Timeframe: <b>{tf_label}</b>\n\n"
        f"🎯 Target: <b>₹{target}</b>  |  "
        f"🛑 Stop Loss: <b>₹{sl}</b>  |  "
        f"⬆️ Upside: <b>+{up}%</b>\n\n"
        f"📈 Technical: RSI={rsi}  MACD={macd}\n"
        f"🏦 FII: {'+' if fii >= 0 else ''}₹{int(fii)}Cr  |  QoQ: {'+' if qoq >= 0 else ''}{qoq}%\n\n"
        f"✅ <b>Key Reasons:</b>\n{reasons}\n\n"
        f"⚠️ <i>Not SEBI advice. Do your own research.</i>"
    )
    return msg

async def send_rise_alert(result: dict) -> bool:
    """Send RISE alert to Telegram."""
    msg = build_rise_message(result)
    return await send_message(msg)

async def send_scan_summary(rise_count: int, total: int, scan_no: int) -> bool:
    """Send brief scan completion summary."""
    if rise_count == 0:
        return True  # Don't spam if no signals
    msg = (
        f"📊 <b>BSE Alpha Scan #{scan_no} Complete</b>\n\n"
        f"🔥 RISE signals: <b>{rise_count}/{total}</b> companies\n"
        f"⏰ Check app for details."
    )
    return await send_message(msg)

async def test_telegram() -> dict:
    """Test if Telegram is working. Returns status dict."""
    if not is_configured():
        return {"ok": False, "reason": "Not configured — set TELEGRAM_TOKEN and TELEGRAM_CHAT_ID"}
    msg = "✅ <b>BSE Alpha Connected!</b>\n\nTelegram alerts are working. You will receive RISE signals here."
    ok = await send_message(msg)
    return {"ok": ok, "reason": "Message sent successfully" if ok else "Failed to send"}
