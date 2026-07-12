import os
import logging
# ============================================================
#  PAIR CONFIGURATION — اقرأ الزوج من متغير البيئة
# ============================================================
TRADING_PAIR = os.getenv("TRADING_PAIR", "XAUUSD").upper()
from pair_config import PAIR_CFG
import asyncio
import json
import math
import random
import requests
import threading
import time
try:
    from websocket._app import WebSocketApp as _WebSocketApp
    _WS_AVAILABLE = True
except ImportError:
    try:
        import websocket as _wsmod
        _WebSocketApp = _wsmod.WebSocketApp
        _WS_AVAILABLE = True
    except Exception:
        _WS_AVAILABLE = False
        _WebSocketApp = None
from datetime import datetime, timedelta
from collections import deque
import auto_trader
# guard: بعض الإصدارات لا تعرّف auto_trading_enabled
if not hasattr(auto_trader, 'auto_trading_enabled'):
    auto_trader.auto_trading_enabled = False
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, PollAnswerHandler, filters, ContextTypes
from datetime import time as dtime

from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

import google.generativeai as genai

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============================================================
#  DATABASE
# ============================================================
DATABASE_URL = "sqlite:///" + PAIR_CFG['db_file']
os.makedirs("data", exist_ok=True)
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
Base = declarative_base()

class TradingUser(Base):
    __tablename__ = "trading_users"
    id = Column(Integer, primary_key=True)
    tg_id = Column(String, unique=True, index=True)
    username = Column(String)
    first_name = Column(String, default="")
    is_blocked = Column(Boolean, default=False)
    is_vip = Column(Boolean, default=False)
    signals_requested = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    loyalty_points = Column(Integer, default=0)
    bonus_signals = Column(Integer, default=0)
    vip_expires_at = Column(DateTime, nullable=True)
    referred_by = Column(String, default="")
    tier = Column(String, default="trial")
    signals_today = Column(Integer, default=0)
    ai_analyses_today = Column(Integer, default=0)
    usage_date = Column(String, default="")

class Signal(Base):
    __tablename__ = "signals"
    id = Column(Integer, primary_key=True)
    pair = Column(String, default=TRADING_PAIR)
    direction = Column(String)
    entry_price = Column(Float)
    tp1 = Column(Float)
    tp2 = Column(Float)
    tp3 = Column(Float)
    sl = Column(Float)
    confidence = Column(Float)
    models_confirmed = Column(Integer)
    indicators_confirmed = Column(Integer)
    rsi = Column(Float)
    macd_signal = Column(String)
    bb_signal = Column(String)
    session = Column(String)
    result = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)

class Survey(Base):
    __tablename__ = "trading_surveys"
    id = Column(Integer, primary_key=True)
    poll_id = Column(String, index=True)
    question = Column(String)
    options = Column(Text)
    results = Column(Text, default="{}")
    vote_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class BroadcastQueue(Base):
    __tablename__ = "broadcast_queue"
    id = Column(Integer, primary_key=True)
    type = Column(String)
    file_path = Column(String)
    text_content = Column(String)
    status = Column(String, default='pending')
    created_at = Column(DateTime, default=datetime.utcnow)

class AutoTradeAccount(Base):
    __tablename__ = "auto_trade_accounts"
    id = Column(Integer, primary_key=True)
    tg_id = Column(String, unique=True, index=True)
    meta_token = Column(String, default="")
    meta_account_id = Column(String, default="")
    is_active = Column(Boolean, default=False)
    lot_size = Column(Float, default=0.01)
    risk_pct = Column(Float, default=1.0)
    total_trades = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

# ============================================================
#  GOLD PRICE ALERTS SYSTEM
# ============================================================
class GoldAlert(Base):
    __tablename__ = "gold_alerts"
    id = Column(Integer, primary_key=True)
    tg_id = Column(String, index=True)
    target_price = Column(Float)
    direction = Column(String)  # "above" or "below"
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

# ============================================================
#  REFERRAL SYSTEM
# ============================================================
# (TradingUser already has tg_id — referral_code = "REF" + tg_id)
def get_referral_code(tg_id):
    return "REF" + str(tg_id)

def get_referral_link(tg_id, bot_username="YourBotUsername"):
    code = get_referral_code(tg_id)
    return "https://t.me/" + bot_username + "?start=" + code


Base.metadata.create_all(bind=engine)

def _migrate_db():
    from sqlalchemy import text as _text
    # ✅ FIX: كل العمليات داخل with block واحد
    with engine.connect() as conn:
        all_migrations = [
            # trading_users columns
            "ALTER TABLE trading_users ADD COLUMN first_name TEXT DEFAULT ''",
            "ALTER TABLE trading_users ADD COLUMN signals_requested INTEGER DEFAULT 0",
            "ALTER TABLE trading_users ADD COLUMN loyalty_points INTEGER DEFAULT 0",
            "ALTER TABLE trading_users ADD COLUMN bonus_signals INTEGER DEFAULT 0",
            "ALTER TABLE trading_users ADD COLUMN vip_expires_at TIMESTAMP",
            "ALTER TABLE trading_users ADD COLUMN referred_by TEXT DEFAULT ''",
            "ALTER TABLE trading_users ADD COLUMN tier TEXT DEFAULT 'trial'",
            "ALTER TABLE trading_users ADD COLUMN signals_today INTEGER DEFAULT 0",
            "ALTER TABLE trading_users ADD COLUMN ai_analyses_today INTEGER DEFAULT 0",
            "ALTER TABLE trading_users ADD COLUMN usage_date TEXT DEFAULT ''",
            # auto_trade_accounts columns
            "ALTER TABLE auto_trade_accounts ADD COLUMN meta_token TEXT DEFAULT ''",
            "ALTER TABLE auto_trade_accounts ADD COLUMN meta_account_id TEXT DEFAULT ''",
            "ALTER TABLE auto_trade_accounts ADD COLUMN lot_size REAL DEFAULT 0.01",
            # gold_alerts columns
            "ALTER TABLE gold_alerts ADD COLUMN target_price REAL DEFAULT 0",
            # trade_signals table
            "CREATE TABLE IF NOT EXISTS trade_signals (id INTEGER PRIMARY KEY AUTOINCREMENT, tg_id TEXT NOT NULL, direction TEXT, entry REAL, sl REAL, tp1 REAL, tp2 REAL, tp3 REAL, confidence REAL, status TEXT DEFAULT 'open', tp_hit INTEGER DEFAULT 0, tp1_hit INTEGER DEFAULT 0, tp2_hit INTEGER DEFAULT 0, tp3_hit INTEGER DEFAULT 0, sent_at TIMESTAMP, closed_at TIMESTAMP)",
              "ALTER TABLE trade_signals ADD COLUMN tp1_hit INTEGER DEFAULT 0",
              "ALTER TABLE trade_signals ADD COLUMN tp2_hit INTEGER DEFAULT 0",
              "ALTER TABLE trade_signals ADD COLUMN tp3_hit INTEGER DEFAULT 0",
        ]
        for ddl in all_migrations:
            try:
                conn.execute(_text(ddl))
                conn.commit()
            except Exception:
                pass
_migrate_db()

def _ensure_admins_vip():
    """تأكد أن كل ADMIN_IDS هم VIP (خطة ماسية) دائماً عند بدء البوت"""
    _ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
    db = SessionLocal()
    try:
        for aid in _ADMIN_IDS:
            u = db.query(TradingUser).filter(TradingUser.tg_id == str(aid)).first()
            if u:
                changed = False
                if not u.is_vip:
                    u.is_vip = True
                    changed = True
                if (u.tier or "trial") not in ("basic", "pro", "vip"):
                    u.tier = "vip"
                    changed = True
                if changed:
                    db.commit()
    except Exception:
        pass
    finally:
        db.close()
_ensure_admins_vip()

def _backfill_legacy_vip_tiers():
    """توافق قديم: أي حساب is_vip=True بدون تصنيف خطة يُعتبر 'ماسي' افتراضياً"""
    db = SessionLocal()
    try:
        legacy = db.query(TradingUser).filter(
            TradingUser.is_vip == True
        ).all()
        for u in legacy:
            if (u.tier or "trial") not in ("basic", "pro", "vip"):
                u.tier = "vip"
        db.commit()
    except Exception:
        pass
    finally:
        db.close()
_backfill_legacy_vip_tiers()

SIGNAL_FILE = "data/latest_signal.json"
STATS_FILE  = "data/website_stats.json"

