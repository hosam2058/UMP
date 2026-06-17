"""
نظام التداول الآلي المتكامل عبر MetaApi → MT5
يتصل بحساب MT5 ويُنفّذ الصفقات تلقائياً بناءً على إشارات المحرك الذكي
"""
import os
import logging
import requests
import json
import time
from datetime import datetime
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)

# ── إعدادات MetaApi ──────────────────────────────────────────────
META_API_TOKEN   = os.getenv("META_API_TOKEN", "")
META_ACCOUNT_ID  = os.getenv("META_ACCOUNT_ID", "")
META_BASE_URL    = "https://mt-client-api-v1.london.agiliumtrade.ai"

# ── إعدادات إدارة المخاطر ────────────────────────────────────────
DEFAULT_LOT       = float(os.getenv("AUTO_LOT", "0.01"))   # حجم اللوت الافتراضي
MAX_OPEN_TRADES   = int(os.getenv("MAX_TRADES", "3"))       # أقصى صفقات مفتوحة
RISK_PERCENT      = float(os.getenv("RISK_PERCENT", "1.0")) # نسبة المخاطرة من الحساب
SYMBOL            = "XAUUSD"

# ── حالة النظام ──────────────────────────────────────────────────
auto_trading_enabled = False   # يُفعَّل من أمر الأدمن
_session = requests.Session()


# ═══════════════════════════════════════════════════════════════
#  MetaApi REST CLIENT
# ═══════════════════════════════════════════════════════════════
def _headers() -> dict:
    return {
        "auth-token": META_API_TOKEN,
        "Content-Type": "application/json",
    }


def _get(endpoint: str, timeout: int = 15) -> Optional[dict]:
    try:
        url = f"{META_BASE_URL}{endpoint}"
        r = _session.get(url, headers=_headers(), timeout=timeout)
        if r.status_code == 200:
            return r.json()
        logger.warning(f"MetaApi GET {endpoint} → {r.status_code}: {r.text[:200]}")
    except Exception as e:
        logger.error(f"MetaApi GET error: {e}")
    return None


def _post(endpoint: str, body: dict, timeout: int = 15) -> Optional[dict]:
    try:
        url = f"{META_BASE_URL}{endpoint}"
        r = _session.post(url, headers=_headers(), json=body, timeout=timeout)
        if r.status_code in (200, 201):
            return r.json()
        logger.warning(f"MetaApi POST {endpoint} → {r.status_code}: {r.text[:300]}")
    except Exception as e:
        logger.error(f"MetaApi POST error: {e}")
    return None


def _delete(endpoint: str, timeout: int = 15) -> bool:
    try:
        url = f"{META_BASE_URL}{endpoint}"
        r = _session.delete(url, headers=_headers(), timeout=timeout)
        return r.status_code in (200, 204)
    except Exception as e:
        logger.error(f"MetaApi DELETE error: {e}")
    return False


# ═══════════════════════════════════════════════════════════════
#  ACCOUNT INFO
# ═══════════════════════════════════════════════════════════════
def get_account_info() -> Optional[dict]:
    """جلب معلومات الحساب (الرصيد، الإيكويتي، الهامش...)"""
    data = _get(f"/users/current/accounts/{META_ACCOUNT_ID}/account-information")
    return data


def get_account_balance() -> float:
    """رصيد الحساب"""
    info = get_account_info()
    return float(info.get("balance", 0)) if info else 0.0


def check_connection() -> dict:
    """فحص حالة الاتصال بـ MT5"""
    data = _get(f"/users/current/accounts/{META_ACCOUNT_ID}/connection/health")
    if data:
        return {
            "connected": True,
            "broker": data.get("connected", False),
            "status": data.get("healthStatus", "unknown"),
        }
    return {"connected": False, "broker": False, "status": "error"}