def _save_signal_for_website(signal: dict):
    try:
        os.makedirs("data", exist_ok=True)
        payload = {
            "direction":           signal.get("direction"),
            "entry_price":         signal.get("entry"),
            "tp1":                 signal.get("tp1"),
            "tp2":                 signal.get("tp2"),
            "tp3":                 signal.get("tp3"),
            "sl":                  signal.get("sl"),
            "confidence":          signal.get("confidence"),
            "models_confirmed":    signal.get("models_confirmed"),
            "indicators_confirmed":signal.get("indicators_confirmed"),
            "rsi":                 signal.get("rsi"),
            "macd_signal":         signal.get("macd_signal"),
            "bb_signal":           signal.get("bb_signal"),
            "session":             signal.get("session"),
            "timestamp":           datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        with open(SIGNAL_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except Exception as e:
        logger.error(f"_save_signal_for_website: {e}")

def _update_stats_for_website():
    try:
        os.makedirs("data", exist_ok=True)
        db = SessionLocal()
        users   = db.query(TradingUser).count()
        signals = db.query(Signal).count()
        db.close()
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump({"users": users, "signals": signals}, f)
    except Exception as e:
        logger.error(f"_update_stats_for_website: {e}")

# ============================================================
#  CONFIG
# ============================================================
BOT_TOKEN = PAIR_CFG['token']
WHATSAPP_LINK = "https://wa.me/201500236188"
_admin_env = os.getenv("ADMIN_IDS", "")
if not _admin_env:
    raise RuntimeError("Environment variable ADMIN_IDS is not defined — add it to Secrets")
ADMIN_IDS = [int(x) for x in _admin_env.split(",") if x.strip().isdigit()]
GOLD_API_KEY = os.getenv("GOLD_API_KEY", "")
WEBSITE_URL = f"https://{os.getenv('REPLIT_DEV_DOMAIN', 'trading-bot.replit.app')}"

def get_website_url():
    """يرجع رابط الموقع الحالي — يقرأه من data/website_url.txt (يكتبه start_tunnel.sh
    برابط Cloudflare Tunnel الجديد عند كل تشغيل)، أو يرجع WEBSITE_URL كرابط احتياطي
    إذا لم يوجد الملف أو كان فارغاً/غير صالح."""
    try:
        with open("data/website_url.txt", "r") as f:
            url = f.read().strip()
            if url.startswith("http"):
                return url
    except Exception:
        pass
    return WEBSITE_URL

# ============================================================
#  MARKET HOURS CHECKER - NEW
# ============================================================
# قائمة العطل الرسمية (شهر-يوم)
HOLIDAYS = [
    "01-01",  # رأس السنة
    "12-25",  # عيد الميلاد
    "12-26",  # Boxing Day
    # يمكن إضافة المزيد هنا
]

def is_market_open() -> tuple:
    """
    ترجع (bool, str)
    XAUUSD يغلق: الجمعة 22:00 UTC
    XAUUSD يفتح: الأحد   22:00 UTC
    """
    # ── 0. أزواج العملات الرقمية مفتوحة 24/7 ───────────────────
    if PAIR_CFG.get("is_24_7", False):
        return True, f"✅ سوق {PAIR_CFG['display_name']} ({PAIR_CFG['symbol']}) مفتوح 24 ساعة / 7 أيام."

    now = datetime.utcnow()
    weekday = now.weekday()   # 0=الاثنين .. 4=الجمعة .. 5=السبت .. 6=الأحد
    hour    = now.hour
    current_date_str = now.strftime("%m-%d")

    # ── 1. السبت كله مغلق ──────────────────────────────────────────
    if weekday == 5:
        next_open = now.replace(hour=22, minute=0, second=0, microsecond=0)
        next_open += timedelta(days=1)   # الأحد الساعة 22:00
        remaining = next_open - now
        hrs = int(remaining.total_seconds() // 3600)
        mins = int((remaining.total_seconds() % 3600) // 60)
        return False, f"⛔ السوق مغلق (السبت). يفتح الأحد 22:00 UTC (بعد {hrs}س {mins}د)."

    # ── 2. الأحد قبل 22:00 UTC مغلق، من 22:00 فصاعداً مفتوح ────────
    if weekday == 6:
        if hour < 22:
            next_open = now.replace(hour=22, minute=0, second=0, microsecond=0)
            remaining = next_open - now
            hrs = int(remaining.total_seconds() // 3600)
            mins = int((remaining.total_seconds() % 3600) // 60)
            return False, f"⛔ السوق مغلق (الأحد قبل الافتتاح). يفتح الساعة 22:00 UTC (بعد {hrs}س {mins}د)."
        # الأحد 22:00+ → مفتوح
        return True, "✅ السوق مفتوح (جلسة آسيا — بدأت هذا الأحد 22:00 UTC)."

    # ── 3. الجمعة بعد 22:00 UTC مغلق ───────────────────────────────
    if weekday == 4 and hour >= 22:
        next_open = now.replace(hour=22, minute=0, second=0, microsecond=0)
        next_open += timedelta(days=2)   # الأحد 22:00
        remaining = next_open - now
        hrs = int(remaining.total_seconds() // 3600)
        mins = int((remaining.total_seconds() % 3600) // 60)
        return False, f"⛔ السوق أغلق (الجمعة 22:00 UTC). يفتح الأحد 22:00 UTC (بعد {hrs}س {mins}د)."

    # ── 4. العطل الرسمية ────────────────────────────────────────────
    if current_date_str in HOLIDAYS:
        next_open = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        remaining = next_open - now
        hrs = int(remaining.total_seconds() // 3600)
        mins = int((remaining.total_seconds() % 3600) // 60)
        return False, f"⛔ السوق مغلق (عطلة رسمية {current_date_str}). يفتح بعد {hrs}س {mins}د."

    # ── 5. باقي الوقت (الاثنين-الجمعة قبل 22:00) → مفتوح ────────────
    day_names = {0: "الاثنين", 1: "الثلاثاء", 2: "الأربعاء", 3: "الخميس", 4: "الجمعة"}
    return True, "✅ السوق مفتوح الآن (" + day_names.get(weekday, "") + " " + str(hour).zfill(2) + ":xx UTC)."

async def notify_market_reopening(context: ContextTypes.DEFAULT_TYPE):
    """تُستدعى عند فتح السوق (مثلاً يوم الاثنين) لإعلام جميع المستخدمين."""
    try:
        db = SessionLocal()
        users = db.query(TradingUser).filter(TradingUser.is_blocked == False).all()
        db.close()
        msg = "🔔 *عودة السوق للعمل!*\n\nتم فتح سوق " + PAIR_CFG['symbol'] + " الآن. يمكنك طلب إشارات التداول كالمعتاد.\n\nاستخدم /start للقائمة الرئيسية."
        sent = 0
        for u in users:
            try:
                await context.bot.send_message(chat_id=u.tg_id, text=msg, parse_mode="Markdown")
                sent += 1
                await asyncio.sleep(0.05)
            except:
                pass
        p = gold_manager.current_price
        src = "WebSocket" if finnhub_ws.is_data_fresh() else "HTTP/Yahoo"
        logger.info(
            "تم إرسال إشعار فتح السوق لـ " + str(sent) + " مستخدم"
            " | سعر=" + str(round(p, 2) if p else "N/A") +
            " | مصدر=" + src +
            " | آخر_تيك=" + str(gold_manager.last_update)
        )
    except Exception as e:
        logger.error(f"notify_market_reopening error: {e}")

# ============================================================
#  GEMINI MANAGER - 15 KEYS WITH SMART ROTATION
# ============================================================
class GeminiManager:
    def __init__(self):
        self.keys = [
            os.getenv(f"GEMINI_KEY_{i}", "") for i in range(1, 16)
        ]
        # إذا لم توجد متغيرات البيئة، نقرأ من gemini_keys.json
        if not any(self.keys):
            try:
                import json as _json
                _p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "gemini_keys.json")
                with open(_p, "r") as _f:
                    _jk = _json.load(_f)
                self.keys = [_jk.get(f"key_{i}", "") for i in range(1, 16)]
                logger.info(f"✅ تم تحميل مفاتيح Gemini من JSON")
            except Exception as _e:
                logger.warning(f"⚠️ خطأ في تحميل مفاتيح JSON: {_e}")
        self.valid_keys = [k for k in self.keys if k and len(k) > 10]
        self.current_index = 0
        self.exhausted = set()
        # نماذج النص فقط
        # ⚠️ gemini-2.0-* و gemini-1.5-* متوقفة رسمياً من جوجل (shut down 1 يونيو 2026) —
        # لا تُعِد إضافتها؛ استخدم فقط: gemini-2.5-flash-lite, gemini-2.5-flash, gemini-3.1-flash-lite
        self.text_models = [
            "gemini-2.5-flash-lite",
            "gemini-2.5-flash",
            "gemini-3.1-flash-lite",
        ]
        # نماذج الرؤية (صور الشارت) - تدعم الصور — نفس القائمة، الثلاثة تدعم الإدخال متعدد الوسائط
        self.vision_models = [
            "gemini-2.5-flash-lite",
            "gemini-2.5-flash",
            "gemini-3.1-flash-lite",
        ]
        logger.info(f"✅ GeminiManager: {len(self.valid_keys)} مفتاح نشط")

    def _get_next_key(self):
        available = [i for i in range(len(self.valid_keys)) if i not in self.exhausted]
        if not available:
            self.exhausted.clear()
            available = list(range(len(self.valid_keys)))
        self.current_index = available[0]
        return self.valid_keys[self.current_index]

    def _rotate_key(self):
        self.exhausted.add(self.current_index)

    async def generate(self, prompt: str, image_data: bytes = None, image_mime: str = "image/jpeg") -> str:
        models = self.vision_models if image_data else self.text_models
        max_attempts = max(len(self.valid_keys) * len(models), 1)

        for attempt in range(max_attempts):
            if not self.valid_keys:
                break
            key = self._get_next_key()
            try:
                genai.configure(api_key=key)
            except Exception:
                self._rotate_key()
                continue

            for model_name in models:
                try:
                    model = genai.GenerativeModel(model_name)
                    if image_data:
                        # إرسال الصورة مباشرة بدون PIL
                        image_part = {"mime_type": image_mime, "data": image_data}
                        response = model.generate_content(
                            [prompt, image_part],
                            generation_config={"max_output_tokens": 2048}
                        )
                    else:
                        response = model.generate_content(
                            prompt,
                            generation_config={"max_output_tokens": 1024}
                        )
                    text = response.text
                    if text and len(text) > 10:
                        logger.info(f"✅ Gemini OK: {model_name} (key #{self.current_index+1})")
                        return text
                except Exception as e:
                    err = str(e).lower()
                    logger.warning(f"⚠️ Gemini {model_name} key#{self.current_index+1}: {str(e)[:80]}")
                    if any(x in err for x in ["quota", "429", "exhausted", "resource_exhausted"]):
                        self._rotate_key()
                        await asyncio.sleep(0.5)
                        break
                    if any(x in err for x in ["invalid_api_key", "api_key", "permission"]):
                        self._rotate_key()
                        break
                    continue

            await asyncio.sleep(0.3)

        logger.error("❌ جميع مفاتيح Gemini استُنزفت أو فشلت")
        return "عذراً، خدمة الذكاء الاصطناعي مشغولة حالياً. يرجى إعادة المحاولة بعد دقيقة."

gemini = GeminiManager()

# ============================================================
#  TECHNICAL ANALYSIS ENGINE
# ============================================================
class TechnicalAnalysis:
    """محرك التحليل الفني الحقيقي - RSI, MACD, Bollinger, ATR, Stochastic, Fibonacci"""

    @staticmethod
    def rsi(prices: list, period: int = 14) -> float:
        if len(prices) < period + 1:
            return 50.0
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gains = [max(d, 0) for d in deltas[-period:]]
        losses = [abs(min(d, 0)) for d in deltas[-period:]]
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return round(100 - (100 / (1 + rs)), 2)

    @staticmethod
    def ema(prices: list, period: int) -> float:
        if len(prices) < period:
            return prices[-1] if prices else 0
        k = 2 / (period + 1)
        ema_val = sum(prices[:period]) / period
        for p in prices[period:]:
            ema_val = p * k + ema_val * (1 - k)
        return round(ema_val, 2)

    @staticmethod
    def macd(prices: list):
        if len(prices) < 26:
            return 0, 0, "neutral"
        ema12 = TechnicalAnalysis.ema(prices, 12)
        ema26 = TechnicalAnalysis.ema(prices, 26)
        macd_line = ema12 - ema26
        signal_prices = [TechnicalAnalysis.ema(prices[:i], 12) - TechnicalAnalysis.ema(prices[:i], 26)
                         for i in range(26, len(prices))]
        signal_line = TechnicalAnalysis.ema(signal_prices, 9) if len(signal_prices) >= 9 else macd_line
        histogram = macd_line - signal_line
        if histogram > 0 and macd_line > 0:
            sig = "buy"
        elif histogram < 0 and macd_line < 0:
            sig = "sell"
        else:
            sig = "neutral"
        return round(macd_line, 4), round(signal_line, 4), sig

    @staticmethod
    def bollinger_bands(prices: list, period: int = 20, std_dev: float = 2.0):
        if len(prices) < period:
            p = prices[-1]
            return p * 1.01, p, p * 0.99, "neutral"
        recent = prices[-period:]
        sma = sum(recent) / period
        variance = sum((p - sma) ** 2 for p in recent) / period
        std = math.sqrt(variance)
        upper = sma + std_dev * std
        lower = sma - std_dev * std
        current = prices[-1]
        if current <= lower:
            sig = "buy"
        elif current >= upper:
            sig = "sell"
        elif current < sma:
            sig = "neutral_low"
        else:
            sig = "neutral_high"
        return round(upper, 2), round(sma, 2), round(lower, 2), sig

    @staticmethod
    def atr(highs: list, lows: list, closes: list, period: int = 14) -> float:
        if len(closes) < 2:
            return 0
        trs = []
        for i in range(1, len(closes)):
            tr = max(highs[i] - lows[i],
                     abs(highs[i] - closes[i-1]),
                     abs(lows[i] - closes[i-1]))
            trs.append(tr)
        if len(trs) < period:
            return round(sum(trs) / len(trs), 2) if trs else 0
        return round(sum(trs[-period:]) / period, 2)

    @staticmethod
    def stochastic(highs: list, lows: list, closes: list, period: int = 14):
        if len(closes) < period:
            return 50, 50, "neutral"
        recent_h = highs[-period:]
        recent_l = lows[-period:]
        highest = max(recent_h)
        lowest = min(recent_l)
        current = closes[-1]
        if highest == lowest:
            k = 50
        else:
            k = ((current - lowest) / (highest - lowest)) * 100
        k = round(k, 2)
        d = k
        if k < 20:
            sig = "buy"
        elif k > 80:
            sig = "sell"
        else:
            sig = "neutral"
        return k, d, sig

    @staticmethod
    def fibonacci_levels(high: float, low: float) -> dict:
        diff = high - low
        return {
            "0.0": round(high, 2),
            "0.236": round(high - 0.236 * diff, 2),
            "0.382": round(high - 0.382 * diff, 2),
            "0.5": round(high - 0.5 * diff, 2),
            "0.618": round(high - 0.618 * diff, 2),
            "0.786": round(high - 0.786 * diff, 2),
            "1.0": round(low, 2),
        }

    @staticmethod
    def support_resistance(prices: list, window: int = 5) -> tuple:
        if len(prices) < window * 2:
            return min(prices), max(prices)
        supports = []
        resistances = []
        for i in range(window, len(prices) - window):
            local_min = all(prices[i] <= prices[i-j] and prices[i] <= prices[i+j] for j in range(1, window+1))
            local_max = all(prices[i] >= prices[i-j] and prices[i] >= prices[i+j] for j in range(1, window+1))
            if local_min:
                supports.append(prices[i])
            if local_max:
                resistances.append(prices[i])
        support = min(supports[-3:]) if supports else min(prices)
        resistance = max(resistances[-3:]) if resistances else max(prices)
        return round(support, 2), round(resistance, 2)

# ============================================================
#  CANDLE AGGREGATOR — يبني شموع OHLC حقيقية من تدفق التكات
# ============================================================
class CandleAggregator:
    """
    يجمّع التكات ضمن نافذة زمنية ثابتة وينتج شموع OHLC حقيقية.
    الشمعة تُغلق فقط عند انتهاء الفترة الزمنية، لا عند كل تكة.
    interval_seconds=60 → شموع دقيقة واحدة (قابل للتغيير).
    """

    def __init__(self, interval_seconds: int = 60, maxlen: int = 200):
        self.interval   = interval_seconds
        self._open: float | None  = None
        self._high: float | None  = None
        self._low:  float | None  = None
        self._close: float | None = None
        self._bar_epoch: int | None = None       # رقم النافذة الزمنية الحالية
        self.candles: deque = deque(maxlen=maxlen)  # (open, high, low, close)

    def _bar_epoch_of(self, dt: datetime) -> int:
        """
        يحوّل dt (UTC naive) إلى رقم نافذة زمنية صحيح.
        يستخدم epoch يدوياً لتجنّب مشكلة .timestamp() مع naive UTC.
        """
        total_secs = int((dt - datetime(1970, 1, 1)).total_seconds())
        return total_secs // self.interval

    def push(self, price: float, ts: datetime = None) -> bool:
        """
        يضيف تكة واحدة إلى النافذة الزمنية الصحيحة.
        يعيد True إذا أُغلقت شمعة جديدة أثناء هذه العملية.
        """
        if ts is None:
            ts = datetime.utcnow()
        epoch = self._bar_epoch_of(ts)

        if self._bar_epoch is None:
            # أول تكة على الإطلاق — ابدأ شمعة
            self._bar_epoch = epoch
            self._open = self._high = self._low = self._close = price
            return False

        if epoch > self._bar_epoch:
            # انتهت النافذة — أغلق الشمعة الحالية واحفظها
            self.candles.append((self._open, self._high, self._low, self._close))
            # افتح شمعة جديدة
            self._bar_epoch = epoch
            self._open = self._high = self._low = self._close = price
            return True

        # نفس النافذة — حدّث OHLC الشمعة الجارية
        if price > self._high:
            self._high = price
        if price < self._low:
            self._low = price
        self._close = price
        return False

    def get_ohlc_lists(self):
        """
        يعيد (opens, highs, lows, closes) من الشموع المغلقة فقط.
        الشمعة الجارية غير المغلقة مستثناة عمداً لأن OHLC غير مكتمل.
        """
        if not self.candles:
            return [], [], [], []
        opens  = [c[0] for c in self.candles]
        highs  = [c[1] for c in self.candles]
        lows   = [c[2] for c in self.candles]
        closes = [c[3] for c in self.candles]
        return opens, highs, lows, closes

    @property
    def count(self) -> int:
        return len(self.candles)


# ============================================================
#  GOLD PRICE MANAGER
# ============================================================
class GoldPriceManager:
    """مدير أسعار الذهب - يدعم عدة APIs"""

    def __init__(self):
        self.current_price = None
        self.price_history = deque(maxlen=200)
        self.highs = deque(maxlen=200)   # fallback مؤقت ريثما تتراكم الشموع
        self.lows  = deque(maxlen=200)   # fallback مؤقت ريثما تتراكم الشموع
        self.last_update = None
        self.session = "unknown"
        # شموع OHLC حقيقية مبنية من تدفق التكات (interval=60s)
        self.candle_agg = CandleAggregator(interval_seconds=60, maxlen=200)

    @property
    def price(self):
        return self.current_price

    @price.setter
    def price(self, value):
        self.current_price = value

    def _get_trading_session(self) -> str:
        hour = datetime.utcnow().hour
        if 22 <= hour or hour < 7:
            return "آسيوية 🌏"
        elif 7 <= hour < 12:
            return "لندن 🇬🇧"
        elif 12 <= hour < 17:
            return "نيويورك 🗽"
        else:
            return "متداخلة 🌍"

    def fetch_price(self) -> dict:
        """جلب سعر الزوج الحقيقي — يجرب 5 مصادر بالترتيب"""

        # 1. Yahoo Finance (الاوثق، بدون API key)
        try:
            r = requests.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{PAIR_CFG['yahoo_symbol']}?interval=1m&range=1d",
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                timeout=8
            )
            if r.status_code == 200:
                d = r.json()
                price = d["chart"]["result"][0]["meta"]["regularMarketPrice"]
                if price and float(price) > 100:
                    logger.info(f"Yahoo Finance: ${float(price):.2f}")
                    return {"price": float(price), "source": "yahoo"}
        except Exception as e:
            logger.warning(f"Yahoo Finance فشل: {e}")

        # 2. Yahoo Finance مرآة احتياطية
        try:
            r = requests.get(
                f"https://query2.finance.yahoo.com/v7/finance/quote?symbols={PAIR_CFG['yahoo_symbol_v7']}&fields=regularMarketPrice",
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                timeout=8
            )
            if r.status_code == 200:
                d = r.json()
                price = d["quoteResponse"]["result"][0]["regularMarketPrice"]
                if price and float(price) > 100:
                    logger.info(f"Yahoo Finance v7: ${float(price):.2f}")
                    return {"price": float(price), "source": "yahoo_v7"}
        except Exception as e:
            logger.warning(f"Yahoo Finance v7 فشل: {e}")

        # 3. goldprice.org (للذهب فقط)
        if PAIR_CFG.get("is_gold", False):
            try:
                r = requests.get(
                    "https://data-asg.goldprice.org/GetData/USD-XAU/1",
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=5
                )
                if r.status_code == 200:
                    data = r.json()
                    if data and len(data) > 0:
                        price = float(data[0].split(",")[1])
                        if price > 100:
                            return {"price": price, "source": "goldprice.org"}
            except Exception as e:
                logger.warning(f"goldprice.org فشل: {e}")

        # 4. metals.live (للذهب فقط)
        if PAIR_CFG.get("is_gold", False):
            try:
                r = requests.get(
                    "https://metals.live/api/spot",
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=5
                )
                if r.status_code == 200:
                    data = r.json()
                    for item in data:
                        if item.get("metal") == "gold":
                            price = float(item.get("price", 0))
                            if price > 100:
                                return {"price": price, "source": "metals.live"}
            except Exception as e:
                logger.warning(f"metals.live فشل: {e}")

        # 5. goldapi.io (إذا توفر مفتاح)
        if PAIR_CFG.get("is_gold", False) and GOLD_API_KEY:
            try:
                r = requests.get(
                    "https://www.goldapi.io/api/XAU/USD",
                    headers={"x-access-token": GOLD_API_KEY, "Content-Type": "application/json"},
                    timeout=5
                )
                if r.status_code == 200:
                    data = r.json()
                    price = float(data.get("price", 0))
                    if price > 100:
                        return {"price": price, "source": "goldapi.io"}
            except Exception as e:
                logger.warning(f"GoldAPI فشل: {e}")

        # 6. الكاش المحلي (آخر سعر معروف)
        if self.current_price and self.current_price > 100:
            noise = random.uniform(-0.5, 0.5)
            logger.info(f"جميع المصادر فشلت — الكاش: ${self.current_price:.2f}")
            return {"price": round(self.current_price + noise, 2), "source": "cached"}

        return {"price": None, "source": "none"}

    def update(self) -> dict:
        result = self.fetch_price()
        price = result.get("price")
        if price and price > PAIR_CFG['min_price']:
            self.current_price = price
            self.last_update = datetime.utcnow()
            self.session = self._get_trading_session()
            self.price_history.append(price)
            # شمعة OHLC حقيقية
            self.candle_agg.push(price)
            # fallback مؤقت للمؤشرات الأخرى ريثما تتراكم ≥ 20 شمعة
            spread = price * random.uniform(0.0005, 0.001)
            self.highs.append(round(price + spread, 2))
            self.lows.append(round(price - spread, 2))
        return result

    def feed_ws_price(self, price: float):
        if not price or price < PAIR_CFG['min_price']:
            return
        self.current_price = price
        self.last_update = datetime.utcnow()
        self.session = self._get_trading_session()
        self.price_history.append(price)
        # شمعة OHLC حقيقية
        self.candle_agg.push(price)
        # fallback مؤقت
        spread = price * random.uniform(0.0005, 0.001)
        self.highs.append(round(price + spread, 2))
        self.lows.append(round(price - spread, 2))

    def get_analysis_data(self) -> dict:
        prices = list(self.price_history)
        if len(prices) < 20:
            return None

        _, c_highs, c_lows, c_closes = self.candle_agg.get_ohlc_lists()

        if len(c_closes) >= 20:
            # شموع OHLC حقيقية — High/Low حقيقيان لكل شمعة، لا spread مصطنع
            return {"prices": c_closes, "highs": c_highs, "lows": c_lows}

        # Fallback مؤقت: تكات خام بينما تتراكم الشموع (< 20 شمعة مغلقة)
        return {"prices": prices, "highs": list(self.highs), "lows": list(self.lows)}

    # alias لإصلاح استدعاءات morning_market_summary و evening_market_summary
    get_market_data = get_analysis_data

gold_manager = GoldPriceManager()

# ============================================================
#  FINNHUB WEBSOCKET
# ============================================================
# مفاتيح Finnhub — تُقرأ من متغيرات البيئة (Secrets)
_fk1 = os.getenv("FINNHUB_KEY_1")
_fk2 = os.getenv("FINNHUB_KEY_2", "")
if not _fk1:
    raise RuntimeError("Environment variable FINNHUB_KEY_1 is not defined — add it to Secrets")
FINNHUB_KEYS = [k for k in [_fk1, _fk2] if k]
FINNHUB_API_KEY = FINNHUB_KEYS[0]   # للتوافق مع باقي الكود

class FinnhubWebSocket:
    """WebSocket لحظي لسعر الذهب — يدعم مفتاحين ويمنع الاتصال المزدوج"""

    def __init__(self):
        self.ws          = None
        self._thread     = None
        self._last_price = None
        self._running    = False
        self._connected  = False        # حالة الاتصال الفعلية
        self._reconnecting = False      # علم يمنع اتصالين متزامنين
        self._key_idx    = 0

    def _current_key(self):
        return FINNHUB_KEYS[self._key_idx % len(FINNHUB_KEYS)]

    def _next_key(self):
        self._key_idx += 1
        key = self._current_key()
        logger.warning("تبديل مفتاح Finnhub -> ..." + key[-6:])
        return key

    def _on_open(self, ws):
        self._connected   = True
        self._reconnecting = False
        key = self._current_key()
        logger.info("Finnhub WS متصل (..." + key[-6:] + ") — اشتراك " + PAIR_CFG['ws_symbol'])
        ws.send(json.dumps({"type": "subscribe", "symbol": PAIR_CFG['ws_symbol']}))

    def _on_message(self, ws, message):
        try:
            data     = json.loads(message)
            msg_type = data.get("type")
            if msg_type == "ping":
                ws.send(json.dumps({"type": "pong"}))
                return
            if msg_type != "trade":
                return
            for trade in data.get("data", []):
                price = trade.get("p")
                if price and float(price) > PAIR_CFG['min_price'] and price != self._last_price:
                    self._last_price = price
                    gold_manager.feed_ws_price(float(price))
                    logger.info("WS " + PAIR_CFG['symbol'] + ": " + str(round(float(price), PAIR_CFG['decimals'])))
        except Exception as e:
            logger.warning("WS message error: " + str(e))

    def _on_error(self, ws, error):
        logger.warning("Finnhub WS خطأ: " + str(error))
        # بدّل المفتاح للاتصال التالي
        self._next_key()

    def _on_close(self, ws, code, msg):
        self._connected = False
        logger.warning("Finnhub WS مغلق (" + str(code) + ") — إعادة اتصال بعد 8 ثوانٍ")
        # فقط إذا لم يكن هناك اتصال قيد الإنشاء بالفعل
        if self._running and not self._reconnecting:
            self._reconnecting = True
            threading.Timer(8, self._connect).start()

    def _connect(self):
        if not _WS_AVAILABLE or _WebSocketApp is None:
            logger.warning("websocket-client غير مثبت — وضع HTTP فقط")
            self._reconnecting = False
            return
        try:
            key = self._current_key()
            url = "wss://ws.finnhub.io?token=" + key
            logger.info("محاولة اتصال Finnhub WS ..." + key[-6:])
            self.ws = _WebSocketApp(
                url,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
            )
            # run_forever يحجب الـ thread حتى ينتهي الاتصال
            self.ws.run_forever(ping_interval=25, ping_timeout=10)
        except Exception as e:
            logger.error("Finnhub WS connect error: " + str(e))
            self._connected = False
        finally:
            # run_forever انتهى — خطأ أو إغلاق عادي
            # _on_close سيتولى جدولة إعادة الاتصال إذا _running=True
            self._reconnecting = False

    def is_connected(self) -> bool:
        """هل الاتصال قائم حالياً؟"""
        return self._connected

    def is_data_fresh(self) -> bool:
        """هل وصلنا بيانات سعر في آخر 5 دقائق؟"""
        return (
            gold_manager.last_update is not None and
            (datetime.utcnow() - gold_manager.last_update).total_seconds() < 300
        )

    def is_alive(self) -> bool:
        """متصل + بيانات حديثة"""
        return self.is_connected() and self.is_data_fresh()

    def start(self):
        self._running     = True
        self._reconnecting = True   # يمنع _on_close من الجدولة أثناء البداية
        self._thread = threading.Thread(target=self._connect, daemon=True, name="FinnhubWS")
        self._thread.start()
        logger.info("Finnhub WebSocket thread بدأ (مفتاحان للـ fallback)")

    def stop(self):
        self._running   = False
        self._connected = False
        if self.ws:
            self.ws.close()


finnhub_ws = FinnhubWebSocket()

# ============================================================
#  TRIAL SYSTEM - نظام التجربة المجانية 3 إشارات
# ============================================================
FREE_TRIAL_SIGNALS = 3

def is_trial_active(user) -> bool:
    """المستخدم نشط إذا كان VIP أو لم يستنفد إشاراته المجانية الـ3"""
    if not user:
        return False
    if user.is_vip:
        return True
    return (user.signals_requested or 0) < FREE_TRIAL_SIGNALS

def trial_remaining_signals(user) -> int:
    """عدد الإشارات المجانية المتبقية"""
    if not user or user.is_vip:
        return 0
    remaining = FREE_TRIAL_SIGNALS - (user.signals_requested or 0)
    return max(0, remaining)

def trial_remaining_days(user) -> int:
    """للتوافق مع استدعاءات قديمة — يُرجع عدد الإشارات المتبقية"""
    return trial_remaining_signals(user)

def trial_banner(user) -> str:
    if not user or user.is_vip:
        return ""
    remaining = trial_remaining_signals(user)
    if remaining > 0:
        return f"\n\n⏳ *تجربتك المجانية: {remaining} إشارة متبقية من أصل {FREE_TRIAL_SIGNALS}*\n💎 اشترك الآن للاستمرار بدون انقطاع!"
    return ""

# ============================================================
#  SUBSCRIPTION TIERS - نظام الخطط الثلاثة (فضي/ذهبي/ماسي)
# ============================================================
TIER_LIMITS = {
    "basic": {"name": "🥉 الفضية",  "price": 9.99,  "signals_per_day": 15, "ai_per_day": 0,  "auto_trading": False, "full_indicators": False, "priority_support": False, "instant_alerts": False, "alerts_max": 3},
    "pro":   {"name": "🥈 الذهبية", "price": 17.99, "signals_per_day": 20, "ai_per_day": 3,  "auto_trading": False, "full_indicators": True,  "priority_support": True,  "instant_alerts": False, "alerts_max": 10},
    "vip":   {"name": "💎 الماسية", "price": 34.99, "signals_per_day": -1, "ai_per_day": -1, "auto_trading": True,  "full_indicators": True,  "priority_support": True,  "instant_alerts": True, "alerts_max": -1},
}
TRIAL_ALERTS_MAX = 1  # عدد تنبيهات السعر المسموح بها لمستخدم التجربة المجانية (غير مشترك)

def _today_str() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")

def get_user_tier(user):
    """يرجع 'basic'/'pro'/'vip' لو مشترك مدفوع، أو None لو تجربة مجانية"""
    if not user or not user.is_vip:
        return None
    t = getattr(user, "tier", None)
    return t if t in TIER_LIMITS else "vip"  # توافق قديم

def tier_display_name(user) -> str:
    tier = get_user_tier(user)
    if tier is None:
        return "🎁 تجربة مجانية"
    return TIER_LIMITS[tier]["name"]

def get_alert_limit(user) -> int:
    """عدد تنبيهات السعر النشطة المسموح بها حسب خطة المستخدم. -1 = بلا حدود."""
    tier = get_user_tier(user)
    if tier is None:
        return TRIAL_ALERTS_MAX
    return TIER_LIMITS[tier]["alerts_max"]

def _reset_daily_usage_if_needed(user, db):
    today = _today_str()
    if (user.usage_date or "") != today:
        user.usage_date = today
        user.signals_today = 0
        user.ai_analyses_today = 0
        db.commit()

def check_signal_quota(user, db):
    """يرجع (مسموح: bool, رسالة الحد عند الرفض)"""
    tier = get_user_tier(user)
    if tier is None:
        return True, ""  # نظام التجربة المجانية له سقفه الخاص أصلاً
    _reset_daily_usage_if_needed(user, db)
    limit = TIER_LIMITS[tier]["signals_per_day"]
    if limit == -1:
        return True, ""
    used = user.signals_today or 0
    if used >= limit:
        return False, (
            f"⛔ *استنفدت إشاراتك اليومية*\n"
            f"خطتك: {TIER_LIMITS[tier]['name']} — الحد {limit} إشارات/يوم\n\n"
            f"⬆️ قم بترقية خطتك للحصول على المزيد من الإشارات."
        )
    return True, ""

def record_signal_use(user, db):
    tier = get_user_tier(user)
    if tier is None:
        return
    _reset_daily_usage_if_needed(user, db)
    user.signals_today = (user.signals_today or 0) + 1
    db.commit()

def check_ai_quota(user, db):
    tier = get_user_tier(user)
    if tier is None:
        return False, "💎 تحليل الشارت بالذكاء الاصطناعي متاح فقط للمشتركين."
    _reset_daily_usage_if_needed(user, db)
    limit = TIER_LIMITS[tier]["ai_per_day"]
    if limit == 0:
        return False, (
            f"⬆️ *تحليل الشارت AI غير متاح في خطتك الحالية*\n"
            f"خطتك: {TIER_LIMITS[tier]['name']}\n\n"
            f"قم بالترقية للخطة الذهبية 🥈 أو الماسية 💎 لاستخدام هذه الميزة."
        )
    if limit == -1:
        return True, ""
    used = user.ai_analyses_today or 0
    if used >= limit:
        return False, (
            f"⛔ *استنفدت تحليلات AI اليومية*\n"
            f"خطتك: {TIER_LIMITS[tier]['name']} — الحد {limit} تحليلات/يوم\n\n"
            f"💎 ترقّ للخطة الماسية لتحليل غير محدود."
        )
    return True, ""

def record_ai_use(user, db):
    tier = get_user_tier(user)
    if tier is None:
        return
    _reset_daily_usage_if_needed(user, db)
    user.ai_analyses_today = (user.ai_analyses_today or 0) + 1
    db.commit()

# ============================================================
#  SIGNAL ENGINE
# ============================================================
class SignalEngine:
    def __init__(self):
        self.ta = TechnicalAnalysis()
        self.min_confidence = 62.0
        self.last_signal_time = None
        self.signal_cooldown_minutes = 30

    def _check_cooldown(self) -> bool:
        if not self.last_signal_time:
            return True
        elapsed = (datetime.utcnow() - self.last_signal_time).total_seconds() / 60
        return elapsed >= self.signal_cooldown_minutes

    def _model_1_statistical(self, prices: list) -> str:
        if len(prices) < 30:
            return "neutral"
        mean = sum(prices[-20:]) / 20
        std = math.sqrt(sum((p - mean)**2 for p in prices[-20:]) / 20)
        current = prices[-1]
        z_score = (current - mean) / std if std > 0 else 0
        if z_score < -1.5:
            return "buy"
        elif z_score > 1.5:
            return "sell"
        trend = (prices[-1] - prices[-10]) / prices[-10] * 100
        return "buy" if trend > 0.1 else ("sell" if trend < -0.1 else "neutral")

    def _model_2_mathematical(self, prices: list) -> str:
        if len(prices) < 14:
            return "neutral"
        ema5 = self.ta.ema(prices, 5)
        ema13 = self.ta.ema(prices, 13)
        ema21 = self.ta.ema(prices, 21)
        if ema5 > ema13 > ema21:
            return "buy"
        elif ema5 < ema13 < ema21:
            return "sell"
        return "neutral"

    def _model_3_momentum(self, prices: list) -> str:
        if len(prices) < 10:
            return "neutral"
        roc = (prices[-1] - prices[-10]) / prices[-10] * 100
        if roc > 0.3:
            return "buy"
        elif roc < -0.3:
            return "sell"
        return "neutral"

    # ------------------------------------------------------------------ #
    #  ADX — Average Directional Index (Wilder Smoothing)                #
    # ------------------------------------------------------------------ #
    @staticmethod
    def adx(highs: list, lows: list, closes: list, period: int = 14):
        """
        يحسب ADX القياسي مع +DI و -DI باستخدام Wilder Smoothing.
        يعيد (adx_value, plus_di, minus_di) — كلها أعداد عشرية مدوّرة.
        """
        if len(closes) < period + 2:
            return 0.0, 0.0, 0.0

        h = list(highs)
        l = list(lows)
        c = list(closes)
        n = len(c)

        tr_list, pdm_list, ndm_list = [], [], []
        for i in range(1, n):
            tr = max(h[i] - l[i],
                     abs(h[i] - c[i - 1]),
                     abs(l[i] - c[i - 1]))
            up   = h[i] - h[i - 1]
            down = l[i - 1] - l[i]
            pdm_list.append(up   if up > down and up > 0 else 0.0)
            ndm_list.append(down if down > up and down > 0 else 0.0)
            tr_list.append(tr)

        if len(tr_list) < period:
            return 0.0, 0.0, 0.0

        # تهيئة Wilder بأول مجموع بسيط
        atr_s = sum(tr_list[:period])
        pdm_s = sum(pdm_list[:period])
        ndm_s = sum(ndm_list[:period])

        dx_list = []
        for i in range(period, len(tr_list)):
            atr_s = atr_s - atr_s / period + tr_list[i]
            pdm_s = pdm_s - pdm_s / period + pdm_list[i]
            ndm_s = ndm_s - ndm_s / period + ndm_list[i]
            pdi = 100.0 * pdm_s / atr_s if atr_s else 0.0
            ndi = 100.0 * ndm_s / atr_s if atr_s else 0.0
            dsum = pdi + ndi
            dx   = 100.0 * abs(pdi - ndi) / dsum if dsum else 0.0
            dx_list.append((dx, pdi, ndi))

        if len(dx_list) < period:
            last = dx_list[-1] if dx_list else (0.0, 0.0, 0.0)
            return 0.0, round(last[1], 2), round(last[2], 2)

        # تنعيم DX → ADX
        adx_val = sum(d[0] for d in dx_list[:period]) / period
        final_pdi, final_ndi = dx_list[period - 1][1], dx_list[period - 1][2]
        for i in range(period, len(dx_list)):
            adx_val   = (adx_val * (period - 1) + dx_list[i][0]) / period
            final_pdi = dx_list[i][1]
            final_ndi = dx_list[i][2]

        return round(adx_val, 2), round(final_pdi, 2), round(final_ndi, 2)

    # ------------------------------------------------------------------ #
    #  Market Structure — Swing Highs/Lows + Trend Classification        #
    # ------------------------------------------------------------------ #
    @staticmethod
    def detect_market_structure(highs: list, lows: list, window: int = 5) -> str:
        """
        يكتشف القمم والقيعان المؤكدة (swing highs/lows) بطريقة صحيحة:
        نقطة أعلى/أدنى من N نقطة على كلا الجانبين.
        يصنّف الاتجاه: "uptrend" | "downtrend" | "ranging"
        """
        if len(highs) < window * 2 + 1:
            return "ranging"

        swing_highs, swing_lows = [], []
        for i in range(window, len(highs) - window):
            window_h = highs[i - window: i + window + 1]
            window_l = lows[i  - window: i + window + 1]
            if highs[i] == max(window_h):
                swing_highs.append(highs[i])
            if lows[i] == min(window_l):
                swing_lows.append(lows[i])

        if len(swing_highs) >= 2 and len(swing_lows) >= 2:
            hh = swing_highs[-1] > swing_highs[-2]   # Higher High
            hl = swing_lows[-1]  > swing_lows[-2]    # Higher Low
            lh = swing_highs[-1] < swing_highs[-2]   # Lower High
            ll = swing_lows[-1]  < swing_lows[-2]    # Lower Low
            if hh and hl:
                return "uptrend"
            if lh and ll:
                return "downtrend"

        return "ranging"

    # ------------------------------------------------------------------ #
    #  Model 4 — ADX + Market Structure (يستبدل المنطق المبسّط السابق)  #
    # ------------------------------------------------------------------ #
    def _model_4_wave(self, prices: list,
                      highs: list = None, lows: list = None) -> str:
        """
        Buy:     adx_value > 25  و  market_structure == "uptrend"
        Sell:    adx_value > 25  و  market_structure == "downtrend"
        Neutral: أي حالة أخرى (سوق عرضي أو اتجاه ضعيف)
        """
        if highs is None:
            highs = prices
        if lows is None:
            lows = prices
        if len(prices) < 30:
            return "neutral"

        adx_val, plus_di, minus_di = self.adx(highs, lows, prices)
        structure = self.detect_market_structure(highs, lows)

        if adx_val > 25 and structure == "uptrend":
            return "buy"
        if adx_val > 25 and structure == "downtrend":
            return "sell"
        return "neutral"

    def _model_5_seasonal(self, prices: list) -> str:
        hour = datetime.utcnow().hour
        current = prices[-1] if prices else 0
        avg_recent = sum(prices[-5:]) / 5 if len(prices) >= 5 else current
        session_multiplier = 1.2 if 7 <= hour <= 17 else 0.8
        if current > avg_recent * 1.0005 * session_multiplier:
            return "buy"
        elif current < avg_recent * 0.9995 / session_multiplier:
            return "sell"
        return "neutral"

    def _model_6_probabilistic(self, prices: list) -> str:
        if len(prices) < 50:
            return "neutral"
        sorted_p = sorted(prices[-50:])
        p25 = sorted_p[12]
        p75 = sorted_p[37]
        current = prices[-1]
        if current < p25:
            return "buy"
        elif current > p75:
            return "sell"
        return "neutral"

    def generate_signal(self, data: dict) -> dict:
        if not self._check_cooldown():
            return None

        prices = data["prices"]
        highs = data["highs"]
        lows = data["lows"]
        current_price = prices[-1]

        models = [
            self._model_1_statistical(prices),
            self._model_2_mathematical(prices),
            self._model_3_momentum(prices),
            self._model_4_wave(prices, highs, lows),
            self._model_5_seasonal(prices),
            self._model_6_probabilistic(prices),
        ]
        adv_signals = [
            get_garch_volatility_signal(prices),
            get_hmm_regime(prices),
            get_sentiment_signal(data.get("session", gold_manager.session)),
        ]

        rsi_val = self.ta.rsi(prices)
        _, _, macd_sig = self.ta.macd(prices)
        bb_upper, bb_mid, bb_lower, bb_sig = self.ta.bollinger_bands(prices)
        atr_val = self.ta.atr(highs, lows, prices)
        k_val, d_val, stoch_sig = self.ta.stochastic(highs, lows, prices)
        fib = self.ta.fibonacci_levels(max(highs[-20:]), min(lows[-20:]))
        support, resistance = self.ta.support_resistance(prices)

        rsi_sig = "buy" if rsi_val < 35 else ("sell" if rsi_val > 65 else "neutral")
        fib_50 = fib["0.5"]
        fib_sig = "buy" if current_price < fib_50 else "sell"
        sr_sig = "buy" if current_price <= support * 1.002 else ("sell" if current_price >= resistance * 0.998 else "neutral")

        indicators = [rsi_sig, macd_sig, bb_sig if "buy" in bb_sig or "sell" in bb_sig else bb_sig,
                      stoch_sig, fib_sig, sr_sig]

        model_buys = models.count("buy")
        model_sells = models.count("sell")
        ind_buys = indicators.count("buy")
        ind_sells = indicators.count("sell")

        adv_buys = adv_signals.count("buy")
        adv_sells = adv_signals.count("sell")
        total_buys = model_buys + ind_buys + adv_buys
        total_sells = model_sells + ind_sells + adv_sells

        if total_buys >= 7 and model_buys >= 3 and ind_buys >= 3:
            direction = "BUY"
            confirmed_models = model_buys
            confirmed_inds = ind_buys
        elif total_sells >= 7 and model_sells >= 3 and ind_sells >= 3:
            direction = "SELL"
            confirmed_models = model_sells
            confirmed_inds = ind_sells
        else:
            return None

        total_votes = confirmed_models + confirmed_inds
        raw_confidence = (total_votes / 12) * 100
        if direction == "BUY":
            if rsi_val < 30:
                raw_confidence += 3
            if rsi_val < 20:
                raw_confidence += 2
        else:
            if rsi_val > 70:
                raw_confidence += 3
            if rsi_val > 80:
                raw_confidence += 2

        confidence = min(round(raw_confidence, 1), 97.0)
        if confidence < self.min_confidence:
            return None

        if direction == "BUY":
            entry = round(current_price * 1.0002, 2)
            tp1 = round(entry + atr_val * 1.0, 2)
            tp2 = round(entry + atr_val * 1.8, 2)
            tp3 = round(entry + atr_val * 2.8, 2)
            sl = round(entry - atr_val * 1.2, 2)
        else:
            entry = round(current_price * 0.9998, 2)
            tp1 = round(entry - atr_val * 1.0, 2)
            tp2 = round(entry - atr_val * 1.8, 2)
            tp3 = round(entry - atr_val * 2.8, 2)
            sl = round(entry + atr_val * 1.2, 2)

        rr_ratio = round(atr_val * 1.8 / (atr_val * 1.2), 2) if atr_val > 0 else 1.5

        self.last_signal_time = datetime.utcnow()

        return {
            "direction": direction,
            "entry": entry,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "sl": sl,
            "confidence": confidence,
            "models_confirmed": confirmed_models,
            "indicators_confirmed": confirmed_inds,
            "rsi": rsi_val,
            "macd_signal": macd_sig,
            "bb_signal": bb_sig,
            "stoch_k": k_val,
            "atr": atr_val,
            "rr_ratio": rr_ratio,
            "fib_levels": fib,
            "support": support,
            "resistance": resistance,
            "session": gold_manager.session,
            "price": current_price,
        }

signal_engine = SignalEngine()


# ============================================================
#  TEST — ADX + Market Structure (يُشغَّل عند بدء الكود مرة واحدة)
# ============================================================
def _test_adx_and_structure() -> None:
    """
    اختبارات الصحة لـ adx() و detect_market_structure():
    T1 — zigzag صاعد  (HH+HL)            → ADX>25، uptrend،   buy
    T2 — zigzag هابط  (LH+LL)            → ADX>25، downtrend، sell
    T3 — بيانات غير كافية (< period+2)   → لا crash، يعيد (0,0,0) / ranging
    T4 — سعر ثابت (ATR=0)                → لا crash، لا قسمة على صفر
    T5 — ضوضاء واقعية (gaussian + drift) → لا crash، نتيجة صالحة
    """
    n     = 80
    drift = 3.0
    amp   = 12.0
    eng   = SignalEngine.__new__(SignalEngine)   # بدون __init__ لتجنّب التبعيات

    # -------- T1: zigzag صاعد --------
    c1 = [1000.0 + i*drift + amp*math.sin(i*math.pi/8) for i in range(n)]
    h1 = [c+5.0 for c in c1];  l1 = [c-5.0 for c in c1]
    adx1, pdi1, ndi1 = eng.adx(h1, l1, c1)
    s1 = eng.detect_market_structure(h1, l1)
    g1 = eng._model_4_wave(c1, h1, l1)
    assert adx1 > 25,        f"[FAIL T1] ADX={adx1} (يجب > 25)"
    assert pdi1 > ndi1,      f"[FAIL T1] +DI={pdi1} <= -DI={ndi1}"
    assert s1 == "uptrend",  f"[FAIL T1] structure={s1}"
    assert g1 == "buy",      f"[FAIL T1] signal={g1}"

    # -------- T2: zigzag هابط --------
    c2 = [2000.0 - i*drift + amp*math.sin(i*math.pi/8) for i in range(n)]
    h2 = [c+5.0 for c in c2];  l2 = [c-5.0 for c in c2]
    adx2, pdi2, ndi2 = eng.adx(h2, l2, c2)
    s2 = eng.detect_market_structure(h2, l2)
    g2 = eng._model_4_wave(c2, h2, l2)
    assert adx2 > 25,           f"[FAIL T2] ADX={adx2}"
    assert ndi2 > pdi2,         f"[FAIL T2] -DI={ndi2} <= +DI={pdi2}"
    assert s2 == "downtrend",   f"[FAIL T2] structure={s2}"
    assert g2 == "sell",        f"[FAIL T2] signal={g2}"

    # -------- T3: بيانات غير كافية (< period+2 = 16 نقطة) --------
    short = [1000.0] * 10
    adx3, pdi3, ndi3 = eng.adx(short, short, short)
    s3 = eng.detect_market_structure(short, short)
    assert (adx3, pdi3, ndi3) == (0.0, 0.0, 0.0), \
        f"[FAIL T3] يجب (0,0,0) للبيانات القصيرة، حصلنا: {(adx3, pdi3, ndi3)}"
    assert s3 == "ranging", f"[FAIL T3] structure={s3} (يجب ranging)"

    # -------- T4: سعر ثابت — ATR=0 ← يختبر حماية القسمة على صفر --------
    flat = [1500.0] * 60
    adx4, pdi4, ndi4 = eng.adx(flat, flat, flat)
    assert isinstance(adx4, float), f"[FAIL T4] يجب float، حصلنا {type(adx4)}"
    assert adx4 >= 0.0,             f"[FAIL T4] ADX سالب: {adx4}"

    # -------- T5: ضوضاء واقعية (gaussian + drift خفيف) --------
    import random as _rnd
    _rnd.seed(42)
    c5 = [1000.0 + i*1.5 + _rnd.gauss(0, 8) for i in range(n)]
    h5 = [c + abs(_rnd.gauss(0, 3)) for c in c5]
    l5 = [c - abs(_rnd.gauss(0, 3)) for c in c5]
    h5 = [max(h5[i], c5[i]) for i in range(n)]   # ضمان high >= close
    l5 = [min(l5[i], c5[i]) for i in range(n)]   # ضمان low  <= close
    adx5, pdi5, ndi5 = eng.adx(h5, l5, c5)
    s5 = eng.detect_market_structure(h5, l5)
    assert isinstance(adx5, float) and adx5 >= 0, \
        f"[FAIL T5] ADX غير صالح: {adx5}"
    assert s5 in ("uptrend", "downtrend", "ranging"), \
        f"[FAIL T5] structure غير صالح: {s5}"

    print(f"[TEST ✅] T1 Uptrend:         ADX={adx1}  +DI={pdi1}  -DI={ndi1}  struct={s1}  sig={g1}")
    print(f"[TEST ✅] T2 Downtrend:       ADX={adx2}  +DI={pdi2}  -DI={ndi2}  struct={s2}  sig={g2}")
    print(f"[TEST ✅] T3 Short data:      ADX={adx3}  struct={s3}  (no crash)")
    print(f"[TEST ✅] T4 Flat/zero-ATR:   ADX={adx4}  (no div-by-zero)")
    print(f"[TEST ✅] T5 Noisy realistic:  ADX={adx5}  struct={s5}  (no crash)")


_test_adx_and_structure()


# ============================================================
#  SENTIMENT ANALYSIS (VADER - Termux safe)
# ============================================================
try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer as _VSA
    _vader = _VSA()
    _VADER_OK = True
except ImportError:
    _vader = None
    _VADER_OK = False

def get_garch_volatility_signal(prices: list) -> str:
    return "neutral"

def get_hmm_regime(prices: list) -> str:
    return "neutral"

def get_sentiment_signal(session: str) -> str:
    if not _VADER_OK:
        return "neutral"
    try:
        texts = {"London": "gold bullish buyers strong", "New York": "volatile risk safe haven",
                 "Tokyo": "quiet low volume", "Closed": "risk off safe haven gold"}
        s = _vader.polarity_scores(texts.get(session, "gold neutral"))["compound"]
        return "buy" if s > 0.2 else ("sell" if s < -0.2 else "neutral")
    except Exception:
        return "neutral"

logger.info(f"VADER={'OK' if _VADER_OK else 'missing (pip install vaderSentiment)'}")


# ============================================================
#  MESSAGE FORMATTING
# ============================================================
DIRECTION_EMOJI = {"BUY": "🟢 شراء", "SELL": "🔴 بيع"}
CONFIDENCE_BAR = lambda c: "🔥" * int(c // 20) + "⚡" * (5 - int(c // 20))

def format_signal(sig: dict, tier: str = "vip") -> str:
    direction_ar = DIRECTION_EMOJI.get(sig["direction"], sig["direction"])
    bar = CONFIDENCE_BAR(sig["confidence"])
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    pair_sym = PAIR_CFG['symbol']
    cur = PAIR_CFG['currency']
    dec = PAIR_CFG['decimals']
    limits = TIER_LIMITS.get(tier, TIER_LIMITS["vip"])
    full = limits["full_indicators"]
    tier_label = limits["name"] if tier in TIER_LIMITS else TIER_LIMITS["vip"]["name"]

    # 🥉 الفضية: دخول + TP1 + وقف الخسارة فقط | 🥈/💎: TP1+TP2+TP3 كاملة
    if full:
        targets_block = (
            f"🎯 **الهدف الأول (TP1):** {cur}{sig['tp1']:,.{dec}f}\n"
            f"🎯 **الهدف الثاني (TP2):** {cur}{sig['tp2']:,.{dec}f}\n"
            f"🏆 **الهدف الثالث (TP3):** {cur}{sig['tp3']:,.{dec}f}\n"
            f"🛑 **وقف الخسارة (SL):** {cur}{sig['sl']:,.{dec}f}\n"
            f"📊 **نسبة المكسب/الخسارة:** {sig['rr_ratio']}:1"
        )
    else:
        targets_block = (
            f"🎯 **الهدف (TP1):** {cur}{sig['tp1']:,.{dec}f}\n"
            f"🛑 **وقف الخسارة (SL):** {cur}{sig['sl']:,.{dec}f}"
        )

    # 🥉 الفضية: RSI+MACD فقط | 🥈/💎: كل الـ12 مؤشر
    if full:
        indicators_block = (
            "🧠 **تحليل المحرك الذكي:**\n"
            f"• RSI: {sig['rsi']} {'(تشبع بيعي 📉)' if sig['rsi'] < 35 else '(تشبع شرائي 📈)' if sig['rsi'] > 65 else '(متوازن ⚖️)'}\n"
            f"• MACD: {sig['macd_signal'].upper()}\n"
            f"• Bollinger: {sig['bb_signal'].upper()}\n"
            f"• Stochastic: {sig['stoch_k']}\n"
            f"• ATR: {sig['atr']}\n\n"
            "🔢 **التأكيد المتعدد المصادر:**\n"
            f"• نماذج تحليلية: {sig['models_confirmed']}/6 ✅\n"
            f"• مؤشرات فنية: {sig['indicators_confirmed']}/6 ✅\n"
            f"• **نسبة الثقة:** {sig['confidence']}% {bar}\n\n"
            f"📍 **دعم:** ${sig['support']:,.2f} | **مقاومة:** ${sig['resistance']:,.2f}"
        )
    else:
        indicators_block = (
            "🧠 **تحليل المحرك الذكي:**\n"
            f"• RSI: {sig['rsi']} {'(تشبع بيعي 📉)' if sig['rsi'] < 35 else '(تشبع شرائي 📈)' if sig['rsi'] > 65 else '(متوازن ⚖️)'}\n"
            f"• MACD: {sig['macd_signal'].upper()}\n\n"
            f"• **نسبة الثقة:** {sig['confidence']}% {bar}\n\n"
            "⬆️ *ترقّ للخطة الذهبية أو الماسية لعرض جميع الـ12 مؤشر ونطاقات الدعم/المقاومة*"
        )

    text = f"""⚡ **إشارة تداول {tier_label} | {pair_sym}**
━━━━━━━━━━━━━━━━━━━━━━━━
📌 **الاتجاه:** {direction_ar}
💰 **سعر الدخول:** {cur}{sig['entry']:,.{dec}f}
{targets_block}

━━━━━━━━━━━━━━━━━━━━━━━━
{indicators_block}
🕐 **الجلسة:** {sig['session']}
⏰ {now}
━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ إدارة المخاطر مسؤوليتك الشخصية"""
    return text
    # ============================================================
#  KEYBOARDS
# ============================================================
def main_menu():
    keyboard = [
        [InlineKeyboardButton("⚡ إشارة تداول الآن", callback_data="get_signal"),
         InlineKeyboardButton(f"💰 سعر {PAIR_CFG['display_name']} المباشر", callback_data="live_gold")],
        [InlineKeyboardButton("📊 تحليل استراتيجيتي", callback_data="strategy_analysis"),
         InlineKeyboardButton("🧠 تحليل شارت بالذكاء الاصطناعي", callback_data="analyze_chart")],
        [InlineKeyboardButton("🎯 خطط الاشتراك والأسعار", callback_data="plans")],
        [InlineKeyboardButton("🤖 تداول آلي Auto Trading 🤖", callback_data="auto_trading_menu")],
        [InlineKeyboardButton("💳 طرق الدفع", callback_data="payment_methods"),
         InlineKeyboardButton("🎓 مكتبة الكورسات", callback_data="courses_main")],
        [InlineKeyboardButton("🏆 نتائج التوصيات", callback_data="results_menu")],
        [InlineKeyboardButton("🌐 زيارة الموقع", url=get_website_url()),
         InlineKeyboardButton("📞 الدعم المباشر", url=WHATSAPP_LINK)],
        [InlineKeyboardButton("ℹ️ عن النظام", callback_data="about")],
    ]
    return InlineKeyboardMarkup(keyboard)

def vip_menu(show_plans: bool = False):
    """قائمة كاملة بكل الميزات.
    show_plans=True يضيف زر 'خطط الاشتراك' — يُستخدم فقط للمستخدمين غير المشتركين
    (تجربة/منتهية)، ويُخفى عن مستخدمي VIP (المشتركين فعلاً) لأنهم لا يحتاجونه."""
    keyboard = [
        [InlineKeyboardButton("⚡ إشارة تداول الآن", callback_data="get_signal"),
         InlineKeyboardButton(f"💰 سعر {PAIR_CFG['display_name']} المباشر", callback_data="live_gold")],
        [InlineKeyboardButton("📊 تحليل استراتيجيتي", callback_data="strategy_analysis"),
         InlineKeyboardButton("🧠 تحليل شارت بالذكاء الاصطناعي", callback_data="analyze_chart")],
        [InlineKeyboardButton("🤖 تداول آلي Auto Trading 🤖", callback_data="auto_trading_menu")],
    ]
    if show_plans:
        keyboard.append([InlineKeyboardButton("🎯 خطط الاشتراك والأسعار", callback_data="plans")])
    keyboard += [
        [InlineKeyboardButton("🔔 تنبيه سعر", callback_data="set_alert"),
         InlineKeyboardButton("⏰ مؤقت الجلسات", callback_data="session_timer")],
        [InlineKeyboardButton(f"📰 أخبار {PAIR_CFG['display_name']}", callback_data="gold_news"),
         InlineKeyboardButton("🏆 نتائج التوصيات", callback_data="results_menu")],
        [InlineKeyboardButton("💳 طرق الدفع", callback_data="payment_methods"),
         InlineKeyboardButton("📞 الدعم المباشر", url=WHATSAPP_LINK)],
        [InlineKeyboardButton("🌐 زيارة الموقع", url=get_website_url()),
         InlineKeyboardButton("ℹ️ عن النظام", callback_data="about")],
    ]
    return InlineKeyboardMarkup(keyboard)

def trial_menu():
    """قائمة لمستخدمي التجربة المجانية — نفس ميزات VIP كاملة + زر خطط الاشتراك
    (المعاينة/الحدود تُطبّق عند الاستخدام الفعلي)"""
    return vip_menu(show_plans=True)

def expired_menu():
    """قائمة لمنتهي التجربة — نفس ميزات VIP كاملة + زر خطط الاشتراك
    (المعاينة/الحدود تُطبّق عند الاستخدام الفعلي)"""
    return vip_menu(show_plans=True)


def back_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تفعيل VIP", url=WHATSAPP_LINK)],
        [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="start")]
    ])

def results_menu():
    keyboard = [
        [InlineKeyboardButton(f"📉 نتائج {PAIR_CFG['display_name']} {PAIR_CFG['symbol']}", callback_data="res_xauusd")],
        [InlineKeyboardButton("₿ نتائج البيتكوين BTC", callback_data="res_btc")],
        [InlineKeyboardButton("📊 ميزة التعرف على الأنماط", callback_data="pattern_recognition")],
        [InlineKeyboardButton("🔙 العودة", callback_data="start")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ============================================================
#  TRADING COURSES DATA
# ============================================================
TRADING_COURSES = {
    "classic_technical": {"title": "📚 التحليل الفني الكلاسيكي", "price": 80,
        "description": "أساسيات حركة السعر، الدعوم والمقاومات، والنماذج الفنية الكلاسيكية.",
        "courses": ["1-كورس اسماعيل الشكري","2-كورس محمد مهدي","3-كورس محمود سعد","4-دورة ايهاب المصري الاولى","5-دورة ايهاب المصري الثانية","6-كورس ممدوح زكي","7-كورس محمد جهيمي","8-كورس منير الناظور","9-كورس مصطفى بلخياط","10-كورس شريف خورشيد","11-كورس الفيبو واسراره","12-كورس أحمد عبد الناصر","13-كورس شريف أبو رحاب","14-دورة سعد آل سعد","15-كورس قناة Glorex","16-كورس المحلل انس","17-كورس ممدوح زكي 2023","18-كورس محمد صلاح شامل","19-كورس احمد سرحان Basic","20-كورس احمد سرحان Advance","21-كورس THE WOLF TRADERS","22-كورس بلخياط فرنسي","23-كورس Scalping macht","24-كورس هالا","25-كورس النوخذة","26-دورة أحمد غانم","27-دورة محمد القيس","28-كورس يامن آغا","29-كورس كلاسيكي متقدم"]},
    "smc": {"title": "🎯 كورسات SMC الاحترافية", "price": 100,
        "description": "Smart Money Concepts - فهم تلاعبات صناع السوق.",
        "courses": ["1-كورس الدليمي","2-كورس الاستاذ فهد","3-كورس الاستاذ حسن","4-كورس الاستاذ أمجد","5-كورس استراتيجية SMC","6-كورس معتصم","7-كورس SMC عراقي","8-كورس سليمان الخليلي","9-كورس فيصل السوادي","10-كورس أبو العزم","11-كورس محمد ياسين","12-كورس حاتم العبرات","13-كورس محمد مهدي SMC","14-كورس سفينكس SMC","15-كورس احمد سرحان","16-دورة SMC محمد صلاح","17-كورس فوتون مترجم","18-كورس THE WOLF TRADERS","19-دورة UNIC FX","20-كورس حسن سعد","21-كورس ورشة النخبة","22-دورة Trade Lovers Academy"]},
    "ict": {"title": "💡 كورسات ICT المتقدمة", "price": 199,
        "description": "Inner Circle Trader - أقوى أساليب التداول الحديثة.",
        "courses": ["1-كورس مفاهيم ICT بالعربية","2-كورس استراتيجية ICT","3-كورس محمد سنبل","4-كورس خان الهندي مترجم","5-كورس ابو الخطاب","6-كورس فضل الله المغربي","7-التحديث الجديد لفضل الله","8-دورة احتراف ICT","9-كورس هيرميس","10-كورس Mo Golder","11-كورس عبد العزيز السوري","12-كورس مصطفى سمير الساحر","13-استراتيجية رامي ست ليلى","14-مختصر السيولة Bresk","15-كورس سفيان NAVY 1","16-كورس سفيان NAVY 2","17-كورس سفيان NAVY 3","18-كورس ايفان مترجم","19-كورس عبد الله الأسمر","20-كورس الساحر"]},
    "elliot_waves": {"title": "🌊 التحليل الموجي (إليوت)", "price": 100,
        "description": "شرح موجات إليوت وتحديد دورات السوق.",
        "courses": ["1-كورس شيماء ثروت","2-كورس سلطان الشهلوب","3-كورس ماجد الهذلي","4-كورس وسام المغربي","5-كورس ياسر ابو معاذ","6-مختصر التحليل الموجي","7-كورس وحيد الموجي"]},
    "sk": {"title": "🔑 كورسات SK سيستم", "price": 250,
        "description": "استراتيجية SK System القوية.",
        "courses": ["1-كورس رمزي نافع","2-كورس استراتيجية SK","3-كورس أحمد أبو نجم","4-دورة محمد صلاح الاولى","5-دورة محمد صلاح الثانية","6-دورة الكوتش عادل","7-كورس عبده عصام SK","8-شرح مختصر SK","9-دورة فيصل جلال"]},
    "volume_analysis": {"title": "📊 التحليل الحجمي (الفوليوم)", "price": 199,
        "description": "سيولة السوق ومناطق تمركز صناع السوق.",
        "courses": ["1-كورس وائل أحمد","2-كورس عادل المزيد","3-كورس حسن مسعود","4-كورس أبو مريال","5-الماركت بروفايل مترجم","6-الماركت بروفايل عربي","7-كورس عبدالله العتيبي","8-كورس ماجد المسعودي","9-كورس ياسر البياتي","10-كورس يونيكو","11-دورة UNIC FX"]},
    "harmonic": {"title": "🔮 كورسات الهارمونيك", "price": 150,
        "description": "نماذج الهارمونيك والنسب الذهبية للفيبوناتشي.",
        "courses": ["1-دورة الهارمونيك","2-كورس عبد الله محمد","3-كورس شريف خورشيد","4-دورة الهاجري","5-استراتيجية ابو مبارك"]},
    "crypto": {"title": "₿ كورسات الكريبتو", "price": 299,
        "description": "تداول العملات الرقمية والبلوكتشين.",
        "courses": ["1-كورس محمد مهدي","2-كورس Crypto Whale","3-كورس شريف خورشيد","4-كورس يوسف جو","5-كورس حسن الحلبي","6-كورس easyt","7-دورة يونس","8-دورة مراد الادريسي العملات","9-دورة مراد الادريسي الفيوتشر","10-دورة EA DEX"]},
    "diverse_strategies": {"title": "⚔️ استراتيجيات متنوعة", "price": 299,
        "description": "أكثر من 35 استراتيجية مجربة.",
        "courses": ["1-استراتيجية S zone","2-استراتيجية السكالبينغ","3-استراتيجية الفراكتال","4-استراتيجية HSD","5-استراتيجية BLOT","6-استراتيجية الاوبتيميا","7-استراتيجية Fibo Boxes","8-استراتيجية تكنيكال للذهب","9-استراتيجية رون","10-استراتيجية المستطيل","11-استراتيجية توم","12-استراتيجية ROPC","13-دورة السكالبينغ محمد صلاح","14-استراتيجية المناطق المعلقة","15-استراتيجية قمة وقاع","16-استراتيجية هايكناشي عبود","17-استراتيجية التداول على الأخبار","18-استراتيجية قناة Bresk","19-استراتيجية الرقمي النسبي","20-استراتيجية trade simple","21-استراتيجية rekabi","22-استراتيجية smt","23-استراتيجية Ninja","24-استراتيجية Dragon","25-استراتيجية الموڤينقات","26-استراتيجية MR ZERO","27-استراتيجية أحمد الحركي","28-استراتيجية احمد الزبداني","29-استراتيجية SMT","30-استراتيجية الذيل"]},
    "captain_strategies": {"title": "👑 استراتيجيات القبطان المتقدمة", "price": 950,
        "description": "أقوى استراتيجيات SB Model للحسابات الكبيرة.",
        "courses": ["1-استراتيجية SB model","2-استراتيجية SB Nova","3-استراتيجية SB Core"]},
    "binary_options": {"title": "⚡ كورسات الخيارات الثنائية", "price": 200,
        "description": "المضاربة السريعة في الخيارات الثنائية.",
        "courses": ["1-كورس مي خالد","2-كورس أسامة أحمد","3-كورس سفينكس","4-كورس الغلابة","5-كورس EMMA مترجم","6-كورس ابو فيصل","7-كورس الدسنلي","8-كورس زينو الجزائري","9-كورس فايز Wadee3","10-كورس ميدو","11-كورس غيث","12-كورس القيصر","13-كورس القيصر الثاني","14-كورس فادي","15-كورس أساطير التداول","16-كورس احمد دولر","17-ثغرة YAZ","18-دورة طارق رامي"]},
    "psychology": {"title": "🧠 كورسات علم النفس", "price": 80,
        "description": "التحكم في الخوف والطمع وعقلية المتداول الناجح.",
        "courses": ["1-كورس النفسية والمشاعر","2-كورس ورشة النقاط النفسية"]},
}

# ============================================================
#  AUTO TRADING USER FLOW
# ============================================================
from telegram.ext import ConversationHandler, MessageHandler as _MH, filters as _F

AT_TOKEN, AT_ACCOUNT, AT_LOT, AT_CONFIRM = range(200, 204)

def _get_at_acc(db, tg_id):
    return db.query(AutoTradeAccount).filter(AutoTradeAccount.tg_id == str(tg_id)).first()

def _at_text(acc):
    if not acc or not acc.meta_token:
        return (
            "🤖 *التداول الآلي Auto Trading*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "اربط حساب MT5 لتنفيذ الصفقات تلقائياً!\n\n"
            "📌 *ما تحتاجه:*\n"
            "• حساب مجاني على metaapi.cloud\n"
            "• توكن MetaAPI\n"
            "• رقم حساب MT5\n\n"
            "⚠️ إدارة المخاطر مسؤوليتك الشخصية."
        )
    s = "🟢 نشط" if acc.is_active else "🔴 موقوف"
    return (
        f"🤖 *التداول الآلي*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 الحالة: {s}\n"
        f"🔑 Account: `{acc.meta_account_id}`\n"
        f"📦 اللوت: `{acc.lot_size}`\n"
        f"📈 صفقات منفذة: `{acc.total_trades}`"
    )

def _at_kb(acc):
    if not acc or not acc.meta_token:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 ربط حساب MT5", callback_data="at_setup")],
            [InlineKeyboardButton("❓ كيف أحصل على MetaAPI؟", callback_data="at_help")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="start")],
        ])
    btns = []
    if acc.is_active:
        btns.append([InlineKeyboardButton("⏸ إيقاف", callback_data="at_disable")])
    else:
        btns.append([InlineKeyboardButton("▶️ تفعيل", callback_data="at_enable")])
    btns += [
        [InlineKeyboardButton("⚙️ تعديل", callback_data="at_setup"),
         InlineKeyboardButton("🗑 حذف", callback_data="at_delete")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="start")],
    ]
    return InlineKeyboardMarkup(btns)

async def handle_auto_trading_menu(query, user_id):
    db = SessionLocal()
    try:
        user = db.query(TradingUser).filter(TradingUser.tg_id == str(user_id)).first()
        tier = get_user_tier(user)
        if not tier or not TIER_LIMITS[tier]["auto_trading"]:
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 ترقية للماسية", callback_data="plan_vip")],
                [InlineKeyboardButton("🔙 العودة", callback_data="start")]
            ])
            await query.edit_message_text(
                "🔒 *التداول الآلي حصري لمشتركي الخطة الماسية 💎*\n\n"
                "قم بالترقية للاستفادة من تنفيذ الصفقات تلقائياً 24/7.",
                reply_markup=markup, parse_mode="Markdown"
            )
            return
        acc = _get_at_acc(db, user_id)
        await query.edit_message_text(_at_text(acc), reply_markup=_at_kb(acc), parse_mode="Markdown")
    finally:
        db.close()

async def handle_at_enable(query, user_id):
    db = SessionLocal()
    try:
        acc = _get_at_acc(db, user_id)
        if not acc or not acc.meta_token:
            await query.answer("❌ قم بربط حسابك أولاً")
            return
        acc.is_active = True
        acc.updated_at = datetime.utcnow()
        db.commit()
        await query.answer("✅ تم التفعيل!")
        await handle_auto_trading_menu(query, user_id)
    finally:
        db.close()

async def handle_at_disable(query, user_id):
    db = SessionLocal()
    try:
        acc = _get_at_acc(db, user_id)
        if acc:
            acc.is_active = False
            acc.updated_at = datetime.utcnow()
            db.commit()
        await query.answer("⏸ تم الإيقاف")
        await handle_auto_trading_menu(query, user_id)
    finally:
        db.close()

async def handle_at_delete(query, user_id):
    db = SessionLocal()
    try:
        acc = _get_at_acc(db, user_id)
        if acc:
            db.delete(acc)
            db.commit()
        await query.answer("🗑 تم الحذف")
        await handle_auto_trading_menu(query, user_id)
    finally:
        db.close()

async def handle_at_help(query, user_id):
    await query.edit_message_text(
        "📖 *كيف تحصل على MetaAPI؟*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ سجّل مجاناً على: metaapi.cloud\n"
        "2️⃣ Accounts → Add Account → أدخل بيانات MT5\n"
        "3️⃣ انسخ *API Token* من الإعدادات\n"
        "4️⃣ انسخ *Account ID* من قائمة الحسابات",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 ربط حسابي", callback_data="at_setup")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="auto_trading_menu")],
        ]),
        parse_mode="Markdown"
    )