# ═══════════════════════════════════════════════════════════════
#  POSITIONS
# ═══════════════════════════════════════════════════════════════
def get_open_positions() -> List[dict]:
    """جلب الصفقات المفتوحة"""
    data = _get(f"/users/current/accounts/{META_ACCOUNT_ID}/positions")
    if isinstance(data, list):
        return [p for p in data if p.get("symbol") == SYMBOL]
    return []


def count_open_positions() -> int:
    return len(get_open_positions())


def close_position(position_id: str) -> bool:
    """إغلاق صفقة محددة"""
    ok = _delete(f"/users/current/accounts/{META_ACCOUNT_ID}/positions/{position_id}")
    logger.info(f"{'✅' if ok else '❌'} إغلاق صفقة {position_id}")
    return ok


def close_all_positions() -> int:
    """إغلاق جميع الصفقات المفتوحة - يُعيد عدد المُغلَقة"""
    positions = get_open_positions()
    closed = 0
    for p in positions:
        if close_position(p["id"]):
            closed += 1
    return closed


# ═══════════════════════════════════════════════════════════════
#  PLACE ORDER
# ═══════════════════════════════════════════════════════════════
def calculate_lot(balance: float, sl_pips: float) -> float:
    """حساب حجم اللوت بناءً على إدارة المخاطر"""
    if balance <= 0 or sl_pips <= 0:
        return DEFAULT_LOT
    # قيمة النقطة لـ XAUUSD ≈ $1 لكل 0.01 لوت
    pip_value_per_lot = 10.0
    risk_amount = balance * (RISK_PERCENT / 100)
    lot = risk_amount / (sl_pips * pip_value_per_lot)
    # تقريب لأقرب 0.01 وتحديد الحد الأقصى
    lot = round(max(0.01, min(lot, 5.0)), 2)
    return lot


def place_order(signal: dict) -> Optional[dict]:
    """
    تنفيذ صفقة بناءً على إشارة المحرك الذكي
    signal: dict يحتوي على direction, entry, sl, tp1, tp2, tp3
    """
    global auto_trading_enabled

    if not auto_trading_enabled:
        return None

    if not META_API_TOKEN or not META_ACCOUNT_ID:
        logger.error("❌ META_API_TOKEN أو META_ACCOUNT_ID غير مُعيَّن")
        return None

    # التحقق من عدد الصفقات المفتوحة
    open_count = count_open_positions()
    if open_count >= MAX_OPEN_TRADES:
        logger.warning(f"⚠️ وصل حد الصفقات المفتوحة: {open_count}/{MAX_OPEN_TRADES}")
        return None

    direction = signal.get("direction", "").upper()  # BUY أو SELL
    entry     = signal.get("entry", 0)
    sl        = signal.get("sl", 0)
    tp1       = signal.get("tp1", 0)
    tp2       = signal.get("tp2", 0)

    if not direction or not entry:
        return None

    # حساب حجم اللوت بناءً على المخاطرة
    balance  = get_account_balance()
    sl_pips  = abs(entry - sl) if sl else 10.0
    lot      = calculate_lot(balance, sl_pips)

    order_type = "ORDER_TYPE_BUY" if direction == "BUY" else "ORDER_TYPE_SELL"
    # الهدف المستخدم: TP2 لنسبة مكسب/خسارة أفضل
    take_profit = tp2 if tp2 else tp1

    body = {
        "symbol":      SYMBOL,
        "type":        order_type,
        "volume":      lot,
        "stopLoss":    round(sl, 2),
        "takeProfit":  round(take_profit, 2),
        "comment":     f"AutoBot|{signal.get('confidence', 0)}%|{datetime.utcnow().strftime('%H:%M')}",
    }

    logger.info(f"📤 إرسال أمر {direction} | لوت: {lot} | SL: {sl} | TP: {take_profit}")
    result = _post(f"/users/current/accounts/{META_ACCOUNT_ID}/orders", body)

    if result:
        logger.info(f"✅ الصفقة نُفِّذت: {result}")
    else:
        logger.error("❌ فشل تنفيذ الصفقة")

    return result