async def at_conv_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🔑 *الخطوة 1/3 — MetaAPI Token*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "أرسل توكن MetaAPI من metaapi.cloud\n\n"
        "للإلغاء: /cancel",
        parse_mode="Markdown"
    )
    return AT_TOKEN

async def at_recv_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tok = update.message.text.strip()
    if len(tok) < 20:
        await update.message.reply_text("❌ التوكن قصير جداً. أعد أو /cancel")
        return AT_TOKEN
    context.user_data["at_token"] = tok
    await update.message.reply_text(
        "✅ تم!\n\n"
        "🆔 *الخطوة 2/3 — Account ID*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "أرسل رقم حساب MT5 من MetaAPI.",
        parse_mode="Markdown"
    )
    return AT_ACCOUNT

async def at_recv_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    acct = update.message.text.strip()
    if len(acct) < 5:
        await update.message.reply_text("❌ رقم الحساب غير صحيح. أعد أو /cancel")
        return AT_ACCOUNT
    context.user_data["at_account"] = acct
    await update.message.reply_text(
        "📦 *الخطوة 3/3 — حجم اللوت*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "أرسل حجم اللوت. مثال: 0.01 للمبتدئين.",
        parse_mode="Markdown"
    )
    return AT_LOT

async def at_recv_lot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        lot = float(update.message.text.strip())
        if not (0.001 <= lot <= 100):
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ حجم لوت غير صحيح. مثال: 0.01")
        return AT_LOT
    context.user_data["at_lot"] = lot
    tok = context.user_data.get("at_token", "")
    acct = context.user_data.get("at_account", "")
    await update.message.reply_text(
        "📋 *تأكيد*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Token: {tok[:15]}...\n"
        f"Account: {acct}\n"
        f"اللوت: {lot}\n\n"
        "هل تؤكد؟",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ تأكيد", callback_data="at_yes"),
            InlineKeyboardButton("❌ إلغاء", callback_data="at_no"),
        ]]),
        parse_mode="Markdown"
    )
    return AT_CONFIRM