# ═══════════════════════════════════════════════════════════════
#  STATUS REPORT
# ═══════════════════════════════════════════════════════════════
def build_status_report() -> str:
    """بناء تقرير كامل عن حالة التداول الآلي"""
    if not META_API_TOKEN or not META_ACCOUNT_ID:
        return (
            "⚙️ *نظام التداول الآلي*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "❌ *غير مُهيَّأ بعد*\n\n"
            "يحتاج إلى:\n"
            "• `META_API_TOKEN` — توكن MetaApi\n"
            "• `META_ACCOUNT_ID` — معرّف الحساب في MetaApi\n\n"
            "📖 راجع تعليمات الإعداد أدناه."
        )

    conn = check_connection()
    info = get_account_info()
    positions = get_open_positions()

    status_icon = "🟢" if conn.get("connected") else "🔴"
    broker_icon  = "🟢" if conn.get("broker") else "🔴"

    balance  = f"${info.get('balance', 0):,.2f}"  if info else "—"
    equity   = f"${info.get('equity', 0):,.2f}"   if info else "—"
    margin   = f"${info.get('margin', 0):,.2f}"   if info else "—"

    auto_icon = "🟢 مفعَّل" if auto_trading_enabled else "🔴 موقوف"

    lines = [
        "⚙️ *نظام التداول الآلي — MT5*",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🔌 MetaApi: {status_icon}  |  MT5 Broker: {broker_icon}",
        f"🤖 التداول الآلي: {auto_icon}",
        "",
        "💰 *معلومات الحساب:*",
        f"• الرصيد: `{balance}`",
        f"• الإيكويتي: `{equity}`",
        f"• الهامش المستخدم: `{margin}`",
        "",
        f"📊 *الصفقات المفتوحة: {len(positions)}/{MAX_OPEN_TRADES}*",
    ]

    for p in positions:
        side   = "🟢 شراء" if p.get("type") == "POSITION_TYPE_BUY" else "🔴 بيع"
        profit = p.get("unrealizedProfit", 0)
        p_icon = "📈" if profit >= 0 else "📉"
        lines.append(
            f"  {side} | لوت: {p.get('volume')} | {p_icon} ${profit:+.2f}"
        )

    if not positions:
        lines.append("  _(لا توجد صفقات مفتوحة)_")

    lines += [
        "",
        f"⚡ حجم اللوت: `{DEFAULT_LOT}`",
        f"🛡️ نسبة المخاطرة: `{RISK_PERCENT}%`",
        f"📌 الرمز: `{SYMBOL}`",
    ]

    return "\n".join(lines)


def build_positions_report() -> str:
    """تقرير مختصر بالصفقات المفتوحة"""
    positions = get_open_positions()
    if not positions:
        return "📭 *لا توجد صفقات مفتوحة حالياً*"

    lines = [f"📊 *الصفقات المفتوحة ({len(positions)})*", "━━━━━━━━━━━━━━━━━━━━━━━━"]
    total_profit = 0.0

    for i, p in enumerate(positions, 1):
        side    = "🟢 شراء" if p.get("type") == "POSITION_TYPE_BUY" else "🔴 بيع"
        profit  = p.get("unrealizedProfit", 0)
        p_icon  = "📈" if profit >= 0 else "📉"
        total_profit += profit
        lines.append(
            f"*#{i}* | {side}\n"
            f"   دخول: `{p.get('openPrice', '—')}` | لوت: `{p.get('volume', '—')}`\n"
            f"   SL: `{p.get('stopLoss', '—')}` | TP: `{p.get('takeProfit', '—')}`\n"
            f"   {p_icon} ربح/خسارة: `${profit:+.2f}`\n"
            f"   ID: `{p.get('id', '—')}`"
        )

    total_icon = "📈" if total_profit >= 0 else "📉"
    lines.append(f"\n{total_icon} *إجمالي: `${total_profit:+.2f}`*")
    return "\n".join(lines)