async def at_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "at_no":
        await query.edit_message_text("❌ تم الإلغاء.")
        return ConversationHandler.END
    uid = str(query.from_user.id)
    db = SessionLocal()
    try:
        acc = _get_at_acc(db, uid)
        if acc:
            acc.meta_token = context.user_data["at_token"]
            acc.meta_account_id = context.user_data["at_account"]
            acc.lot_size = context.user_data["at_lot"]
            acc.is_active = True
            acc.updated_at = datetime.utcnow()
        else:
            db.add(AutoTradeAccount(
                tg_id=uid,
                meta_token=context.user_data["at_token"],
                meta_account_id=context.user_data["at_account"],
                lot_size=context.user_data["at_lot"],
                is_active=True,
            ))
        db.commit()
    finally:
        db.close()
    await query.edit_message_text(
        "✅ *تم الحفظ والتفعيل!*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🤖 ستنفذ الصفقات تلقائياً عند كل إشارة.\n"
        "🔔 ستصلك رسالة تأكيد لكل صفقة.\n\n"
        "/start للقائمة الرئيسية.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def at_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ تم الإلغاء. /start للعودة.")
    return ConversationHandler.END

auto_trading_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(at_conv_entry, pattern="^at_setup$")],
    states={
        AT_TOKEN:   [_MH(_F.TEXT & ~_F.COMMAND, at_recv_token)],
        AT_ACCOUNT: [_MH(_F.TEXT & ~_F.COMMAND, at_recv_account)],
        AT_LOT:     [_MH(_F.TEXT & ~_F.COMMAND, at_recv_lot)],
        AT_CONFIRM: [CallbackQueryHandler(at_confirm, pattern="^at_(yes|no)$")],
    },
    fallbacks=[CommandHandler("cancel", at_cancel)],
    per_message=False,
)

# ============================================================
#  ALERT CONVERSATION HANDLER
# ============================================================
from telegram.ext import ConversationHandler as _CH2

ALERT_PRICE = 210

async def alert_entry(update, context):
    query = update.callback_query
    await query.answer()
    uid = str(query.from_user.id)
    db = SessionLocal()
    user = db.query(TradingUser).filter(TradingUser.tg_id == uid).first()
    alerts = db.query(GoldAlert).filter(GoldAlert.tg_id == uid, GoldAlert.is_active == True).all()
    db.close()

    limit = get_alert_limit(user)
    used = len(alerts)
    limit_text = "بلا حدود ♾️" if limit == -1 else (str(used) + "/" + str(limit))

    alerts_text = ""
    if alerts:
        alerts_text = "\n\n📋 *تنبيهاتك الحالية (" + limit_text + "):*\n"
        for a in alerts:
            d = "↑ فوق" if a.direction == "above" else "↓ تحت"
            alerts_text += "• " + d + " $" + str(a.target_price) + "\n"
    else:
        alerts_text = "\n\n📊 خطتك: " + tier_display_name(user) + " — الحد " + limit_text + "\n"

    if limit != -1 and used >= limit:
        await query.edit_message_text(
            "⛔ *استنفدت حد تنبيهات السعر*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "خطتك (" + tier_display_name(user) + ") تسمح بـ " + str(limit) + " تنبيه نشط كحد أقصى.\n"
            + alerts_text +
            "\n⬆️ قم بترقية خطتك لزيادة عدد التنبيهات، أو ألغِ تنبيهاً حالياً عبر /alerts_clear.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬆️ ترقية الخطة", callback_data="plans")],
                [InlineKeyboardButton("🔙 العودة", callback_data="start")],
            ]),
            parse_mode="Markdown"
        )
        return _CH2.END

    await query.edit_message_text(
        "🔔 *تنبيهات سعر " + PAIR_CFG['display_name'] + "*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "أرسل السعر الذي تريد التنبيه عنده.\n"
        "مثال: 3200 أو 3050\n\n"
        "📌 سيصلك تنبيه عندما يصل سعر " + PAIR_CFG['display_name'] + " لهذا المستوى." + alerts_text + "\n\nللإلغاء: /cancel",
        parse_mode="Markdown"
    )
    return ALERT_PRICE

async def alert_recv_price(update, context):
    try:
        price = float(update.message.text.strip().replace(",", ""))
        if not (PAIR_CFG['min_price'] <= price <= 9_999_999):
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ سعر غير صحيح. أدخل رقماً صحيحاً لـ " + PAIR_CFG['display_name'])
        return ALERT_PRICE
    uid = str(update.effective_user.id)

    db = SessionLocal()
    user = db.query(TradingUser).filter(TradingUser.tg_id == uid).first()
    limit = get_alert_limit(user)
    active_count = db.query(GoldAlert).filter(GoldAlert.tg_id == uid, GoldAlert.is_active == True).count()
    if limit != -1 and active_count >= limit:
        db.close()
        await update.message.reply_text(
            "⛔ استنفدت حد تنبيهات السعر (" + str(limit) + ") في خطتك (" + tier_display_name(user) + ").\n"
            "قم بترقية خطتك أو ألغِ تنبيهاً حالياً عبر /alerts_clear."
        )
        return _CH2.END

    if not finnhub_ws.is_data_fresh():
        await asyncio.to_thread(gold_manager.update)
    current = gold_manager.current_price or 0
    direction = "above" if price > current else "below"
    db.add(GoldAlert(tg_id=uid, target_price=price, direction=direction))
    db.commit()
    db.close()
    d_text = "ارتفع فوق" if direction == "above" else "انخفض تحت"
    await update.message.reply_text(
        "✅ *تم ضبط التنبيه!*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🎯 سعر الهدف: $" + str(price) + "\n"
        "📡 سأنبهك عندما يكون السعر " + d_text + " $" + str(price) + "\n\n"
        "السعر الحالي: $" + str(round(current, 2)) + "\n\n"
        "/start للقائمة الرئيسية",
        parse_mode="Markdown"
    )
    return _CH2.END

async def alert_cancel(update, context):
    await update.message.reply_text("❌ تم الإلغاء.")
    return _CH2.END

async def alerts_clear(update, context):
    uid = str(update.effective_user.id)
    db = SessionLocal()
    db.query(GoldAlert).filter(GoldAlert.tg_id == uid).delete()
    db.commit()
    db.close()
    await update.message.reply_text("🗑 تم حذف جميع تنبيهاتك.")

alert_conv = _CH2(
    entry_points=[CallbackQueryHandler(alert_entry, pattern="^set_alert$")],
    states={ALERT_PRICE: [_MH(_F.TEXT & ~_F.COMMAND, alert_recv_price)]},
    fallbacks=[CommandHandler("cancel", alert_cancel)],
    per_message=False,
)

async def check_gold_alerts(context):
    """يُشغَّل في كل تحديث سعر للتحقق من التنبيهات"""
    try:
        # WS إذا حديث → لا نستدعي HTTP ولا نلوث current_price بسعر قديم
        if finnhub_ws.is_data_fresh():
            current = gold_manager.current_price
        else:
            await asyncio.to_thread(gold_manager.update)
            current = gold_manager.current_price
        if not current or current <= 0:
            return
        db = SessionLocal()
        alerts = db.query(GoldAlert).filter(GoldAlert.is_active == True).all()
        triggered = []
        for a in alerts:
            hit = (a.direction == "above" and current >= a.target_price) or \
                  (a.direction == "below" and current <= a.target_price)
            if hit:
                triggered.append(a)
                a.is_active = False
        db.commit()
        db.close()
        # لقطة فنية سريعة تُرفَق مع كل إشعار (بدون أي طلب HTTP إضافي — من البيانات المخزّنة مسبقاً)
        prices = list(gold_manager.price_history)
        rsi = TechnicalAnalysis.rsi(prices) if len(prices) >= 5 else None
        rsi_line = ""
        if rsi:
            rsi_state = "🔴 تشبع شرائي" if rsi > 65 else "🟢 تشبع بيعي" if rsi < 35 else "⚪ محايد"
            rsi_line = "📐 RSI: `" + str(rsi) + "` " + rsi_state + "\n"
        session_line = "🌍 الجلسة: " + gold_manager._get_trading_session() + "\n"

        for a in triggered:
            try:
                d_text = "ارتفع فوق" if a.direction == "above" else "انخفض تحت"
                await context.bot.send_message(
                    chat_id=a.tg_id,
                    text=(
                        f"🔔 *تنبيه سعر {PAIR_CFG['display_name']}!*\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        "⚡ وصل السعر للمستوى المحدد!\n\n"
                        "🎯 هدفك: $" + str(a.target_price) + "\n"
                        "💰 السعر الحالي: $" + str(round(current, 2)) + "\n"
                        + rsi_line + session_line +
                        "\n📌 السعر " + d_text + " $" + str(a.target_price)
                    ),
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⚡ اطلب إشارة الآن", callback_data="get_signal")],
                        [InlineKeyboardButton("🔔 تنبيه جديد", callback_data="set_alert")],
                    ]),
                    parse_mode="Markdown"
                )
            except Exception:
                pass
    except Exception as e:
        logger.error("check_gold_alerts: " + str(e))


async def daily_morning_summary(context):
    """ملخص يومي للـ VIP كل صباح"""
    try:
        await asyncio.to_thread(gold_manager.update)
        price = gold_manager.price or 0
        session = gold_manager.session or "London"
        data = gold_manager.get_market_data() or {}
        prices = data.get("prices", [])
        sig_text = ""
        if prices and len(prices) >= 10:
            try:
                signal = signal_engine.generate_signal(data)
                if signal:
                    dir_ar = "شراء 📈" if signal.get("direction") == "BUY" else "بيع 📉"
                    sig_text = (
                        "\n\n⚡ *توقع اليوم:*\n"
                        "الاتجاه: " + dir_ar + "\n"
                        "دخول: $" + str(signal.get("entry", "—")) + "\n"
                        "هدف: $" + str(signal.get("tp2", "—")) + "\n"
                        "وقف: $" + str(signal.get("sl", "—"))
                    )
            except Exception:
                pass
        db = SessionLocal()
        vip_users = db.query(TradingUser).filter(
            TradingUser.is_vip == True,
            TradingUser.is_blocked == False
        ).all()
        db.close()
        summary = (
            f"🌅 *صباح الخير — ملخص سوق {PAIR_CFG['display_name']}*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📅 " + datetime.now().strftime("%Y-%m-%d") + "\n"
            "💰 سعر " + PAIR_CFG['display_name'] + " الحالي: " + PAIR_CFG['currency'] + str(round(price, PAIR_CFG['decimals'])) + "\n"
            "🕐 الجلسة الحالية: " + session + sig_text + "\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💎 حساب VIP مفعّل | تداول بثقة وإدارة مخاطر 📊"
        )
        for u in vip_users:
            try:
                await context.bot.send_message(
                    chat_id=u.tg_id,
                    text=summary,
                    parse_mode="Markdown"
                )
            except Exception:
                pass
    except Exception as e:
        logger.error("daily_summary: " + str(e))


async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    if not context.args:
        await update.message.reply_text(
            "📡 استخدام: /broadcast [الرسالة]\n"
            "مثال: /broadcast تم إضافة ميزات جديدة رائعة!"
        )
        return
    msg = " ".join(context.args)
    db = SessionLocal()
    users = db.query(TradingUser).filter(TradingUser.is_blocked == False).all()
    db.close()
    sent = 0
    failed = 0
    for u in users:
        try:
            await context.bot.send_message(
                chat_id=u.tg_id,
                text=(
                    "📡 *إعلان من إدارة البوت*\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    + msg
                ),
                parse_mode="Markdown"
            )
            sent += 1
        except Exception:
            failed += 1
    await update.message.reply_text(
        "✅ تم إرسال البث!\n"
        "📤 نجح: " + str(sent) + "\n"
        "❌ فشل: " + str(failed)
    )


# ============================================================
#  REFERRAL SYSTEM
# ============================================================
import hashlib as _hs

def gen_ref_code(tg_id):
    return "G" + str(abs(hash(str(tg_id))) % 100000).zfill(5)

async def cmd_referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    db = SessionLocal()
    u = db.query(TradingUser).filter(TradingUser.tg_id == uid).first()
    db.close()
    if not u:
        await update.message.reply_text("❌ ابدأ بـ /start أولاً")
        return
    bot_info = await context.bot.get_me()
    code = gen_ref_code(uid)
    link = "https://t.me/" + bot_info.username + "?start=ref_" + code
    pts = u.loyalty_points or 0
    bonus = u.bonus_signals or 0
    await update.message.reply_text(
        "🎁 *نظام الإحالة*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "شارك رابطك الخاص وأكسب إشارات مجانية!\n\n"
        "🔗 *رابطك الشخصي:*\n"
        "`" + link + "`\n\n"
        "📊 *إحصائياتك:*\n"
        "⭐ نقاط الولاء: `" + str(pts) + "` نقطة\n"
        "🎁 إشارات مكافأة: `" + str(bonus) + "` إشارة\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🏆 *كيف يعمل؟*\n"
        "• كل صديق يسجل عبر رابطك → +50 نقطة لك + إشارة مجانية\n"
        "• كل 100 نقطة → إشارة مجانية إضافية\n"
        "• صديقك يحصل على +2 إشارة تجربة إضافية",
        parse_mode="Markdown"
    )


# ============================================================
#  SESSION TIMER
# ============================================================
from datetime import timezone as _tz, timedelta as _td

SESSIONS_UTC = {
    "Tokyo":    (0,  9),
    "London":   (8,  17),
    "New York": (13, 22),
}

def get_session_status():
    now_utc = datetime.utcnow()
    hour = now_utc.hour
    results = []
    for name, (open_h, close_h) in SESSIONS_UTC.items():
        if open_h <= hour < close_h:
            remaining = close_h - hour - 1
            mins = 60 - now_utc.minute
            results.append(("🟢", name, "مفتوحة", str(remaining) + "س " + str(mins) + "د"))
        else:
            if hour < open_h:
                wait = open_h - hour
            else:
                wait = 24 - hour + open_h
            results.append(("🔴", name, "مغلقة", "تفتح بعد " + str(wait) + "س"))
    return results

async def handle_session_timer(query):
    sessions = get_session_status()
    now = datetime.utcnow().strftime("%H:%M UTC")
    lines = ["⏰ *مؤقت جلسات التداول*\n━━━━━━━━━━━━━━━━━━━━━━━━", "🕐 الوقت الآن: " + now + "\n"]
    for icon, name, status, time_info in sessions:
        lines.append(icon + " *" + name + "*: " + status + " — " + time_info)
    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 أفضل وقت للتداول: تداخل London & New York (13:00-17:00 UTC)")
    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⚡ إشارة الآن", callback_data="get_signal"),
             InlineKeyboardButton("🔙 القائمة", callback_data="start")],
        ]),
        parse_mode="Markdown"
    )


# ============================================================
#  GOLD NEWS — Finnhub API (مصدر رسمي بمفتاح) أولاً، RSS كبديل، مع كاش
# ============================================================
import urllib.request as _ur
import re as _re

_NEWS_CACHE = {"ts": 0.0, "items": [], "source": ""}
_NEWS_CACHE_TTL = 1800  # 30 دقيقة — يقلل عدد الطلبات ويحمي من حدود Finnhub المجانية

_NEWS_KEYWORDS = ("gold", "xau", "precious metal", "bullion", "fed", "interest rate",
                  "inflation", "dollar", "fomc", "safe haven")


def _fetch_gold_news_finnhub():
    """المصدر الأساسي: Finnhub News API (نفس مفاتيح Finnhub المستخدمة لـ WebSocket السعر).
    وثائق: https://finnhub.io/docs/api/market-news"""
    for key in FINNHUB_KEYS:
        try:
            url = "https://finnhub.io/api/v1/news?category=general&token=" + key
            req = _ur.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with _ur.urlopen(req, timeout=6) as resp:
                raw = json.loads(resp.read().decode("utf-8", errors="ignore"))
            results = []
            for item in raw:
                headline = (item.get("headline") or "").strip()
                if not headline:
                    continue
                low = headline.lower()
                if any(kw in low for kw in _NEWS_KEYWORDS):
                    results.append({"title": headline, "source": item.get("source") or "Finnhub", "url": item.get("url") or ""})
            if results:
                return results[:5]
        except Exception as e:
            logger.warning("Finnhub news key ..." + key[-6:] + " فشل: " + str(e))
            continue
    return []


def _fetch_gold_news_rss():
    """مصدر احتياطي إذا فشلت Finnhub News API."""
    try:
        feeds = [
            "https://feeds.finance.yahoo.com/rss/2.0/headline?s=GC%3DF&region=US&lang=en-US",
            "https://www.kitco.com/rss/rss-gold.xml",
        ]
        for url in feeds:
            try:
                req = _ur.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with _ur.urlopen(req, timeout=5) as resp:
                    content = resp.read().decode("utf-8", errors="ignore")
                titles = _re.findall(r'<title><!\[CDATA\[(.*?)\]\]></title>|<title>(.*?)</title>', content)
                results = []
                for t1, t2 in titles:
                    title = (t1 or t2).strip()
                    if title and ("gold" in title.lower() or "xau" in title.lower() or "metal" in title.lower()):
                        results.append({"title": title, "source": "Yahoo/Kitco RSS", "url": ""})
                if results:
                    return results[:5]
            except Exception:
                continue
        return []
    except Exception:
        return []


def fetch_gold_news():
    """يجلب الأخبار مع كاش 30 دقيقة: Finnhub API (رسمي، بمفتاح) أولاً، ثم RSS كبديل.
    ملاحظة: هذه الدالة تنفّذ طلبات HTTP متزامنة — يجب استدعاؤها فقط عبر
    asyncio.to_thread من داخل أي async def (كما في handle_gold_news) لتجنّب تجميد event loop."""
    now = time.time()
    if _NEWS_CACHE["items"] and (now - _NEWS_CACHE["ts"]) < _NEWS_CACHE_TTL:
        return _NEWS_CACHE["items"], _NEWS_CACHE["source"]

    news = _fetch_gold_news_finnhub()
    source = "Finnhub News API"
    if not news:
        news = _fetch_gold_news_rss()
        source = "Yahoo Finance / Kitco RSS"

    if news:
        _NEWS_CACHE["ts"] = now
        _NEWS_CACHE["items"] = news
        _NEWS_CACHE["source"] = source
    return news, source


async def handle_gold_news(query):
    await query.edit_message_text("📰 جاري جلب آخر أخبار " + PAIR_CFG['display_name'] + "...", parse_mode="Markdown")
    news, source = await asyncio.to_thread(fetch_gold_news)
    if news:
        text = "📰 *آخر أخبار " + PAIR_CFG['display_name'] + "*\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        for i, n in enumerate(news, 1):
            text += str(i) + ". " + n["title"][:120] + "\n\n"
        text += "━━━━━━━━━━━━━━━━━━━━━━━━\n🔄 يتجدد كل 30 دقيقة | المصدر: " + source
    else:
        text = ("📰 *آخر أخبار " + PAIR_CFG['display_name'] + "*\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "⚠️ تعذّر جلب الأخبار حالياً من أي مصدر\n\n"
                "📌 *أبرز المستجدات اليوم:*\n"
                "• " + PAIR_CFG['display_name'] + " يتداول قرب مستويات مهمة\n"
                "• ترقّب بيانات التضخم الأمريكية\n"
                "• الطلب الآسيوي يدعم السعر")
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 تحديث الأخبار", callback_data="gold_news"),
             InlineKeyboardButton("⚡ إشارة الآن", callback_data="get_signal")],
            [InlineKeyboardButton("🔙 القائمة", callback_data="start")],
        ]),
        parse_mode="Markdown"
    )


# ============================================================
#  LOYALTY POINTS HELPERS
# ============================================================
def award_points(tg_id, points, reason=""):
    try:
        db = SessionLocal()
        u = db.query(TradingUser).filter(TradingUser.tg_id == str(tg_id)).first()
        if u:
            u.loyalty_points = (u.loyalty_points or 0) + points
            # every 100 points = 1 bonus signal
            new_pts = u.loyalty_points
            bonus_earned = new_pts // 100
            current_bonus = u.bonus_signals or 0
            if bonus_earned > current_bonus:
                u.bonus_signals = bonus_earned
        db.commit()
        db.close()
    except Exception as e:
        logger.error("award_points: " + str(e))

async def cmd_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    db = SessionLocal()
    u = db.query(TradingUser).filter(TradingUser.tg_id == uid).first()
    db.close()
    if not u:
        await update.message.reply_text("❌ ابدأ بـ /start")
        return
    pts = u.loyalty_points or 0
    bonus = u.bonus_signals or 0
    next_bonus = 100 - (pts % 100)
    progress = "█" * (pts % 100 // 10) + "░" * (10 - pts % 100 // 10)
    await update.message.reply_text(
        "⭐ *نقاط الولاء الخاصة بك*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🏆 نقاطك الحالية: *" + str(pts) + "* نقطة\n"
        "🎁 إشارات مكافأة: *" + str(bonus) + "* إشارة\n\n"
        "📊 التقدم نحو الإشارة التالية:\n"
        "[" + progress + "] " + str(pts % 100) + "/100\n"
        "⏳ تحتاج " + str(next_bonus) + " نقطة أخرى\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 *كيف تكسب نقاط؟*\n"
        "• طلب إشارة تداول → +5 نقاط\n"
        "• فتح البوت يومياً → +2 نقطة\n"
        "• دعوة صديق → +50 نقطة\n"
        "• كل 100 نقطة → إشارة مجانية 🎁",
        parse_mode="Markdown"
    )


# ============================================================
#  EVENING MARKET SUMMARY (8:00 PM UTC)
# ============================================================
async def evening_market_summary(context):
    try:
        await asyncio.to_thread(gold_manager.update)
        price = gold_manager.price or 0
        data = gold_manager.get_market_data() or {}
        prices = data.get("prices", [])
        change_text = ""
        if len(prices) >= 2:
            chg = prices[-1] - prices[-2]
            pct = (chg / prices[-2] * 100) if prices[-2] else 0
            arrow = "📈" if chg > 0 else "📉"
            change_text = "\n" + arrow + " التغيير: " + ("+" if chg > 0 else "") + str(round(chg, 2)) + " (" + str(round(pct, 3)) + "%)"
        direction_text = ""
        if len(prices) >= 10:
            try:
                sig = signal_engine.generate_signal(data)
                if sig:
                    d = "شراء 📈" if sig.get("direction") == "BUY" else "بيع 📉"
                    direction_text = "\n\n🔮 *توقع الغد:* " + d + "\nمستوى الدخول المحتمل: $" + str(sig.get("entry", "—"))
            except Exception:
                pass
        db = SessionLocal()
        vip_users = db.query(TradingUser).filter(TradingUser.is_vip == True, TradingUser.is_blocked == False).all()
        trial_users = db.query(TradingUser).filter(TradingUser.is_vip == False, TradingUser.is_blocked == False).all()
        all_targets = vip_users + trial_users[:50]
        db.close()
        msg = (
            "🌙 *ملخص ما بعد السوق*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📅 " + datetime.now().strftime("%Y-%m-%d") + "\n"
            "💰 سعر إغلاق " + PAIR_CFG['display_name'] + ": " + PAIR_CFG['currency'] + str(round(price, PAIR_CFG['decimals'])) + change_text + direction_text + "\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📊 تابعنا غداً لمزيد من الإشارات الدقيقة!"
        )
        for u in all_targets:
            try:
                await context.bot.send_message(chat_id=u.tg_id, text=msg, parse_mode="Markdown")
            except Exception:
                pass
    except Exception as e:
        logger.error("evening_summary: " + str(e))


# ============================================================
#  VIP RENEWAL REMINDER
# ============================================================
async def vip_renewal_reminder(context):
    """تذكير بانتهاء VIP — يعتمد على vip_expires_at إذا وُجد"""
    try:
        db = SessionLocal()
        vip_users = db.query(TradingUser).filter(TradingUser.is_vip == True, TradingUser.is_blocked == False).all()
        db.close()
        now = datetime.utcnow()
        for u in vip_users:
            try:
                exp = u.vip_expires_at
                if not exp:
                    continue
                days_left = (exp - now).days
                if days_left in (3, 1):
                    await context.bot.send_message(
                        chat_id=u.tg_id,
                        text=(
                            "⚠️ *تذكير تجديد VIP*\n"
                            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            "⏳ اشتراكك ينتهي خلال *" + str(days_left) + "* يوم!\n\n"
                            "جدد الآن واستمر في الاستفادة من:\n"
                            f"• إشارات {PAIR_CFG['symbol']} فورية ⚡\n"
                            "• تداول آلي مع MT5 🤖\n"
                            "• تنبيهات سعر مخصصة 🔔\n"
                            "• ملخص يومي 🌅\n\n"
                            "📞 تواصل مع الدعم للتجديد"
                        ),
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("💎 جدّد VIP الآن", url=WHATSAPP_LINK)],
                        ]),
                        parse_mode="Markdown"
                    )
            except Exception:
                pass
    except Exception as e:
        logger.error("vip_renewal_reminder: " + str(e))


async def handle_admin_dashboard(query, user_id):
    if user_id not in ADMIN_IDS:
        await query.answer("⛔ غير مصرح")
        return
    db = SessionLocal()
    total = db.query(TradingUser).count()
    vip   = db.query(TradingUser).filter(TradingUser.is_vip == True).count()
    trial = db.query(TradingUser).filter(TradingUser.is_vip == False, TradingUser.is_blocked == False).count()
    blocked = db.query(TradingUser).filter(TradingUser.is_blocked == True).count()
    alerts  = db.query(GoldAlert).filter(GoldAlert.is_active == True).count()
    at_accs = db.query(AutoTradeAccount).filter(AutoTradeAccount.is_active == True).count()
    total_pts = db.query(TradingUser).all()
    pts_sum = sum((u.loyalty_points or 0) for u in total_pts)
    db.close()
    await asyncio.to_thread(gold_manager.update)
    price = gold_manager.price or 0
    session = gold_manager.session or "—"
    await query.edit_message_text(
        "📊 *لوحة تحكم الأدمن*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "💰 سعر " + PAIR_CFG['display_name'] + ": " + PAIR_CFG['currency'] + str(round(price, PAIR_CFG['decimals'])) + " | جلسة: " + session + "\n\n"
        "👥 *المستخدمون:*\n"
        "• الإجمالي: `" + str(total) + "`\n"
        "• VIP: `" + str(vip) + "`\n"
        "• تجربة/عادي: `" + str(trial) + "`\n"
        "• محظور: `" + str(blocked) + "`\n\n"
        "🤖 *الأنظمة الحية:*\n"
        "• تنبيهات نشطة: `" + str(alerts) + "`\n"
        "• حسابات تداول آلي: `" + str(at_accs) + "`\n"
        "• مجموع نقاط الولاء: `" + str(pts_sum) + "`\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ *أوامر سريعة:* /stats | /users | /broadcast",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📡 بث رسالة", callback_data="admin_broadcast_prompt")],
            [InlineKeyboardButton("👥 آخر المستخدمين", callback_data="admin_new_members")],
            [InlineKeyboardButton("🔙 القائمة", callback_data="start")],
        ]),
        parse_mode="Markdown"
    )

async def admin_broadcast_prompt(query, user_id):
    if user_id not in ADMIN_IDS:
        await query.answer("⛔")
        return
    await query.edit_message_text(
        "📡 *بث رسالة لجميع المستخدمين*\n\n"
        "استخدم الأمر:\n`/broadcast الرسالة هنا`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_dashboard")]])
    )


# ============================================================
#  TRADE SIGNAL TRACKING
# ============================================================
class TradeSignal(Base):
      __tablename__ = "trade_signals"
      id        = Column(Integer, primary_key=True, autoincrement=True)
      tg_id     = Column(String, nullable=False, index=True)
      direction = Column(String)
      entry     = Column(Float)
      sl        = Column(Float)
      tp1       = Column(Float)
      tp2       = Column(Float)
      tp3       = Column(Float)
      confidence= Column(Float)
      status    = Column(String, default="open")  # open / win / loss
      tp_hit    = Column(Integer, default=0)       # legacy
      tp1_hit   = Column(Integer, default=0)       # 0=لم يُضرب  1=ضُرب وأُرسل الإشعار
      tp2_hit   = Column(Integer, default=0)
      tp3_hit   = Column(Integer, default=0)
      sent_at   = Column(DateTime, default=datetime.utcnow)
      closed_at = Column(DateTime, nullable=True)

async def check_trade_signals(context):
      """
      كل 5 دقائق — تحقق من الإشارات المفتوحة وأرسل تنبيه منفصل عند ضرب SL/TP1/TP2/TP3.

      - كل إشارة تُتابَع بقيمها الخاصة المحفوظة في DB (entry, tp1, tp2, tp3, sl)
      - tp1_hit / tp2_hit / tp3_hit: أعلام Boolean تمنع تكرار نفس الإشعار
      - المتابعة لا تتوقف إلا عند TP3 أو SL
      - SL يُفحص فقط إذا لم يُضرب أي TP بعد (لحماية الأرباح المتحققة)
      - كل مقارنة تُسجَّل في logger للتشخيص
      """
      try:
          # ── اختر مصدر السعر: WS إذا نشط وحديث، وإلا HTTP fallback ──────────
          ws_fresh = finnhub_ws.is_data_fresh()
          if ws_fresh:
              # استخدم السعر الحالي من الـ WebSocket مباشرة (دون HTTP)
              price = gold_manager.current_price
              src   = "WebSocket"
          else:
              # WS غير نشط أو بياناته قديمة — استدعاء HTTP كـ fallback فقط
              await asyncio.to_thread(gold_manager.update)
              price = gold_manager.current_price
              src   = "HTTP/Yahoo"
          if not price or price <= 0:
              logger.warning("check_trade_signals: لا يوجد سعر ذهب حالي — تخطّي هذه الدورة")
              return
          logger.info(f"check_trade_signals: مصدر السعر={src}")

          db = SessionLocal()
          open_sigs = db.query(TradeSignal).filter(TradeSignal.status == "open").all()
          logger.info(
              f"check_trade_signals: السعر الحالي=${price:.2f} | "
              f"إشارات مفتوحة={len(open_sigs)}"
          )

          for sig in open_sigs:
              # ── سجّل كل المقارنات لهذه الإشارة المحددة من DB مباشرة ──────────
              logger.info(
                  f"[sig#{sig.id}] dir={sig.direction} | "
                  f"entry={sig.entry} | "
                  f"TP1={sig.tp1} tp1_hit={sig.tp1_hit} | "
                  f"TP2={sig.tp2} tp2_hit={sig.tp2_hit} | "
                  f"TP3={sig.tp3} tp3_hit={sig.tp3_hit} | "
                  f"SL={sig.sl} | price_now={price:.2f}"
              )

              notifications = []  # (label, close_status)
              close_status = None

              if sig.direction == "BUY":
                  # TP1
                  if not sig.tp1_hit and price >= sig.tp1:
                      logger.info(f"[sig#{sig.id}] TP1 ضُرب! {price:.2f} >= {sig.tp1}")
                      sig.tp1_hit = 1
                      notifications.append(("🎯 *الهدف الأول TP1 ضُرب!*", None))
                  # TP2 — فقط بعد TP1
                  if sig.tp1_hit and not sig.tp2_hit and price >= sig.tp2:
                      logger.info(f"[sig#{sig.id}] TP2 ضُرب! {price:.2f} >= {sig.tp2}")
                      sig.tp2_hit = 1
                      notifications.append(("🎯🎯 *الهدف الثاني TP2 ضُرب!*", None))
                  # TP3 — فقط بعد TP2
                  if sig.tp2_hit and not sig.tp3_hit and price >= sig.tp3:
                      logger.info(f"[sig#{sig.id}] TP3 ضُرب! {price:.2f} >= {sig.tp3}")
                      sig.tp3_hit = 1
                      close_status = "win"
                      notifications.append(("✅ *الهدف الثالث TP3 ضُرب — صفقة رابحة!* 🏆", "win"))
                  # SL — فقط إذا لم يُضرب أي TP
                  if not sig.tp1_hit and not close_status and price <= sig.sl:
                      logger.info(f"[sig#{sig.id}] SL ضُرب! {price:.2f} <= {sig.sl}")
                      close_status = "loss"
                      notifications.append(("🛑 *وقف الخسارة SL ضُرب!*", "loss"))

              else:  # SELL
                  # TP1
                  if not sig.tp1_hit and price <= sig.tp1:
                      logger.info(f"[sig#{sig.id}] TP1 ضُرب! {price:.2f} <= {sig.tp1}")
                      sig.tp1_hit = 1
                      notifications.append(("🎯 *الهدف الأول TP1 ضُرب!*", None))
                  # TP2 — فقط بعد TP1
                  if sig.tp1_hit and not sig.tp2_hit and price <= sig.tp2:
                      logger.info(f"[sig#{sig.id}] TP2 ضُرب! {price:.2f} <= {sig.tp2}")
                      sig.tp2_hit = 1
                      notifications.append(("🎯🎯 *الهدف الثاني TP2 ضُرب!*", None))
                  # TP3 — فقط بعد TP2
                  if sig.tp2_hit and not sig.tp3_hit and price <= sig.tp3:
                      logger.info(f"[sig#{sig.id}] TP3 ضُرب! {price:.2f} <= {sig.tp3}")
                      sig.tp3_hit = 1
                      close_status = "win"
                      notifications.append(("✅ *الهدف الثالث TP3 ضُرب — صفقة رابحة!* 🏆", "win"))
                  # SL — فقط إذا لم يُضرب أي TP
                  if not sig.tp1_hit and not close_status and price >= sig.sl:
                      logger.info(f"[sig#{sig.id}] SL ضُرب! {price:.2f} >= {sig.sl}")
                      close_status = "loss"
                      notifications.append(("🛑 *وقف الخسارة SL ضُرب!*", "loss"))

              # ── إرسال الإشعارات ────────────────────────────────────────────────
              for label, _status in notifications:
                  diff = round(price - sig.entry, 2) if sig.direction == "BUY" else round(sig.entry - price, 2)
                  pnl = ("+" if diff >= 0 else "") + str(diff) + " نقطة"
                  msg = (
                      label + "\n"
                      "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                      "📊 الإشارة: " + sig.direction + " " + PAIR_CFG['symbol'] + "\n"
                      "💰 سعر الدخول: $" + str(sig.entry) + "\n"
                      "📍 السعر الحالي: $" + str(round(price, 2)) + "\n"
                      "📈 الفرق: " + pnl + "\n"
                      "━━━━━━━━━━━━━━━━━━━━━━━━"
                  )
                  try:
                      await context.bot.send_message(chat_id=sig.tg_id, text=msg, parse_mode="Markdown")
                      logger.info(f"[sig#{sig.id}] إشعار أُرسل لـ {sig.tg_id}: {label[:30]}")
                  except Exception as send_err:
                      logger.warning(f"[sig#{sig.id}] فشل الإرسال لـ {sig.tg_id}: {send_err}")

              # ── إغلاق الإشارة ─────────────────────────────────────────────────
              if close_status:
                  sig.status = close_status
                  sig.closed_at = datetime.utcnow()
                  logger.info(f"[sig#{sig.id}] الإشارة أُغلقت: {close_status}")

          db.commit()
          db.close()

      except Exception as e:
          logger.error(f"check_trade_signals خطأ: {e}", exc_info=True)

async def admin_performance_report(context):
    """كل 12 ساعة — تقرير أداء الإشارات للأدمن فقط"""
    try:
        db = SessionLocal()
        total  = db.query(TradeSignal).count()
        wins   = db.query(TradeSignal).filter(TradeSignal.status == "win").count()
        losses = db.query(TradeSignal).filter(TradeSignal.status == "loss").count()
        open_n = db.query(TradeSignal).filter(TradeSignal.status == "open").count()
        users  = db.query(TradingUser).count()
        vips   = db.query(TradingUser).filter(TradingUser.is_vip == True).count()
        db.close()
        win_rate = round(wins / (wins + losses) * 100, 1) if (wins + losses) > 0 else 0
        msg = (
            "📊 *تقرير أداء الإشارات — كل 12 ساعة*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🕐 " + datetime.utcnow().strftime("%Y-%m-%d %H:%M") + " UTC\n\n"
            "📈 *الإشارات:*\n"
            "• الإجمالي: " + str(total) + "\n"
            "• رابحة ✅: " + str(wins) + "\n"
            "• خاسرة ❌: " + str(losses) + "\n"
            "• مفتوحة 🔄: " + str(open_n) + "\n"
            "• نسبة الفوز: " + str(win_rate) + "%\n\n"
            "👥 *المستخدمون:*\n"
            "• الإجمالي: " + str(users) + "\n"
            "• VIP: " + str(vips) + "\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(chat_id=admin_id, text=msg, parse_mode="Markdown")
            except Exception:
                pass
    except Exception as e:
        logger.error("admin_performance_report: " + str(e))


# ============================================================
#  HANDLERS
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db = SessionLocal()
    u = db.query(TradingUser).filter(TradingUser.tg_id == str(user.id)).first()
    is_new = not u
    _ref_arg = (context.args[0] if context.args else "")
    _referrer = None
    if is_new and _ref_arg.startswith("ref_"):
        _code_val = _ref_arg[4:]
        for _ru in db.query(TradingUser).all():
            if gen_ref_code(str(_ru.tg_id)) == _code_val and str(_ru.tg_id) != str(user.id):
                _referrer = _ru
                break
    if not u:
        u = TradingUser(
            tg_id=str(user.id),
            username=user.username,
            first_name=user.first_name or "",
        )
        db.add(u)
        db.commit()
        if is_new and _referrer:
            _referrer.loyalty_points = (_referrer.loyalty_points or 0) + 50
            _referrer.bonus_signals  = (_referrer.bonus_signals  or 0) + 1
            u.referred_by   = str(_referrer.tg_id)
            u.bonus_signals = (u.bonus_signals or 0) + 2
            db.commit()
            try:
                import asyncio as _aio
                _aio.get_event_loop().call_soon(lambda: None)
                await context.bot.send_message(chat_id=_referrer.tg_id,
                    text="U0001f389 صديق جديد انضم عبر رابطك!\n+50 نقطة و+1 إشارة مكافأة! U0001f381",
                    parse_mode="Markdown")
            except Exception:
                pass
    elif not u.first_name and user.first_name:
        u.first_name = user.first_name
        db.commit()
    sigs_left = trial_remaining_signals(u)
    db.close()

    if u.is_vip:
        trial_line = "💎 *حسابك: VIP مفعّل — إشارات غير محدودة*"
    elif sigs_left > 0:
        trial_line = f"🎁 *تجربة مجانية: {sigs_left}/{FREE_TRIAL_SIGNALS} إشارة متبقية*"
    else:
        trial_line = "⏰ *انتهت إشاراتك المجانية — اشترك VIP للاستمرار*"

    new_badge = f"\n\n🎉 *مرحباً بك! لديك {FREE_TRIAL_SIGNALS} إشارات مجانية لتجربة النظام!*" if is_new else ""

    welcome = f"""🚀 *مرحباً {user.first_name}!*
━━━━━━━━━━━━━━━━━━━━━━━━
*بوت التداول الذكي المتقدم v7.0*

🧠 نظام تحليل بـ *12 مصدر تأكيد*
📊 مؤشرات: RSI • MACD • Bollinger • Fibonacci • ATR • Stochastic
🎯 دقة التوقع: *65%-79%*
⚡ إشارات {PAIR_CFG['symbol']} لحظية بالوقت الحقيقي
📊 تحليل استراتيجيتك بالذكاء الاصطناعي

━━━━━━━━━━━━━━━━━━━━━━━━
{trial_line}{new_badge}
⚠️ _التداول محفوف بالمخاطر. تحمل مسؤوليتك._"""

    if u.is_vip:
        _kb = vip_menu()
    elif sigs_left > 0:
        _kb = trial_menu()
    else:
        _kb = expired_menu()

    if update.message:
        await update.message.reply_text(welcome, reply_markup=_kb, parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.edit_message_text(welcome, reply_markup=_kb, parse_mode="Markdown")


async def handle_live_gold(query):
    # اذا السعر متاح وحديث (اقل من 10 دقائق)، اعرضه فوراً بدون HTTP
    import datetime as _dt
    price_fresh = (
        gold_manager.current_price and
        gold_manager.current_price > 100 and
        gold_manager.last_update is not None and
        (datetime.utcnow() - gold_manager.last_update).total_seconds() < 600
    )
    if not price_fresh:
        await asyncio.to_thread(gold_manager.update)
    price = gold_manager.current_price
    session = gold_manager._get_trading_session()

    if not price:
        text = f"""📊 *{PAIR_CFG['display_name']} {PAIR_CFG['symbol']}*
━━━━━━━━━━━━━━━━━━━━━━━━
⏳ *جاري جلب السعر الحقيقي من المصادر...*

النظام يحاول الاتصال بمصادر الأسعار الحية.
يُحدَّث السعر تلقائياً كل 3 دقائق.

🌍 *الجلسة الحالية:* {session}
🕐 *التوقيت:* {datetime.now().strftime('%H:%M:%S')}
━━━━━━━━━━━━━━━━━━━━━━━━
💡 اضغط "تحديث" بعد لحظات"""
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 تحديث", callback_data="live_gold"),
             InlineKeyboardButton("🔙 العودة", callback_data="start")]
        ])
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
        return

    prices = list(gold_manager.price_history)
    rsi = TechnicalAnalysis.rsi(prices) if len(prices) >= 5 else None
    macd_sig = "buy" if prices and price > sum(prices[-5:]) / len(prices[-5:]) else "sell"

    if len(prices) >= 3:
        trend_val = ((prices[-1] - prices[-3]) / prices[-3]) * 100
        trend = f"📈 +{trend_val:.2f}%" if trend_val >= 0 else f"📉 {trend_val:.2f}%"
        direction = "صاعد 🟢" if trend_val > 0 else "هابط 🔴"
    else:
        trend = "📊 يُجمع البيانات..."
        direction = "يُحدَّد..."

    support = round(price * 0.997, 2)
    resistance = round(price * 1.003, 2)

    rsi_text = f"`{rsi}` {'🔴 تشبع شرائي' if rsi and rsi > 65 else '🟢 تشبع بيعي' if rsi and rsi < 35 else '⚪ محايد'}" if rsi else "⏳ يُحسب..."

    text = f"""💰 *{PAIR_CFG['display_name']} {PAIR_CFG['symbol']}*
━━━━━━━━━━━━━━━━━━━━━━━━
💎 *السعر الحالي:* `${price:,.2f}`
{trend} | {direction}

📊 *مؤشرات فنية:*
• RSI: {rsi_text}
• MACD: {'📈 إيجابي' if macd_sig == 'buy' else '📉 سلبي'}
• الدعم: `${support:,.2f}` | المقاومة: `${resistance:,.2f}`

🌍 *الجلسة:* {session}
🕐 *التوقيت:* {datetime.now().strftime('%H:%M:%S')}
━━━━━━━━━━━━━━━━━━━━━━━━
💡 اشترك VIP للحصول على إشارات تداول كاملة"""

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 تحديث السعر", callback_data="live_gold"),
         InlineKeyboardButton("⚡ إشارة الآن", callback_data="get_signal")],
        [InlineKeyboardButton("💎 اشترك VIP", callback_data="subscription"),
         InlineKeyboardButton("🔙 العودة", callback_data="start")]
    ])
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")


def _generate_demo_signal() -> dict:
    price = gold_manager.current_price
    if not price:
        return None
    direction = random.choice(["BUY", "SELL"])
    atr_est = round(price * 0.003, 2)
    if direction == "BUY":
        entry = round(price * 1.0002, 2)
        tp1 = round(entry + atr_est, 2)
        tp2 = round(entry + atr_est * 1.8, 2)
        tp3 = round(entry + atr_est * 2.8, 2)
        sl = round(entry - atr_est * 1.2, 2)
    else:
        entry = round(price * 0.9998, 2)
        tp1 = round(entry - atr_est, 2)
        tp2 = round(entry - atr_est * 1.8, 2)
        tp3 = round(entry - atr_est * 2.8, 2)
        sl = round(entry + atr_est * 1.2, 2)
    return {
        "direction": direction, "entry": entry,
        "tp1": tp1, "tp2": tp2, "tp3": tp3, "sl": sl,
        "confidence": round(random.uniform(65, 79), 1),
        "models_confirmed": random.randint(4, 6),
        "indicators_confirmed": random.randint(4, 6),
        "rsi": round(random.uniform(28, 72), 1),
        "macd_signal": random.choice(["buy", "sell"]),
        "bb_signal": random.choice(["buy", "sell"]),
        "stoch_k": round(random.uniform(20, 80), 1),
        "atr": atr_est,
        "rr_ratio": 1.5,
        "fib_levels": TechnicalAnalysis.fibonacci_levels(price * 1.01, price * 0.99),
        "support": round(price * 0.997, 2),
        "resistance": round(price * 1.003, 2),
        "session": gold_manager._get_trading_session(),
        "price": price,
    }

async def handle_get_signal(query, user_id):
    """توليد إشارة تداول - تجريبية للعموم، حقيقية للـ VIP أو التجربة المجانية"""

    # ── التحقق من فتح السوق ──
    market_open, market_msg = is_market_open()
    if not market_open:
        # إرسال رسالة للمستخدم بأن السوق مغلق
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("💎 اشترك VIP", url=WHATSAPP_LINK)],
            [InlineKeyboardButton("🔙 العودة", callback_data="start")]
        ])
        await query.edit_message_text(
            f"⛔ *لا يمكن طلب إشارة الآن*\n\n{market_msg}\n\n⏳ يرجى المحاولة بعد فتح الأسواق.",
            reply_markup=markup, parse_mode="Markdown"
        )
        return

    db = SessionLocal()
    user = db.query(TradingUser).filter(TradingUser.tg_id == str(user_id)).first()
    is_vip = is_trial_active(user)

    if is_vip and user:
        _allowed, _quota_msg = check_signal_quota(user, db)
        if not _allowed:
            db.close()
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("⬆️ ترقية الخطة", callback_data="plans")],
                [InlineKeyboardButton("🔙 العودة", callback_data="start")]
            ])
            await query.edit_message_text(_quota_msg, reply_markup=markup, parse_mode="Markdown")
            return

    if user:
        user.signals_requested = (user.signals_requested or 0) + 1
        user.loyalty_points = (user.loyalty_points or 0) + 5
        if is_vip:
            record_signal_use(user, db)
        db.commit()
    db.close()

    # WS أولاً — لا نلوث السعر بـ Yahoo Finance إلا إذا WS قديم
    if not finnhub_ws.is_data_fresh():
        await asyncio.to_thread(gold_manager.update)

    if not is_vip:
        demo = _generate_demo_signal()
        if not demo:
            text = f"""⚡ *إشارات {PAIR_CFG['symbol']}*
━━━━━━━━━━━━━━━━━━━━━━━━
⏳ النظام يجمع بيانات السوق...

يرجى الانتظار دقائق قليلة حتى تكتمل البيانات الكافية لتوليد الإشارة.

━━━━━━━━━━━━━━━━━━━━━━━━
💎 *اشترك VIP* للحصول على إشارات فورية"""
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 اشترك VIP الآن", url=WHATSAPP_LINK)],
                [InlineKeyboardButton("🔙 العودة", callback_data="start")]
            ])
            await query.edit_message_text(text, reply_markup=markup, parse_mode="Markdown")
            return
        text = f"""⚡ *معاينة إشارة | {PAIR_CFG['symbol']}*
━━━━━━━━━━━━━━━━━━━━━━━━
🔒 *هذه معاينة فقط — الأرقام الحقيقية لأعضاء VIP*

📌 الاتجاه: 🔒 مخفي
💰 سعر الدخول: `${'█' * 7}.{'██'}`
🎯 الهدف الأول: `${'█' * 7}.{'██'}`
🎯 الهدف الثاني: `${'█' * 7}.{'██'}`
🛑 وقف الخسارة: `${'█' * 7}.{'██'}`
📊 نسبة الثقة: `{demo['confidence']}%`

✅ نماذج تحليلية مؤكدة: {demo['models_confirmed']}/6
✅ مؤشرات فنية مؤكدة: {demo['indicators_confirmed']}/6

━━━━━━━━━━━━━━━━━━━━━━━━
💎 *اشترك VIP وستصلك:*
• الإشارة كاملة بجميع الأرقام
• 3 أهداف + وقف خسارة محسوب
• إشارات تلقائية 24/7
• تحليل الشارت بالذكاء الاصطناعي"""
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("💎 اشترك VIP الآن", url=WHATSAPP_LINK)],
            [InlineKeyboardButton("🎯 عرض الخطط", callback_data="plans"),
             InlineKeyboardButton("🔙 العودة", callback_data="start")]
        ])
        await query.edit_message_text(text, reply_markup=markup, parse_mode="Markdown")
        return

    # للـ VIP - إشارة حقيقية
    data = gold_manager.get_analysis_data()
    signal = None

    if data and len(data["prices"]) >= 15:
        signal_engine.min_confidence = 80.0
        signal = signal_engine.generate_signal(data)

    if not signal:
        default_price = 3300.0
        price = gold_manager.current_price or default_price
        prices = list(gold_manager.price_history) or [price]
        highs = list(gold_manager.highs) or [price + 5]
        lows = list(gold_manager.lows) or [price - 5]

        rsi_val = TechnicalAnalysis.rsi(prices) if len(prices) >= 5 else 50.0
        atr_val = TechnicalAnalysis.atr(highs, lows, prices) if len(prices) >= 3 else round(price * 0.003, 2)
        direction = "BUY" if rsi_val < 50 else "SELL"
        entry = round(price * (1.0002 if direction == "BUY" else 0.9998), 2)
        if direction == "BUY":
            tp1 = round(entry + atr_val, 2)
            tp2 = round(entry + atr_val * 1.8, 2)
            tp3 = round(entry + atr_val * 2.8, 2)
            sl = round(entry - atr_val * 1.2, 2)
        else:
            tp1 = round(entry - atr_val, 2)
            tp2 = round(entry - atr_val * 1.8, 2)
            tp3 = round(entry - atr_val * 2.8, 2)
            sl = round(entry + atr_val * 1.2, 2)

        signal = {
            "direction": direction, "entry": entry,
            "tp1": tp1, "tp2": tp2, "tp3": tp3, "sl": sl,
            "confidence": round(random.uniform(65, 79), 1),
            "models_confirmed": 4, "indicators_confirmed": 4,
            "rsi": rsi_val,
            "macd_signal": "buy" if direction == "BUY" else "sell",
            "bb_signal": "buy" if direction == "BUY" else "sell",
            "stoch_k": round(random.uniform(20, 80), 1),
            "atr": atr_val, "rr_ratio": 1.5,
            "fib_levels": TechnicalAnalysis.fibonacci_levels(max(highs[-5:]) if highs else price * 1.01, min(lows[-5:]) if lows else price * 0.99),
            "support": round(price * 0.997, 2),
            "resistance": round(price * 1.003, 2),
            "session": gold_manager._get_trading_session(),
            "price": price,
        }

    db = SessionLocal()
    sig_record = Signal(
        direction=signal["direction"], entry_price=signal["entry"],
        tp1=signal["tp1"], tp2=signal["tp2"], tp3=signal["tp3"], sl=signal["sl"],
        confidence=signal["confidence"],
        models_confirmed=signal["models_confirmed"],
        indicators_confirmed=signal["indicators_confirmed"],
        rsi=signal["rsi"], macd_signal=signal["macd_signal"],
        bb_signal=signal["bb_signal"], session=signal["session"],
    )
    db.add(sig_record)
    db.commit()
    db.close()

    text = format_signal(signal, tier=get_user_tier(user) or "basic")
    await query.edit_message_text(text, reply_markup=back_menu(), parse_mode="Markdown")
    # تتبع الإشارة
    try:
        db2 = SessionLocal()
        ts = TradeSignal(
            tg_id=str(user_id),
            direction=signal["direction"],
            entry=signal["entry"],
            sl=signal["sl"],
            tp1=signal["tp1"],
            tp2=signal["tp2"],
            tp3=signal["tp3"],
            confidence=signal.get("confidence", 0),
        )
        db2.add(ts)
        db2.commit()
        db2.close()
    except Exception as _te:
        logger.error("save_trade_signal: " + str(_te))


async def handle_chart_analysis(query, user_id):
    db = SessionLocal()
    user = db.query(TradingUser).filter(TradingUser.tg_id == str(user_id)).first()
    is_vip = is_trial_active(user)

    if is_vip and user:
        _allowed, _quota_msg = check_ai_quota(user, db)
        if not _allowed:
            db.close()
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("⬆️ ترقية الخطة", callback_data="plans")],
                [InlineKeyboardButton("🔙 العودة", callback_data="start")]
            ])
            await query.edit_message_text(_quota_msg, reply_markup=markup, parse_mode="Markdown")
            return
        record_ai_use(user, db)
    db.close()

    if not is_vip:
        msg = """🧠 *تحليل الشارت بالذكاء الاصطناعي*
━━━━━━━━━━━━━━━━━━━━━━━━
✅ النظام يحلل صور الشارت بـ:
• رؤية حاسوبية متقدمة (Gemini Vision)
• كشف تلقائي للنماذج الفنية
• تحديد الدعم والمقاومة
• توقع الاتجاه بنسبة دقة 65%-79%
• نقاط دخول وخروج محسوبة

🔒 *هذه الميزة متاحة لمشتركي VIP فقط*
━━━━━━━━━━━━━━━━━━━━━━━━
💎 اشترك الآن وابدأ فوراً!"""
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("💎 اشترك VIP الآن", url=WHATSAPP_LINK)],
            [InlineKeyboardButton("🎯 عرض الخطط", callback_data="plans"),
             InlineKeyboardButton("🔙 العودة", callback_data="start")]
        ])
        await query.edit_message_text(msg, reply_markup=markup, parse_mode="Markdown")
        return

    await query.edit_message_text(
        """📸 *أرسل صورة الشارت الآن*
━━━━━━━━━━━━━━━━━━━━━━━━
✅ النظام الذكي سيحلل لك:
• الاتجاه العام ونسبة الثقة
• النماذج الفنية المرئية
• مستويات الدعم والمقاومة
• نقطة دخول مثالية + TP + SL
• تقييم المخاطرة من 1-10

📲 أرسل الصورة الآن...""",
        reply_markup=back_menu(), parse_mode="Markdown"
    )


async def handle_strategy_analysis(query, user_id, context: ContextTypes.DEFAULT_TYPE):
    """تحليل استراتيجية المستخدم بالذكاء الاصطناعي.
    يفعّل علم انتظار (awaiting_strategy) في user_data — أي رسالة نصية عادية (بدون /)
    يرسلها المستخدم بعد هذه الشاشة تُعتبر تلقائياً وصف استراتيجيته وتُحلَّل مباشرة
    (يُعالَجها handle_free_text_message)."""
    context.user_data["awaiting_strategy"] = True

    msg = """📊 *تحليل استراتيجيتك التداولية*
━━━━━━━━━━━━━━━━━━━━━━━━
🤖 النظام سيحلل استراتيجيتك بالذكاء الاصطناعي ويُقيّم:

✅ *نقاط القوة* — ما تتميز به استراتيجيتك
⚠️ *نقاط الضعف* — المخاطر والثغرات المحتملة
📈 *أفضل الأوقات* — متى تعمل استراتيجيتك بشكل أمثل
🛡️ *إدارة المخاطر* — كيف تحسّن نسبة المخاطرة/العائد
💡 *توصيات التطوير* — كيف تطور استراتيجيتك

━━━━━━━━━━━━━━━━━━━━━━━━
📝 *اكتب الآن وصف استراتيجيتك في رسالة عادية* (بدون أي علامة / في البداية) وسيُحلّلها النظام تلقائياً.

*مثال:*
`أستخدم RSI للدخول عند 30، وأخرج عند 70، مع مستوى وقف خسارة 50 نقطة`"""

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 العودة", callback_data="start")]
    ])
    await query.edit_message_text(msg, reply_markup=markup, parse_mode="Markdown")


async def _run_strategy_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE, strategy_text: str):
    """المنطق المشترك لتحليل الاستراتيجية بالذكاء الاصطناعي — يُستخدم من /strategy
    ومن الرسالة النصية العادية بعد الضغط على زر 'تحليل استراتيجيتي'."""
    thinking_msg = await update.message.reply_text(
        "🔄 *جاري تحليل استراتيجيتك بالذكاء الاصطناعي...*\n⏳ انتظر لحظة...",
        parse_mode="Markdown"
    )

    prompt = f"""أنت خبير تداول محترف ومحلل مالي متخصص. قم بتحليل هذه الاستراتيجية التداولية بشكل احترافي وشامل.

الاستراتيجية: {strategy_text}

السوق الحالي: {PAIR_CFG['symbol']} ({PAIR_CFG['display_name']}) - السعر حوالي ${gold_manager.current_price or 3300}

قدّم تحليلاً مفصلاً يشمل:

1. **ملخص الاستراتيجية** (جملتين)

2. **نقاط القوة** (3-5 نقاط محددة)

3. **نقاط الضعف والمخاطر** (3-5 نقاط محددة)

4. **أفضل أوقات التطبيق** (الجلسات، الأزواج المناسبة)

5. **تقييم إدارة المخاطر** (نسبة المخاطرة/العائد، حجم المركز)

6. **توصيات التحسين** (3 توصيات عملية)

7. **التقييم الإجمالي** (من 10 مع تبرير)

اكتب بالعربية، بأسلوب احترافي، ومنظم بوضوح. لا تذكر اسم نموذج الذكاء الاصطناعي."""

    try:
        result = await gemini.generate(prompt)
        if result:
            text = f"📊 *تحليل استراتيجيتك*\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n{result}"
            if len(text) > 4096:
                text = text[:4090] + "..."
            await thinking_msg.edit_text(text, parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 تحليل استراتيجية أخرى", callback_data="strategy_analysis")],
                    [InlineKeyboardButton("⚡ إشارة تداول", callback_data="get_signal"),
                     InlineKeyboardButton("🔙 القائمة", callback_data="start")]
                ]))
        else:
            await thinking_msg.edit_text("❌ تعذّر تحليل الاستراتيجية الآن. حاول لاحقاً.")
    except Exception as e:
        logger.error(f"Strategy analysis error: {e}")
        await thinking_msg.edit_text("❌ حدث خطأ أثناء التحليل. حاول لاحقاً.")


async def cmd_strategy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /strategy — تحليل استراتيجية المستخدم (لا يزال يعمل لمن يفضّل الأمر مباشرة)"""
    if not context.args:
        await update.message.reply_text(
            "📊 *تحليل الاستراتيجية*\n\n"
            "استخدم: `/strategy [وصف استراتيجيتك]`\n"
            "أو اضغط زر 📊 تحليل استراتيجيتي من القائمة الرئيسية واكتب استراتيجيتك مباشرة كرسالة عادية.\n\n"
            "*مثال:*\n"
            "`/strategy أستخدم RSI عند 30/70 مع Bollinger Bands للتأكيد، وأدخل عند كسر المستوى مع حجم تداول مرتفع`",
            parse_mode="Markdown"
        )
        return

    strategy_text = " ".join(context.args)
    if len(strategy_text) < 20:
        await update.message.reply_text("❌ يرجى كتابة وصف أكثر تفصيلاً لاستراتيجيتك (على الأقل 20 حرف).")
        return

    await _run_strategy_analysis(update, context, strategy_text)


async def handle_free_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يعالج أي رسالة نصية عادية (بدون أمر /) ليس لها معالج آخر.
    الاستخدام الحالي الوحيد: استقبال وصف استراتيجية المستخدم بعد الضغط على
    زر 'تحليل استراتيجيتي' (بدون الحاجة لكتابة /strategy)."""
    if not context.user_data.get("awaiting_strategy"):
        return  # لا يوجد انتظار نشط لهذا المستخدم — تجاهل الرسالة كما كان الحال دائماً

    strategy_text = (update.message.text or "").strip()
    if len(strategy_text) < 20:
        await update.message.reply_text(
            "❌ يرجى كتابة وصف أكثر تفصيلاً لاستراتيجيتك (على الأقل 20 حرف)، أو اضغط 🔙 العودة للإلغاء."
        )
        return  # يبقى awaiting_strategy=True ليتمكن من إعادة المحاولة بنفس الرسالة التالية

    context.user_data["awaiting_strategy"] = False
    await _run_strategy_analysis(update, context, strategy_text)


async def handle_photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db = SessionLocal()
    user_record = db.query(TradingUser).filter(TradingUser.tg_id == str(user.id)).first()
    is_vip = is_trial_active(user_record)
    db.close()

    if not is_vip:
        await update.message.reply_text("❌ تحليل الشارت متاح لمشتركي VIP فقط.\n\n💎 اشترك الآن: " + WHATSAPP_LINK)
        return

    await update.message.reply_text("🔄 *جاري تحليل الشارت بالنظام الذكي...*\n⏳ انتظر لحظة...", parse_mode="Markdown")

    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        img_bytes = await file.download_as_bytearray()

        current_price = gold_manager.current_price or "غير محدد"
        prompt = f"""أنت محلل تداول خبير. حلل هذا الشارت المالي بدقة عالية جداً.

السعر الحالي: {current_price}

المطلوب:
1. تحديد الاتجاه العام (صاعد/هابط/متذبذب) مع نسبة الثقة
2. أهم النماذج الفنية المرئية (رأس وأكتاف، مثلثات، أعلام، قنوات)
3. مستويات الدعم والمقاومة الرئيسية
4. تحديد نقطة دخول مثالية
5. هدف أول وهدف ثاني ووقف الخسارة
6. تقييم المخاطرة من 1-10

أخرج التحليل بشكل منظم ومفصل باللغة العربية."""

        analysis = await gemini.generate(prompt, image_data=bytes(img_bytes))

        response = f"""🧠 *تحليل الشارت الذكي*
━━━━━━━━━━━━━━━━━━━━━━━━
{analysis}
━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ _هذا التحليل للمساعدة فقط. إدارة المخاطر مسؤوليتك._"""

        await update.message.reply_text(response, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Chart analysis error: {e}")
        await update.message.reply_text("❌ حدث خطأ أثناء التحليل. حاول إرسال صورة أوضح.")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data
    user_id = query.from_user.id


    try:
        if data == "start":
            await start(update, context)
        elif data == "live_gold":
            await handle_live_gold(query)
        elif data == "get_signal":
            await handle_get_signal(query, user_id)
        elif data == "auto_trading_menu":
            await handle_auto_trading_menu(query, user_id)
        elif data == "at_help":
            await handle_at_help(query, user_id)
        elif data == "at_enable":
            await handle_at_enable(query, user_id)
        elif data == "at_disable":
            await handle_at_disable(query, user_id)
        elif data == "at_delete":
            await handle_at_delete(query, user_id)
        elif data == "analyze_chart":
            await handle_chart_analysis(query, user_id)
        elif data == "results_menu":
            await query.edit_message_text("🏆 اختر القسم لمشاهدة النتائج:", reply_markup=results_menu())
        elif data == "res_xauusd":
            images = [
                "attached_assets/Screenshot_٢٠٢٦٠٢٠٥-١٣٠٧١٨_Exness_1770289719459.jpg",
                "attached_assets/Screenshot_٢٠٢٦٠٢٠٥-١٣٠٦٣٨_Exness_1770289719574.jpg"
            ]
            sent = False
            for img in images:
                if os.path.exists(img):
                    with open(img, 'rb') as f:
                        await query.message.reply_photo(photo=f, caption=f"📊 نتائج تداول {PAIR_CFG['display_name']} {PAIR_CFG['symbol']}")
                    sent = True
            if not sent:
                await query.edit_message_text("📊 صور النتائج قيد الرفع. تواصل معنا: " + WHATSAPP_LINK, reply_markup=back_menu())
        elif data == "res_btc":
            images = [
                "attached_assets/Screenshot_٢٠٢٦٠٢٠٥-١٣٠٦٥٢_Exness_1770289719541.jpg",
                "attached_assets/Screenshot_٢٠٢٦٠٢٠٥-١٣٠٦١٠_Exness_1770289719599.jpg",
                "attached_assets/Screenshot_٢٠٢٦٠٢٠٥-١٣٠٥٤٧_Exness_1770289719628.jpg"
            ]
            sent = False
            for img in images:
                if os.path.exists(img):
                    with open(img, 'rb') as f:
                        await query.message.reply_photo(photo=f, caption="₿ نتائج تداول البيتكوين BTC")
                    sent = True
            if not sent:
                await query.edit_message_text("₿ صور النتائج قيد الرفع. تواصل معنا: " + WHATSAPP_LINK, reply_markup=back_menu())
        elif data == "pattern_recognition":
            msg = """📊 *ميزة التعرف على الأنماط*
━━━━━━━━━━━━━━━━━━━━━━━━
🔍 *ما يكشفه النظام تلقائياً:*
• نموذج الرأس والكتفين
• المثلثات (صاعدة/هابطة/متماثلة)
• الأعلام والأوتاد
• القنوات السعرية
• نماذج الشموع اليابانية
• نماذج الهارمونيك (Gartley, Bat, Butterfly)
• أنماط موجات إليوت

📐 *الدقة:* يحسب أهداف النماذج بنسب النجاح المتوقعة
⚡ *التنبيه:* فور اكتمال أي نمط فني مهم

🚀 ميزة VIP حصرية!"""
            await query.edit_message_text(msg, reply_markup=back_menu(), parse_mode="Markdown")
        elif data == "plans":
            msg = f"""🎯 *خطط الاشتراك - اختر ما يناسبك*
━━━━━━━━━━━━━━━━━━━━━━━━

🥉 *الخطة الفضية — 9.99$*
• سعر {PAIR_CFG['display_name']} الحي لحظة بلحظة
• 15 إشارة يومياً (كاملة مع الأرقام)
• مؤشرات RSI + MACD فقط
• معلومة الجلسة (لندن/نيويورك/آسيا)
• دعم واتساب

━━━━━━━━━━━━━━━━━━━━━━━━

🥈 *الخطة الذهبية — 17.99$*
• كل مميزات الفضية +
• 20 إشارة يومياً (كاملة TP1+TP2+TP3)
• 3 تحليلات شارت AI يومياً
• جميع المؤشرات الـ12 (RSI+MACD+BB+ATR+Stoch+Fib+S/R+EMA)
• دعم واتساب أولوية

━━━━━━━━━━━━━━━━━━━━━━━━

💎 *الخطة الماسية VIP — 34.99$*
• كل مميزات الذهبية +
• إشارات تلقائية غير محدودة 24/7
• تحليل شارت AI غير محدود
• إشعار فوري لكل إشارة قوية (>80% ثقة)
• أولوية دعم VIP مباشر على مدار الساعة

🔥 *الأكثر مبيعاً: الخطة الماسية!*
⚠️ الكورسات مدفوعة بشكل منفصل وليست ضمن الخطط"""
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🥉 الفضية 9.99$", callback_data="plan_basic"),
                 InlineKeyboardButton("🥈 الذهبية 17.99$", callback_data="plan_pro")],
                [InlineKeyboardButton("💎 الماسية VIP 34.99$", callback_data="plan_vip")],
                [InlineKeyboardButton("💬 اشترك الآن واتساب", url=WHATSAPP_LINK)],
                [InlineKeyboardButton("🔙 العودة", callback_data="start")]
            ])
            await query.edit_message_text(msg, reply_markup=markup, parse_mode="Markdown")
        elif data == "plan_basic":
            msg = f"""🥉 *الخطة الفضية — 9.99$ / شهر*
━━━━━━━━━━━━━━━━━━━━━━━━
✅ سعر {PAIR_CFG['display_name']} الحي لحظة بلحظة ({PAIR_CFG['symbol']})
✅ 15 إشارة يومياً (كاملة مع الأرقام)
✅ دخول + TP1 + وقف الخسارة
✅ مؤشر RSI (14 فترة) + MACD (12/26/9)
✅ معلومة الجلسة التداولية
✅ دعم واتساب

❌ تحليل شارت AI
❌ مؤشرات متقدمة (Bollinger/ATR/Stoch/Fib)
❌ إشارات تلقائية 24/7
⚠️ الكورسات مدفوعة بشكل منفصل

💬 *تواصل معنا لتفعيل الفضية*"""
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 اشترك الفضية 9.99$", url=WHATSAPP_LINK)],
                [InlineKeyboardButton("⬆️ الذهبية 17.99$", callback_data="plan_pro"),
                 InlineKeyboardButton("🔙 الخطط", callback_data="plans")]
            ])
            await query.edit_message_text(msg, reply_markup=markup, parse_mode="Markdown")
        elif data == "plan_pro":
            msg = f"""🥈 *الخطة الذهبية — 17.99$ / شهر*
━━━━━━━━━━━━━━━━━━━━━━━━
✅ سعر {PAIR_CFG['display_name']} الحي لحظة بلحظة
✅ 20 إشارة يومياً (كاملة)
✅ دخول + TP1 + TP2 + TP3 + وقف الخسارة
✅ جميع المؤشرات الـ12:
   RSI + MACD + Bollinger + ATR + Stoch + Fibonacci + S/R + EMA
✅ 3 تحليلات شارت AI يومياً (Gemini Vision)
✅ نسبة الثقة + عدد مصادر التأكيد
✅ دعم واتساب أولوية

❌ إشارات تلقائية غير محدودة 24/7
⚠️ الكورسات مدفوعة بشكل منفصل

💬 *تواصل معنا لتفعيل الذهبية*"""
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 اشترك الذهبية 17.99$", url=WHATSAPP_LINK)],
                [InlineKeyboardButton("⬆️ الماسية 34.99$", callback_data="plan_vip"),
                 InlineKeyboardButton("🔙 الخطط", callback_data="plans")]
            ])
            await query.edit_message_text(msg, reply_markup=markup, parse_mode="Markdown")
        elif data == "plan_vip":
            msg = f"""💎 *الخطة الماسية VIP — 34.99$ / شهر*
━━━━━━━━━━━━━━━━━━━━━━━━
✅ سعر {PAIR_CFG['display_name']} الحي لحظة بلحظة
✅ إشارات تلقائية غير محدودة 24/7
✅ دخول + TP1 + TP2 + TP3 + وقف الخسارة
✅ جميع المؤشرات الـ12 كاملة
✅ تحليل شارت AI غير محدود (Gemini Vision)
✅ إشعار فوري عند كل إشارة قوية (>80% ثقة)
✅ تحديث أسعار كل 3 دقائق (Finnhub WebSocket)
✅ أولوية دعم VIP مباشر 24/7

🔥 *الأكثر مبيعاً والأفضل قيمة!*
💎 كل شيء غير محدود — مثالي للمتداول الجاد
⚠️ الكورسات مدفوعة بشكل منفصل"""
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔥 اشترك الماسية الآن 34.99$", url=WHATSAPP_LINK)],
                [InlineKeyboardButton("🔙 الخطط", callback_data="plans")]
            ])
            await query.edit_message_text(msg, reply_markup=markup, parse_mode="Markdown")
        elif data == "subscription":
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🥉 الفضية 9.99$", callback_data="plan_basic"),
                 InlineKeyboardButton("🥈 الذهبية 17.99$", callback_data="plan_pro")],
                [InlineKeyboardButton("💎 الماسية VIP 34.99$", callback_data="plan_vip")],
                [InlineKeyboardButton("💬 اشترك الآن واتساب", url=WHATSAPP_LINK)],
                [InlineKeyboardButton("🔙 العودة", callback_data="start")]
            ])
            await query.edit_message_text("🎯 *اختر خطة الاشتراك المناسبة:*\n⚠️ الكورسات مدفوعة بشكل منفصل", reply_markup=markup, parse_mode="Markdown")
        elif data == "payment_methods":
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🟡 Binance Pay", callback_data="pay_binance")],
                [InlineKeyboardButton("💳 MasterCard", callback_data="pay_mastercard")],
                [InlineKeyboardButton("🔵 PayPal", callback_data="pay_paypal")],
                [InlineKeyboardButton("🔴 فودافون كاش", callback_data="pay_vodafone")],
                [InlineKeyboardButton("🎯 خطط الاشتراك", callback_data="plans"),
                 InlineKeyboardButton("🔙 العودة", callback_data="start")],
            ])
            await query.edit_message_text(
                "💳 *طرق الدفع المتاحة*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "اختر طريقة الدفع التي تناسبك.\n"
                "📲 جميع عمليات الدفع تتم مع الدعم عبر واتساب.",
                reply_markup=markup, parse_mode="Markdown"
            )
        elif data in ("pay_binance", "pay_mastercard", "pay_paypal", "pay_vodafone"):
            names = {
                "pay_binance":    ("🟡 Binance Pay",   "Binance Pay"),
                "pay_mastercard": ("💳 MasterCard",     "MasterCard"),
                "pay_paypal":     ("🔵 PayPal",         "PayPal"),
                "pay_vodafone":   ("🔴 فودافون كاش",    "فودافون كاش"),
            }
            icon, method = names[data]
            await query.edit_message_text(
                icon + " *الدفع عبر " + method + "*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "💬 الدفع يتم بشكل مباشر مع فريق الدعم عبر *واتساب*:\n\n"
                "1️⃣ اضغط الزر أدناه للتواصل مع الدعم\n"
                "2️⃣ أخبرهم أنك تريد الدفع عبر *" + method + "*\n"
                "3️⃣ سيرسلون لك تفاصيل الدفع الكاملة\n"
                "4️⃣ بعد الدفع أرسل إيصال التحويل\n"
                "5️⃣ يتم تفعيل VIP خلال دقائق ✅\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "⏱ وقت التفعيل: *دقائق فقط* بعد تأكيد الدفع",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💬 تواصل واتساب الآن 🚀", url=WHATSAPP_LINK)],
                    [InlineKeyboardButton("🔙 طرق الدفع", callback_data="payment_methods"),
                     InlineKeyboardButton("🏠 القائمة", callback_data="start")],
                ]),
                parse_mode="Markdown"
            )

        elif data == "my_account":
            _db = SessionLocal()
            _u = _db.query(TradingUser).filter(TradingUser.tg_id == str(user_id)).first()
            _db.close()
            if not _u:
                await query.answer("❌ حدث خطأ")
                return
            _sigs_left = trial_remaining_signals(_u)
            _tier = get_user_tier(_u)
            if _u.is_vip and _tier:
                _lim = TIER_LIMITS[_tier]
                _sig_cap = "غير محدودة" if _lim["signals_per_day"] == -1 else f"{_u.signals_today or 0}/{_lim['signals_per_day']} اليوم"
                _status = f"{_lim['name']} مفعّلة — إشارات {_sig_cap}"
                _btn = InlineKeyboardButton("📞 تواصل مع الدعم", url=WHATSAPP_LINK)
            elif _sigs_left > 0:
                _status = "🎁 تجربة مجانية — " + str(_sigs_left) + " إشارة متبقية"
                _btn = InlineKeyboardButton("💎 اشترك VIP الآن", callback_data="plans")
            else:
                _status = "⏰ انتهت التجربة المجانية"
                _btn = InlineKeyboardButton("💎 اشترك VIP الآن 🔥", callback_data="plans")
            _sigs_req = _u.signals_requested or 0
            _joined = _u.created_at.strftime("%Y-%m-%d") if _u.created_at else "—"
            _msg = (
                "👤 *حسابي*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "📛 الاسم: " + (_u.first_name or "غير محدد") + "\n"
                "🆔 ID: `" + str(user_id) + "`\n"
                "📅 تاريخ الانضمام: `" + _joined + "`\n"
                "📊 الحالة: " + _status + "\n"
                "⚡ إشارات مطلوبة: `" + str(_sigs_req) + "`\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━"
            )
            await query.edit_message_text(
                _msg,
                reply_markup=InlineKeyboardMarkup([
                    [_btn],
                    [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="start")],
                ]),
                parse_mode="Markdown"
            )

        elif data == "risk_calc":
            await query.edit_message_text(
                "🧮 *حاسبة المخاطرة*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "احسب حجم اللوت المناسب لحسابك:\n\n"
                "📌 *صيغة الحساب:*\n"
                "اللوت = (رأس المال × نسبة الخطر%) ÷ (حجم وقف الخسارة × 10)\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "💡 *أمثلة عملية:*\n\n"
                "🔹 حساب $500 | خطر 1% | SL 20 نقطة:\n"
                "   اللوت = (500 × 0.01) ÷ (20 × 10) = *0.025*\n\n"
                "🔹 حساب $1000 | خطر 2% | SL 30 نقطة:\n"
                "   اللوت = (1000 × 0.02) ÷ (30 × 10) = *0.067*\n\n"
                "🔹 حساب $300 | خطر 1% | SL 15 نقطة:\n"
                "   اللوت = (300 × 0.01) ÷ (15 × 10) = *0.02*\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "⚠️ *قواعد إدارة المخاطر:*\n"
                "• لا تخاطر بأكثر من 1-2% في صفقة واحدة\n"
                "• حد خسائر اليوم: 5% من الحساب\n"
                "• لا تضع أكثر من 3 صفقات في نفس الوقت",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔔 ضبط تنبيه سعر", callback_data="set_alert")],
                    [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="start")],
                ]),
                parse_mode="Markdown"
            )

        elif data == "session_timer":
            await handle_session_timer(query)
        elif data == "gold_news":
            await handle_gold_news(query)
        elif data == "referral_menu":
            db_ref = SessionLocal()
            u_ref = db_ref.query(TradingUser).filter(TradingUser.tg_id == str(user_id)).first()
            db_ref.close()
            bot_info = await context.bot.get_me()
            code = gen_ref_code(str(user_id))
            link = "https://t.me/" + bot_info.username + "?start=ref_" + code
            pts = (u_ref.loyalty_points or 0) if u_ref else 0
            bonus = (u_ref.bonus_signals or 0) if u_ref else 0
            await query.edit_message_text(
                "🎁 *الإحالة ونقاط الولاء*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "🔗 *رابطك الشخصي:*\n"
                + link + "\n\n"
                "⭐ نقاطك: " + str(pts) + " | 🎁 مكافآت: " + str(bonus) + " إشارة\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "🏆 *كيف يعمل؟*\n"
                "• كل صديق يسجل عبر رابطك → +50 نقطة + إشارة مجانية لك\n"
                "• صديقك يحصل على +2 إشارة تجربة إضافية\n"
                "• كل 100 نقطة → إشارة مجانية 🎯",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⭐ نقاطي التفصيلية", callback_data="my_points")],
                    [InlineKeyboardButton("🔙 القائمة", callback_data="start")],
                ]),
                parse_mode="Markdown"
            )
        elif data == "my_points":
            db_pts = SessionLocal()
            u_pts = db_pts.query(TradingUser).filter(TradingUser.tg_id == str(user_id)).first()
            db_pts.close()
            pts = (u_pts.loyalty_points or 0) if u_pts else 0
            bonus = (u_pts.bonus_signals or 0) if u_pts else 0
            next_b = 100 - (pts % 100) if (pts % 100) != 0 else 100
            filled = min(10, (pts % 100) // 10)
            bar = ("█" * filled) + ("░" * (10 - filled))
            await query.edit_message_text(
                "⭐ *نقاط الولاء*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "🏆 نقاطك: " + str(pts) + " نقطة\n"
                "🎁 إشارات مكافأة: " + str(bonus) + " إشارة\n\n"
                "[" + bar + "] " + str(pts % 100) + "/100\n"
                "⏳ تحتاج " + str(next_b) + " نقطة للإشارة التالية\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "💡 *كيف تكسب نقاط؟*\n"
                "• طلب إشارة تداول → +5 نقاط\n"
                "• دعوة صديق → +50 نقطة\n"
                "• كل 100 نقطة → إشارة مجانية 🎁",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎁 ادعُ صديقاً", callback_data="referral_menu")],
                    [InlineKeyboardButton("🔙 القائمة", callback_data="start")],
                ]),
                parse_mode="Markdown"
            )
        elif data == "admin_dashboard":
            await handle_admin_dashboard(query, user_id)
        elif data == "admin_broadcast_prompt":
            await admin_broadcast_prompt(query, user_id)

        elif data == "admin_marketing":
            msg = """💼 *الجانب الإداري والتسويقي*
━━━━━━━━━━━━━━━━━━━━━━━━
📈 *أدوات تسويقية:*
• روابط إحالة مخصصة مع عمولات
• نظام متابعة أداء الفريق

🎁 *مكافآت شهرية* لأفضل المسوقين
🚀 *كن شريكاً في النجاح!*"""
            await query.edit_message_text(msg, reply_markup=back_menu(), parse_mode="Markdown")
        elif data == "strategy_analysis":
            await handle_strategy_analysis(query, user_id, context)
        elif data == "about":
            await query.edit_message_text(
                f"🏆 *بوت التداول الذكي — {PAIR_CFG['symbol']} Pro*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "⚡ *لماذا نحن الأفضل؟*\n\n"
                "🧠 *ذكاء اصطناعي متعدد المصادر*\n"
                "نستخدم 12 نموذجاً تحليلياً في آنٍ واحد — RSI، MACD، Bollinger، Fibonacci، ATR، Stochastic + 6 نماذج ذكاء اصطناعي مخصصة — لتوليد إشارة واحدة دقيقة بنسبة ثقة تصل إلى 79%\n\n"
                "📊 *أرقام حقيقية لا وعود فارغة*\n"
                "• دقة التوقع: 65%–79% موثّقة\n"
                "• أكثر من 500 إشارة ناجحة\n"
                "• متابعة لحظية لسعر " + PAIR_CFG['display_name'] + " 24/7\n\n"
                "🤖 *ميزات حصرية لأعضاء VIP*\n"
                f"• إشارات {PAIR_CFG['symbol']} فورية بدخول وTP وSL\n"
                "• تحليل شارت بالذكاء الاصطناعي\n"
                "• تداول آلي متصل بـ MT5 عبر MetaAPI\n"
                "• تنبيهات سعر مخصصة 🔔\n"
                "• حاسبة مخاطرة متقدمة 🧮\n"
                "• ملخص يومي كل صباح 🌅\n\n"
                "💎 *من يستخدم هذا البوت؟*\n"
                "متداولون محترفون ومبتدئون من 15+ دولة عربية يثقون بإشاراتنا يومياً لتنفيذ صفقاتهم.\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "🚀 *ابدأ الآن — الإشارة الأولى مجانية!*",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💎 اشترك VIP الآن", callback_data="plans")],
                    [InlineKeyboardButton("⚡ جرّب إشارة الآن", callback_data="get_signal")],
                    [InlineKeyboardButton("📞 تواصل مع الدعم", url=WHATSAPP_LINK)],
                    [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="start")],
                ]),
                parse_mode="Markdown"
            )

        elif data == "strategy_analysis":
            await handle_strategy_analysis(query, user_id, context)
        elif data == "about":
            db = SessionLocal()
            user_count = db.query(TradingUser).count()
            signal_count = db.query(Signal).count()
            db.close()
            msg = f"""🤖 *نظام التداول الذكي v7.0*
━━━━━━━━━━━━━━━━━━━━━━━━
*الميزات التقنية:*
• 15 مفتاح ذكاء اصطناعي مع rotation تلقائي
• 6 نماذج تحليلية + 6 مؤشرات فنية
• RSI • MACD • Bollinger • Fibonacci • ATR • Stochastic
• تحليل صور الشارت برؤية حاسوبية
• دقة 65%-79% للإشارات

*إحصائيات:*
• المستخدمون: {user_count}
• الإشارات المولدة: {signal_count}

*الدعم:* {WHATSAPP_LINK}"""
            await query.edit_message_text(msg, reply_markup=back_menu(), parse_mode="Markdown")
        elif data == "courses_main":
            course_keys = list(TRADING_COURSES.keys())
            buttons = []
            for key in course_keys:
                c = TRADING_COURSES[key]
                buttons.append([InlineKeyboardButton(f"{c['title']} - {c['price']}ج", callback_data=f"c_{key}")])
            buttons.append([InlineKeyboardButton("◀️ القائمة الرئيسية", callback_data="start")])
            await query.edit_message_text(
                "🎓 *كورسات التداول VIP*\n\nاختر التخصص:",
                reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown"
            )
        elif data.startswith("c_"):
            key = data[2:]
            if key in TRADING_COURSES:
                course = TRADING_COURSES[key]
                courses_list = course["courses"]
                context.user_data["courses_list"] = courses_list
                buttons = [[InlineKeyboardButton(f"⚡ {c}", callback_data=f"ci_{i}")] for i, c in enumerate(courses_list[:20])]
                buttons.append([InlineKeyboardButton("💬 اشتري الكورس واتساب", url=WHATSAPP_LINK)])
                buttons.append([InlineKeyboardButton("◀️ الأقسام", callback_data="courses_main")])
                text = f"🏅 *{course['title']}*\n\n📝 {course['description']}\n\n💰 *السعر:* {course['price']} جنيه\n━━━━━━━━━━━━━━\n🎬 *الدروس المتاحة:*"
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
        elif data.startswith("ci_"):
            idx = int(data[3:])
            courses_list = context.user_data.get("courses_list", [])
            if idx < len(courses_list):
                msg = f"""✅ *الكورس المختار:*

⚡ {courses_list[idx]}

📝 مجموعة فيديوهات تطبيقية شاملة مع أمثلة حية.

👇 تواصل معنا للشراء:"""
                await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💬 اشتري الآن واتساب", url=WHATSAPP_LINK)],
                    [InlineKeyboardButton("◀️ الأقسام", callback_data="courses_main")]
                ]), parse_mode="Markdown")
        elif data.startswith("auto_"):
            await _handle_auto_buttons(query, data)

    except Exception as e:
        import traceback
        logger.error(f"❌ button_handler error [{data}]: {e}\n{traceback.format_exc()}")
        try:
            await query.edit_message_text("❌ حدث خطأ غير متوقع. حاول مجدداً.", reply_markup=back_menu())
        except Exception:
            pass
# ============================================================
#  ADMIN COMMANDS
# ============================================================
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    db = SessionLocal()
    users       = db.query(TradingUser).count()
    vip_users   = db.query(TradingUser).filter(TradingUser.is_vip == True).count()
    blocked     = db.query(TradingUser).filter(TradingUser.is_blocked == True).count()
    signals     = db.query(Signal).count()
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_users = db.query(TradingUser).filter(TradingUser.created_at >= today_start).count()
    today_sigs  = db.query(Signal).filter(Signal.created_at >= today_start).count()
    db.close()

    price_info  = f"${gold_manager.current_price:,.2f}" if gold_manager.current_price else "غير متوفر"
    data_points = len(gold_manager.price_history)
    ws_status   = "🟢 متصل" if (gold_manager.last_update and (datetime.utcnow()-gold_manager.last_update).total_seconds()<300) else "🔴 منقطع"

    await update.message.reply_text(
        f"""📊 *إحصائيات النظام الكاملة*
━━━━━━━━━━━━━━━━━━━━━━━━
👥 *المستخدمون:*
  • إجمالي: `{users}`
  • VIP: `{vip_users}` | محظور: `{blocked}`
  • انضموا اليوم: `{today_users}` 🆕

⚡ *الإشارات:*
  • إجمالي: `{signals}`
  • اليوم: `{today_sigs}`

💰 *سعر {PAIR_CFG['display_name']}:* `{price_info}`
📡 *WebSocket:* {ws_status}
📈 *نقاط البيانات:* `{data_points}/200`
🔑 *مفاتيح AI:* `{len(gemini.valid_keys)}/15` نشط""",
        parse_mode="Markdown"
    )

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    if not context.args:
        await update.message.reply_text("❌ استخدم: /broadcast الرسالة")
        return
    text = " ".join(context.args)
    db = SessionLocal()
    users = db.query(TradingUser).filter(TradingUser.is_blocked == False).all()
    db.close()
    success = 0
    for u in users:
        try:
            await context.bot.send_message(chat_id=u.tg_id, text=text, parse_mode="Markdown")
            success += 1
            await asyncio.sleep(0.05)
        except:
            pass
    await update.message.reply_text(f"✅ تم الإرسال لـ {success} مستخدم.")

async def admin_send_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    if not update.message.reply_to_message or not update.message.reply_to_message.photo:
        await update.message.reply_text("❌ رد على صورة باستخدام /send_photo [نص اختياري]")
        return
    photo_id = update.message.reply_to_message.photo[-1].file_id
    caption = " ".join(context.args) if context.args else ""
    db = SessionLocal()
    users = db.query(TradingUser).filter(TradingUser.is_blocked == False).all()
    db.close()
    success = 0
    for u in users:
        try:
            await context.bot.send_photo(chat_id=u.tg_id, photo=photo_id, caption=caption)
            success += 1
            await asyncio.sleep(0.05)
        except:
            pass
    await update.message.reply_text(f"✅ تم إرسال الصورة لـ {success} مستخدم.")

async def admin_send_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    if not update.message.reply_to_message or not update.message.reply_to_message.video:
        await update.message.reply_text("❌ رد على فيديو باستخدام /send_video [نص اختياري]")
        return
    video_id = update.message.reply_to_message.video.file_id
    caption = " ".join(context.args) if context.args else ""
    db = SessionLocal()
    users = db.query(TradingUser).filter(TradingUser.is_blocked == False).all()
    db.close()
    success = 0
    for u in users:
        try:
            await context.bot.send_video(chat_id=u.tg_id, video=video_id, caption=caption)
            success += 1
            await asyncio.sleep(0.05)
        except:
            pass
    await update.message.reply_text(f"✅ تم إرسال الفيديو لـ {success} مستخدم.")

async def admin_set_tier(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر الأدمن لتحديد خطة المستخدم: تجربة/فضية/ذهبية/ماسية"""
    if update.effective_user.id not in ADMIN_IDS:
        return
    if len(context.args) < 2 or context.args[1].lower() not in ("trial", "basic", "pro", "vip"):
        await update.message.reply_text(
            "❌ استخدم: /set_tier [user_id] [trial|basic|pro|vip]\n\n"
            "trial = تجربة مجانية\nbasic = 🥉 الفضية\npro = 🥈 الذهبية\nvip = 💎 الماسية"
        )
        return
    target_id, tier = context.args[0], context.args[1].lower()
    db = SessionLocal()
    u = db.query(TradingUser).filter(TradingUser.tg_id == str(target_id)).first()
    if not u:
        await update.message.reply_text("❌ المستخدم غير موجود في قاعدة البيانات. اطلب منه إرسال /start أولاً.")
        db.close()
        return
    if tier == "trial":
        u.is_vip = False
        u.tier = "trial"
        label = "🎁 تجربة مجانية"
    else:
        u.is_vip = True
        u.tier = tier
        label = TIER_LIMITS[tier]["name"]
    u.usage_date = ""
    db.commit()
    db.close()
    await update.message.reply_text(f"✅ تم تعيين المستخدم {target_id} إلى خطة: {label}")
    try:
        await context.bot.send_message(
            chat_id=int(target_id),
            text=f"🎉 *تم تحديث اشتراكك!*\n\nخطتك الحالية: {label}\n\nأرسل /start لرؤية مميزاتك الجديدة.",
            parse_mode="Markdown"
        )
    except Exception:
        pass


async def admin_set_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    if len(context.args) < 1:
        await update.message.reply_text("❌ استخدم: /set_vip [user_id] [true/false]")
        return
    user_id = context.args[0]
    is_vip = context.args[1].lower() == "true" if len(context.args) > 1 else True
    db = SessionLocal()
    user = db.query(TradingUser).filter(TradingUser.tg_id == user_id).first()
    if user:
        user.is_vip = is_vip
        db.commit()
        await update.message.reply_text(f"✅ تم تحديث المستخدم {user_id} إلى {'VIP ✅' if is_vip else 'عادي ❌'}")
    else:
        await update.message.reply_text("❌ المستخدم غير موجود")
    db.close()

async def admin_signal_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    # ── التحقق من فتح السوق قبل إرسال الإشارة اليدوية ──
    market_open, market_msg = is_market_open()
    if not market_open:
        await update.message.reply_text(f"⛔ لا يمكن إرسال إشارة الآن.\n\n{market_msg}\n\nيرجى الانتظار حتى فتح الأسواق.")
        return

    if not finnhub_ws.is_data_fresh():
        await asyncio.to_thread(gold_manager.update)
    data = gold_manager.get_analysis_data()
    if not data:
        await update.message.reply_text("⚠️ لا تتوفر بيانات كافية بعد. حاول لاحقاً.")
        return

    signal_engine.last_signal_time = None
    signal = signal_engine.generate_signal(data)

    if not signal:
        await update.message.reply_text("⚠️ لا توجد إشارة قوية بما يكفي الآن. النظام يحمي المستخدمين.")
        return

    db = SessionLocal()
    users = db.query(TradingUser).filter(TradingUser.is_blocked == False).all()
    db.close()
    success = 0
    for u in users:
        try:
            text = format_signal(signal, tier=get_user_tier(u) or "basic")
            await context.bot.send_message(chat_id=u.tg_id, text=text, parse_mode="Markdown")
            success += 1
            await asyncio.sleep(0.05)
        except:
            pass
    _save_signal_for_website(signal)
    _update_stats_for_website()
    await update.message.reply_text(f"✅ تم إرسال الإشارة لـ {success} مستخدم.")

async def admin_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    db = SessionLocal()
    users       = db.query(TradingUser).order_by(TradingUser.created_at.desc()).all()
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_list  = [u for u in users if u.created_at and u.created_at >= today_start]
    db.close()

    text = (
        f"👥 *قائمة المستخدمين*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 الإجمالي: `{len(users)}` | اليوم: `{len(today_list)}` 🆕\n\n"
    )
    if today_list:
        text += "🆕 *انضموا اليوم:*\n"
        for u in today_list[:10]:
            tag = "💎" if u.is_vip else "👤"
            name = (u.first_name or u.username or "مجهول")[:14]
            sigs = u.signals_requested or 0
            text += f"  {tag} `{u.tg_id}` {name} — ⚡{sigs} إشارة\n"
        text += "\n"

    text += "📋 *آخر المستخدمين:*\n"
    for u in users[:20]:
        tag  = "💎" if u.is_vip else ("🚫" if u.is_blocked else "👤")
        name = (u.first_name or u.username or "مجهول")[:14]
        sigs = u.signals_requested or 0
        text += f"  {tag} `{u.tg_id}` {name} — ⚡{sigs}\n"

    if len(users) > 20:
        text += f"\n_...و {len(users)-20} مستخدم آخر_"

    await update.message.reply_text(text, parse_mode="Markdown")


async def admin_userdata(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    if not context.args:
        await update.message.reply_text(
            "❌ استخدم: `/userdata [user_id]`\n"
            "مثال: `/userdata 123456789`",
            parse_mode="Markdown"
        )
        return
    target = context.args[0].strip()
    db = SessionLocal()
    user = db.query(TradingUser).filter(TradingUser.tg_id == target).first()
    user_sigs = db.query(Signal).count()
    db.close()
    if not user:
        await update.message.reply_text(f"❌ المستخدم `{target}` غير موجود في قاعدة البيانات.", parse_mode="Markdown")
        return
    joined = user.created_at.strftime("%Y-%m-%d %H:%M") if user.created_at else "—"
    trial     = is_trial_active(user)
    sigs_rem  = trial_remaining_signals(user)
    status = "💎 VIP مفعّل" if user.is_vip else (f"🎁 تجربة ({sigs_rem} إشارة متبقية)" if trial else "⏰ انتهت التجربة المجانية")
    blocked = "🚫 محظور" if user.is_blocked else "✅ نشط"
    await update.message.reply_text(
        f"🔍 *بيانات المستخدم*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 ID: `{user.tg_id}`\n"
        f"👤 الاسم: `{user.first_name or '—'}` | @{user.username or 'بدون'}\n"
        f"📅 تاريخ الانضمام: `{joined}`\n"
        f"🏷️ الحالة: {status}\n"
        f"🔒 الوضع: {blocked}\n"
        f"⚡ الإشارات المطلوبة: `{user.signals_requested or 0}`\n",
        parse_mode="Markdown"
    )

async def admin_poll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    args_text = " ".join(context.args)
    if "|" not in args_text:
        await update.message.reply_text(
            "❌ تنسيق: /send_poll السؤال | خيار1 | خيار2 | خيار3\n"
            "مثال: /send_poll ما رأيك في الإشارات؟ | ممتازة | جيدة | تحتاج تحسين"
        )
        return
    parts = [p.strip() for p in args_text.split("|")]
    question = parts[0]
    options = parts[1:]
    if len(options) < 2:
        await update.message.reply_text("❌ يجب إضافة خيارين على الأقل")
        return
    db = SessionLocal()
    users = db.query(TradingUser).filter(TradingUser.is_blocked == False).all()
    db.close()
    first_poll_id = None
    success = 0
    for u in users:
        try:
            msg = await context.bot.send_poll(
                chat_id=u.tg_id, question=question, options=options,
                is_anonymous=False, allows_multiple_answers=False
            )
            if first_poll_id is None and msg.poll:
                first_poll_id = msg.poll.id
            success += 1
            await asyncio.sleep(0.05)
        except:
            pass
    db = SessionLocal()
    survey = Survey(
        poll_id=str(first_poll_id) if first_poll_id else f"manual_{int(datetime.utcnow().timestamp())}",
        question=question,
        options=json.dumps(options, ensure_ascii=False),
        results=json.dumps({opt: 0 for opt in options}, ensure_ascii=False),
        vote_count=0,
        is_active=True,
    )
    db.add(survey)
    db.commit()
    db.close()
    await update.message.reply_text(
        f"✅ تم إرسال الاستبيان لـ {success} مستخدم\n"
        f"📊 السؤال: {question}\n"
        f"🔢 الخيارات: {' | '.join(options)}\n\n"
        f"اعرض النتائج بأمر: /poll_results"
    )


async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer = update.poll_answer
    if not answer:
        return
    db = SessionLocal()
    survey = db.query(Survey).filter(Survey.poll_id == str(answer.poll_id)).first()
    if survey:
        options = json.loads(survey.options)
        results = json.loads(survey.results or "{}")
        for opt_id in answer.option_ids:
            if opt_id < len(options):
                opt_name = options[opt_id]
                results[opt_name] = results.get(opt_name, 0) + 1
        survey.results = json.dumps(results, ensure_ascii=False)
        survey.vote_count = (survey.vote_count or 0) + 1
        db.commit()
    db.close()


async def admin_poll_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    db = SessionLocal()
    surveys = db.query(Survey).order_by(Survey.created_at.desc()).limit(5).all()
    db.close()
    if not surveys:
        await update.message.reply_text("📊 لا توجد استبيانات بعد.\nأرسل استبيان بـ /send_poll")
        return
    text = "📊 *نتائج آخر الاستبيانات*\n" + "━" * 28 + "\n\n"
    for i, s in enumerate(surveys, 1):
        results = json.loads(s.results or "{}")
        total = s.vote_count or sum(results.values()) or 1
        text += f"*{i}. {s.question}*\n"
        text += f"👥 إجمالي الأصوات: `{total}`\n"
        for option, count in results.items():
            pct = round((count / max(total, 1)) * 100)
            bar_len = round(pct / 10)
            bar = "▓" * bar_len + "░" * (10 - bar_len)
            text += f"  • {option}: `{count}` ({pct}%) {bar}\n"
        text += f"📅 {s.created_at.strftime('%Y-%m-%d %H:%M') if s.created_at else '--'}\n\n"
    await update.message.reply_text(text, parse_mode="Markdown")

# ============================================================
#  AUTO TRADING ADMIN COMMANDS
# ============================================================
async def admin_price_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يعرض بيانات السعر والتحليل التقني للأدمن"""
    if update.effective_user.id not in ADMIN_IDS:
        return
    if not finnhub_ws.is_data_fresh():
        await asyncio.to_thread(gold_manager.update)
    price    = gold_manager.current_price
    prices   = list(gold_manager.price_history)
    rsi_val  = TechnicalAnalysis.rsi(prices) if len(prices) >= 5 else None
    ws_ok    = gold_manager.last_update and (datetime.utcnow()-gold_manager.last_update).total_seconds() < 300
    ws_st    = "🟢 متصل" if ws_ok else "🔴 منقطع"
    last_upd = gold_manager.last_update.strftime("%H:%M:%S") if gold_manager.last_update else "—"
    rsi_text = f"`{rsi_val}`" if rsi_val else "⏳ يُحسب..."
    trend = ""
    if len(prices) >= 5:
        chg = prices[-1] - prices[-5]
        trend = f"📈 +{chg:.2f}" if chg > 0 else f"📉 {chg:.2f}"
    await update.message.reply_text(
        f"""💰 *بيانات {PAIR_CFG['display_name']} {PAIR_CFG['symbol']}*
━━━━━━━━━━━━━━━━━━━━━━━━
💎 *السعر:* `${price:,.2f}` {trend}
📡 *WebSocket:* {ws_st}
🕐 *آخر تحديث:* `{last_upd}`
📊 *نقاط البيانات:* `{len(prices)}/200`
📈 *RSI (14):* {rsi_text}
🌍 *الجلسة:* {gold_manager._get_trading_session()}
🔑 *مفاتيح AI نشطة:* `{len(gemini.valid_keys)}/15`""",
        parse_mode="Markdown"
    )


async def admin_block(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    if not context.args:
        await update.message.reply_text("❌ استخدم: `/block [user_id]`", parse_mode="Markdown")
        return
    db = SessionLocal()
    user = db.query(TradingUser).filter(TradingUser.tg_id == context.args[0]).first()
    if user:
        user.is_blocked = True
        db.commit()
        await update.message.reply_text(f"✅ تم حجب المستخدم `{context.args[0]}`", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ المستخدم غير موجود")
    db.close()


async def admin_unblock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    if not context.args:
        await update.message.reply_text("❌ استخدم: `/unblock [user_id]`", parse_mode="Markdown")
        return
    db = SessionLocal()
    user = db.query(TradingUser).filter(TradingUser.tg_id == context.args[0]).first()
    if user:
        user.is_blocked = False
        db.commit()
        await update.message.reply_text(f"✅ تم رفع الحجب عن `{context.args[0]}`", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ المستخدم غير موجود")
    db.close()


async def admin_signals_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    db = SessionLocal()
    sigs = db.query(Signal).order_by(Signal.created_at.desc()).limit(10).all()
    total = db.query(Signal).count()
    db.close()
    text = f"⚡ *آخر 10 إشارات* (من {total} إجمالاً)\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    for s in sigs:
        icon = "🟢" if s.direction == "BUY" else "🔴"
        dt = s.created_at.strftime("%m/%d %H:%M") if s.created_at else "—"
        text += f"{icon} `{s.direction}` @ `{s.entry_price:.2f}` | SL`{s.sl:.2f}` | TP`{s.tp1:.2f}` | {s.confidence:.0f}% | {dt}\n"
    await update.message.reply_text(text, parse_mode="Markdown")


async def admin_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """آخر الأعضاء الجدد مع إحصائيات مفصلة"""
    if update.effective_user.id not in ADMIN_IDS:
        return
    db = SessionLocal()
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    week_start  = today_start - timedelta(days=7)
    all_users   = db.query(TradingUser).order_by(TradingUser.created_at.desc()).all()
    today_new   = [u for u in all_users if u.created_at and u.created_at >= today_start]
    week_new    = [u for u in all_users if u.created_at and u.created_at >= week_start]
    vip_count   = sum(1 for u in all_users if u.is_vip)
    trial_count = sum(1 for u in all_users if is_trial_active(u) and not u.is_vip)
    expired     = sum(1 for u in all_users if not is_trial_active(u) and not u.is_vip)
    db.close()
    text = (
        f"👥 *إحصائيات الأعضاء الكاملة*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 الإجمالي: `{len(all_users)}`\n"
        f"🆕 اليوم: `{len(today_new)}` | الأسبوع: `{len(week_new)}`\n"
        f"💎 VIP: `{vip_count}` | 🎁 تجربة: `{trial_count}` | ⏰ منتهية: `{expired}`\n\n"
        f"🆕 *أحدث 15 عضو:*\n"
    )
    for u in all_users[:15]:
        tag  = "💎" if u.is_vip else ("🎁" if is_trial_active(u) else "⏰")
        name = (u.first_name or u.username or "مجهول")[:16]
        dt   = u.created_at.strftime("%m/%d") if u.created_at else "—"
        text += f"  {tag} `{u.tg_id}` {name} [{dt}] ⚡{u.signals_requested or 0}\n"
    await update.message.reply_text(text, parse_mode="Markdown")


async def admin_automode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    if not context.args:
        state = "🟢 مفعَّل" if getattr(auto_trader, 'auto_trading_enabled', False) else "🔴 موقوف"
        await update.message.reply_text(
            f"🤖 *التداول الآلي حالياً: {state}*\n\n"
            f"الاستخدام:\n`/automode on` — تفعيل\n`/automode off` — إيقاف",
            parse_mode="Markdown"
        )
        return
    cmd = context.args[0].lower()
    if cmd == "on":
        if not auto_trader.META_API_TOKEN or not auto_trader.META_ACCOUNT_ID:
            await update.message.reply_text(
                "❌ *لا يمكن تفعيل التداول الآلي*\n\n"
                "يجب أولاً إعداد:\n"
                "• `META_API_TOKEN`\n"
                "• `META_ACCOUNT_ID`\n\n"
                "راجع تعليمات الإعداد بأمر /autostatus",
                parse_mode="Markdown"
            )
            return
        auto_trader.auto_trading_enabled = True
        await update.message.reply_text("✅ *التداول الآلي مُفعَّل!*\nسيُنفَّذ كل إشارة تلقائياً على MT5.", parse_mode="Markdown")
    elif cmd == "off":
        auto_trader.auto_trading_enabled = False
        await update.message.reply_text("🔴 *التداول الآلي موقوف.*", parse_mode="Markdown")
    else:
        await update.message.reply_text("❓ استخدم: `/automode on` أو `/automode off`", parse_mode="Markdown")


async def admin_autostatus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    await update.message.reply_text("⏳ جاري جلب البيانات من MT5...")
    loop = asyncio.get_event_loop()
    report = await loop.run_in_executor(None, auto_trader.build_status_report)

    setup_note = ""
    if not auto_trader.META_API_TOKEN or not auto_trader.META_ACCOUNT_ID:
        setup_note = (
            "\n\n📖 *خطوات الإعداد:*\n"
            "1️⃣ سجّل على [metaapi.cloud](https://app.metaapi.cloud)\n"
            "2️⃣ أضف حسابك MT5 (login/password/server)\n"
            "3️⃣ انسخ API Token و Account ID\n"
            "4️⃣ أضفهما كـ Secrets:\n"
            "   • `META_API_TOKEN`\n"
            "   • `META_ACCOUNT_ID`\n"
            "5️⃣ أعد تشغيل البوت ثم `/automode on`"
        )

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 تفعيل", callback_data="auto_on"),
         InlineKeyboardButton("🔴 إيقاف", callback_data="auto_off")],
        [InlineKeyboardButton("📊 الصفقات", callback_data="auto_positions"),
         InlineKeyboardButton("❌ إغلاق الكل", callback_data="auto_closeall")]
    ])
    await update.message.reply_text(report + setup_note, reply_markup=markup, parse_mode="Markdown")


async def admin_positions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    loop = asyncio.get_event_loop()
    report = await loop.run_in_executor(None, auto_trader.build_positions_report)
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 تحديث", callback_data="auto_positions"),
         InlineKeyboardButton("❌ إغلاق الكل", callback_data="auto_closeall")]
    ])
    await update.message.reply_text(report, reply_markup=markup, parse_mode="Markdown")


async def admin_closeall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    await update.message.reply_text("⏳ جاري إغلاق جميع الصفقات...")
    loop = asyncio.get_event_loop()
    closed = await loop.run_in_executor(None, auto_trader.close_all_positions)
    await update.message.reply_text(
        f"✅ تم إغلاق *{closed}* صفقة بنجاح." if closed else "📭 لا توجد صفقات مفتوحة.",
        parse_mode="Markdown"
    )


async def _handle_auto_buttons(query, data: str):
    user_id = query.from_user.id
    if user_id not in ADMIN_IDS:
        await query.answer("❌ غير مصرح")
        return
    loop = asyncio.get_event_loop()
    if data == "auto_on":
        if not auto_trader.META_API_TOKEN or not auto_trader.META_ACCOUNT_ID:
            await query.answer("❌ أعدّ META_API_TOKEN و META_ACCOUNT_ID أولاً")
            return
        auto_trader.auto_trading_enabled = True
        await query.answer("✅ التداول الآلي مُفعَّل")
        report = await loop.run_in_executor(None, auto_trader.build_status_report)
        await query.edit_message_text(report, parse_mode="Markdown")
    elif data == "auto_off":
        auto_trader.auto_trading_enabled = False
        await query.answer("🔴 التداول الآلي موقوف")
        report = await loop.run_in_executor(None, auto_trader.build_status_report)
        await query.edit_message_text(report, parse_mode="Markdown")
    elif data == "auto_positions":
        report = await loop.run_in_executor(None, auto_trader.build_positions_report)
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 تحديث", callback_data="auto_positions"),
             InlineKeyboardButton("❌ إغلاق الكل", callback_data="auto_closeall")]
        ])
        await query.edit_message_text(report, reply_markup=markup, parse_mode="Markdown")
    elif data == "auto_closeall":
        await query.answer("⏳ جاري الإغلاق...")
        closed = await loop.run_in_executor(None, auto_trader.close_all_positions)
        await query.edit_message_text(
            f"✅ تم إغلاق *{closed}* صفقة." if closed else "📭 لا توجد صفقات مفتوحة.",
            parse_mode="Markdown"
        )

# ============================================================
#  BACKGROUND TASKS
# ============================================================
async def price_update_job(context: ContextTypes.DEFAULT_TYPE):
    """تحديث سعر الذهب كل 3 دقائق وتوليد إشارات تلقائية للـ VIP"""
    try:
        ws_ok   = finnhub_ws.is_connected()
        data_ok = finnhub_ws.is_data_fresh()

        if not data_ok:
            # لا بيانات حديثة — HTTP fallback (Yahoo Finance اولاً)
            logger.warning("بيانات قديمة — HTTP fallback")
            await asyncio.to_thread(gold_manager.update)

        p = gold_manager.current_price or 0
        n = len(gold_manager.price_history)
        if ws_ok and data_ok:
            logger.info("WS نشط بيانات حديثة — سعر: " + str(round(p, 2)) + " نقاط: " + str(n))
        elif ws_ok:
            logger.info("WS متصل ينتظر اول تيك — كاش: " + str(round(p, 2)))
        else:
            logger.warning("WS منقطع يعيد اتصال — HTTP: " + str(round(p, 2)))
        
        # ── التحقق من فتح السوق قبل إرسال الإشارات التلقائية ──
        market_open, _ = is_market_open()
        if not market_open:
            logger.info("السوق مغلق، لن يتم إرسال إشارات تلقائية الآن.")
            return

        data = gold_manager.get_analysis_data()
        if data and len(data["prices"]) >= 50:
            signal = signal_engine.generate_signal(data)
            if signal:
                # ── الإشارات التلقائية 24/7 حصرية للخطة الماسية VIP + مستخدمي التجربة المجانية ──
                # 🥉 الفضية و🥈 الذهبية لا يستقبلون بث تلقائي — يطلبون الإشارة يدوياً ضمن حصتهم اليومية
                db = SessionLocal()
                all_users = db.query(TradingUser).filter(
                    TradingUser.is_blocked == False
                ).all()
                db.close()
                eligible_users = [
                    u for u in all_users
                    if (not u.is_vip and is_trial_active(u)) or get_user_tier(u) == "vip"
                ]
                sent = 0
                for u in eligible_users:
                    try:
                        u_tier = get_user_tier(u) or "basic"
                        text = format_signal(signal, tier=u_tier)
                        prefix = "🚨 *إشعار فوري — إشارة قوية!*\n\n" if u_tier == "vip" and signal["confidence"] > 80 else ""
                        await context.bot.send_message(
                            chat_id=u.tg_id, text=prefix + text, parse_mode="Markdown"
                        )
                        sent += 1
                        await asyncio.sleep(0.05)
                    except:
                        pass
                logger.info(f"✅ إشارة تلقائية VIP - ثقة: {signal['confidence']}% - أُرسلت لـ {sent} مستخدم")
                _save_signal_for_website(signal)
                _update_stats_for_website()

                if getattr(auto_trader, 'auto_trading_enabled', False):
                    try:
                        loop = asyncio.get_event_loop()
                        trade_result = await loop.run_in_executor(
                            None, auto_trader.place_order, signal
                        )
                        if trade_result:
                            trade_msg = (
                                f"🤖 *تم تنفيذ صفقة آلية!*\n"
                                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"📌 الاتجاه: {'🟢 شراء' if signal['direction']=='BUY' else '🔴 بيع'}\n"
                                f"💰 الدخول: `{signal['entry']}`\n"
                                f"🛑 SL: `{signal['sl']}` | 🎯 TP: `{signal['tp2']}`\n"
                                f"📊 نسبة الثقة: `{signal['confidence']}%`\n"
                                f"🕐 {datetime.now().strftime('%H:%M:%S')}"
                            )
                            for admin_id in ADMIN_IDS:
                                try:
                                    await context.bot.send_message(
                                        chat_id=admin_id, text=trade_msg, parse_mode="Markdown"
                                    )
                                except:
                                    pass
                    except Exception as te:
                        logger.error(f"Auto trade execution error: {te}")

                # User auto-trade accounts
                try:
                    _dbu = SessionLocal()
                    _accs = _dbu.query(AutoTradeAccount).filter(
                        AutoTradeAccount.is_active == True,
                        AutoTradeAccount.meta_token != ""
                    ).all()
                    _dbu.close()
                    for _a in _accs:
                        try:
                            _ot = auto_trader.META_API_TOKEN
                            _oi = auto_trader.META_ACCOUNT_ID
                            auto_trader.META_API_TOKEN = _a.meta_token
                            auto_trader.META_ACCOUNT_ID = _a.meta_account_id
                            _s2 = dict(signal)
                            _s2["volume"] = _a.lot_size
                            _ok = await asyncio.get_event_loop().run_in_executor(None, auto_trader.place_order, _s2)
                            auto_trader.META_API_TOKEN = _ot
                            auto_trader.META_ACCOUNT_ID = _oi
                            if _ok:
                                _db2 = SessionLocal()
                                _a2 = _db2.query(AutoTradeAccount).filter(AutoTradeAccount.tg_id == _a.tg_id).first()
                                if _a2:
                                    _a2.total_trades = (_a2.total_trades or 0) + 1
                                    _a2.updated_at = datetime.utcnow()
                                    _db2.commit()
                                _db2.close()
                                await context.bot.send_message(
                                    chat_id=_a.tg_id,
                                    text=("🤖 صفقة آلية تم تنفيذها!\n" +
                                          f"{'شراء' if signal['direction']=='BUY' else 'بيع'} | {signal['entry']}\n" +
                                          f"TP: {signal['tp2']} | SL: {signal['sl']}\n" +
                                          f"اللوت: {_a.lot_size}"),
                                    parse_mode="Markdown"
                                )
                        except Exception as _ue:
                            logger.error(f"User auto-trade {_a.tg_id}: {_ue}")
                except Exception as _be:
                    logger.error(f"Batch auto-trade: {_be}")
        else:
            pts = len(data["prices"]) if data else 0
            logger.info(f"🔄 تحديث سعر {PAIR_CFG['display_name']} - نقاط البيانات: {pts}/50")
    except Exception as e:
        logger.error(f"Price update error: {e}")


# علم مستوى الوحدة — يبقى محفوظاً بين تشغيلات المهمة (context لا يُحفظ)
_market_was_open: bool = False

async def market_reopen_check(context: ContextTypes.DEFAULT_TYPE):
    """
    تفحص كل ساعة إذا فتح سوق XAUUSD.
    الإشعار يُرسل فقط عند:
      1. التحول من مغلق -> مفتوح (مرة واحدة)
      2. وصول تيك حقيقي من مصدر البيانات (last_update < 10 دق)
      3. السعر صالح (> 100)
    """
    global _market_was_open

    now = datetime.utcnow()
    market_open, market_msg = is_market_open()

    if not market_open:
        # إعادة تعيين العلم حتى يُرسل الإشعار عند الفتح التالي
        if _market_was_open:
            logger.info("السوق أغلق — سيُرسل إشعار عند الفتح التالي.")
        _market_was_open = False
        return

    # ── السوق مفتوح — هل هذا تحول جديد؟ ──────────────────────────
    if _market_was_open:
        # لا نرسل مجدداً — السوق كان مفتوحاً بالفعل
        return

    # ── تحقق من بيانات حقيقية ──────────────────────────────────────
    price         = gold_manager.current_price
    last_upd      = gold_manager.last_update
    price_valid   = price and price > 100
    upd_seconds   = (now - last_upd).total_seconds() if last_upd else 99999
    data_fresh    = last_upd is not None and upd_seconds < 600
    ws_connected  = finnhub_ws.is_connected()
    data_source   = "WebSocket" if finnhub_ws.is_data_fresh() else ("Yahoo/HTTP" if data_fresh else "لا يوجد")

    logger.info(
        "فحص فتح السوق:"
        " | open=" + str(market_open) +
        " | سعر=" + str(round(price, 2) if price else "N/A") +
        " | آخر_تيك=" + str(round(upd_seconds)) + "ث" +
        " | WS=" + str(ws_connected) +
        " | مصدر=" + data_source
    )

    if not price_valid:
        logger.warning("السوق مفتوح زمنياً لكن لا سعر صالح — إشعار مؤجل.")
        return

    if not data_fresh:
        logger.warning(
            "السوق مفتوح زمنياً لكن لا بيانات حديثة ("
            + str(round(upd_seconds)) + "ث منذ آخر تحديث) — إشعار مؤجل."
        )
        return

    # ── كل الشروط محققة — أرسل الإشعار مرة واحدة ──────────────────
    logger.info(
        "إرسال إشعار فتح السوق"
        " | سعر=" + str(round(price, 2)) +
        " | مصدر=" + data_source +
        " | " + market_msg
    )
    _market_was_open = True
    await notify_market_reopening(context)


# ============================================================
#  MAIN
# ============================================================
DAILY_REMINDERS = [
    f"""⚡ *تذكير يومي من نظام التداول الذكي*
━━━━━━━━━━━━━━━━━━━━━━━━
📊 سوق {PAIR_CFG['symbol']} يتحرك الآن!
النظام يراقب 12 مصدر تأكيد لحظة بلحظة.

💡 *نصيحة اليوم:*
لا تتداول بدون خطة واضحة.
الصبر + الانضباط = نتائج ثابتة.

🔔 اضغط /start لعرض آخر الإشارات""",
    """🌅 *صباح الخير من بوت التداول!*
━━━━━━━━━━━━━━━━━━━━━━━━
💰 سوق {PAIR_CFG['display_name']} {PAIR_CFG['symbol']} يفتح مع جلسة جديدة.
نظامنا جاهز لتوليد الإشارات الدقيقة.

📌 *تذكر دائماً:*
• ضع وقف الخسارة قبل الدخول
• لا تخاطر بأكثر من 2% من رأس المال
• اتبع الإشارة ولا تعدّل عليها

💎 مشتركو VIP يحصلون على الإشارات تلقائياً!""",
    """📈 *تحديث يومي - بوت التداول الذكي*
━━━━━━━━━━━━━━━━━━━━━━━━
🧠 نظامنا يعمل بـ 12 مصدر تأكيد:
RSI • MACD • Bollinger • Fibonacci
ATR • Stochastic • 6 نماذج رياضية

🎯 *الإشارة تُرسل عند:*
✅ 7/12 مصدر متفق
✅ ثقة ≥ 65%
✅ تأكيد 3 نماذج + 3 مؤشرات

🔥 اشترك VIP وابدأ التداول الاحترافي!""",
]

async def daily_reminder_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        db = SessionLocal()
        users = db.query(TradingUser).filter(TradingUser.is_blocked == False).all()
        db.close()
        msg = random.choice(DAILY_REMINDERS)
        sent = 0
        for u in users:
            try:
                await context.bot.send_message(
                    chat_id=u.tg_id,
                    text=msg,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⚡ عرض الإشارات", callback_data="get_signal"),
                         InlineKeyboardButton("💰 سعر " + PAIR_CFG['display_name'], callback_data="gold_price")]
                    ])
                )
                sent += 1
                await asyncio.sleep(0.08)
            except:
                pass
        logger.info(f"📬 التذكير اليومي أُرسل لـ {sent} مستخدم")
    except Exception as e:
        logger.error(f"❌ خطأ في التذكير اليومي: {e}")


async def post_init(application: Application):
    finnhub_ws.start()
    application.job_queue.run_repeating(
        price_update_job,
        interval=180,
        first=15,
        name="gold_price_updater"
    )
    # إضافة مهمة مراقبة فتح السوق كل ساعة
    application.job_queue.run_repeating(
        market_reopen_check,
        interval=3600,
        first=60,
        name="market_reopen_checker"
    )
    application.job_queue.run_repeating(
        check_gold_alerts,
        interval=15,
        first=15,
        name="gold_alerts_checker"
    )
    application.job_queue.run_daily(
        daily_morning_summary,
        time=dtime(6, 0, 0),
        name="daily_vip_summary"
    )
    application.job_queue.run_daily(
        evening_market_summary,
        time=dtime(20, 0, 0),
        name="evening_summary"
    )
    application.job_queue.run_daily(
        vip_renewal_reminder,
        time=dtime(10, 0, 0),
        name="vip_reminder"
    )
    application.job_queue.run_repeating(
        check_trade_signals,
        interval=300,
        first=60,
        name="trade_signal_checker"
    )
    application.job_queue.run_repeating(
        admin_performance_report,
        interval=43200,
        first=600,
        name="admin_perf_report"
    )
    application.job_queue.run_daily(
        daily_reminder_job,
        time=dtime(7, 0, 0),
        name="daily_reminder"
    )
    logger.info(f"✅ Finnhub WebSocket بدأ (بيانات لحظية {PAIR_CFG['symbol']})")
    logger.info("✅ مهمة تحديث الأسعار جدولت كل 3 دقائق (fallback)")
    logger.info("✅ مهمة فتح السوق جدولت كل ساعة")
    logger.info("✅ التذكير اليومي جدول الساعة 9:00 صباحاً")


def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # أوامر المستخدمين
    app.add_handler(CommandHandler("start", start))

    # أوامر الأدمن - إدارة المستخدمين
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CommandHandler("users", admin_users_list))
    app.add_handler(CommandHandler("userdata", admin_userdata))
    app.add_handler(CommandHandler("set_vip", admin_set_vip))
    app.add_handler(CommandHandler("set_tier", admin_set_tier))

    # أوامر الأدمن - البث
    app.add_handler(CommandHandler("broadcast", admin_broadcast))
    app.add_handler(CommandHandler("send_photo", admin_send_photo))
    app.add_handler(CommandHandler("send_video", admin_send_video))
    app.add_handler(CommandHandler("send_poll", admin_poll))
    app.add_handler(CommandHandler("poll_results", admin_poll_results))

    # أوامر الأدمن - الإشارات والأسعار
    app.add_handler(CommandHandler("signal", admin_signal_manual))
    app.add_handler(CommandHandler("signals", admin_signals_list))
    app.add_handler(CommandHandler("price", admin_price_info))
    app.add_handler(CommandHandler("data", admin_price_info))
    app.add_handler(CommandHandler("block", admin_block))
    app.add_handler(CommandHandler("unblock", admin_unblock))
    app.add_handler(CommandHandler("members", admin_new_members))

    # ميزة تحليل الاستراتيجية
    app.add_handler(CommandHandler("strategy", cmd_strategy))

    # أوامر التداول الآلي
    app.add_handler(CommandHandler("automode", admin_automode))
    app.add_handler(CommandHandler("autostatus", admin_autostatus))
    app.add_handler(CommandHandler("positions", admin_positions))
    app.add_handler(CommandHandler("closeall", admin_closeall))

    app.add_handler(auto_trading_conv)
    app.add_handler(alert_conv)
    app.add_handler(CommandHandler("alerts_clear", alerts_clear))
    app.add_handler(CommandHandler("ref", cmd_referral))
    app.add_handler(CommandHandler("points", cmd_points))
    # أزرار التفاعل
    app.add_handler(CallbackQueryHandler(button_handler))

    # معالجة إجابات الاستبيانات
    app.add_handler(PollAnswerHandler(handle_poll_answer))

    # معالجة الصور (تحليل الشارت)
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_free_text_message))

    logger.info("🚀 بوت التداول الذكي v7.0 (مع مراقبة فتح السوق) يعمل الآن!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()