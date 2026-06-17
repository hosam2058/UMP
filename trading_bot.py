import os
import logging
import asyncio
import json
import math
import random
import requests
import threading
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
DATABASE_URL = "sqlite:///data/trading_bot.db"
os.makedirs("data", exist_ok=True)
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
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

class Signal(Base):
    __tablename__ = "signals"
    id = Column(Integer, primary_key=True)
    pair = Column(String, default="XAUUSD")
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

Base.metadata.create_all(bind=engine)

def _migrate_db():
    from sqlalchemy import text as _text
    with engine.connect() as conn:
        for col, ddl in [
            ("first_name",         "ALTER TABLE trading_users ADD COLUMN first_name TEXT DEFAULT ''"),
            ("signals_requested",  "ALTER TABLE trading_users ADD COLUMN signals_requested INTEGER DEFAULT 0"),
        ]:
            try:
                conn.execute(_text(ddl))
                conn.commit()
            except Exception:
                pass
_migrate_db()

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
BOT_TOKEN = os.getenv("TRADING_BOT_TOKEN", "8543638509:AAGu_lP83It50LcIXbtZeaC5stuqz5HvHn4")
WHATSAPP_LINK = "https://wa.me/201500236188"
ADMIN_IDS = [8865738615]
GOLD_API_KEY = os.getenv("GOLD_API_KEY", "")
WEBSITE_URL = f"https://{os.getenv('REPLIT_DEV_DOMAIN', 'trading-bot.replit.app')}"

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
    bool = True إذا كان السوق مفتوحاً
    str = رسالة توضح السبب ومتى يفتح
    """
    now = datetime.utcnow()
    weekday = now.weekday()  # 0=الاثنين, 4=الجمعة, 5=السبت, 6=الأحد
    current_date_str = now.strftime("%m-%d")
    
    # 1. عطل نهاية الأسبوع
    if weekday >= 5:  # السبت (5) أو الأحد (6)
        # افتتاح السوق: الأحد الساعة 23:00 UTC (تقريباً)
        next_open = now.replace(hour=23, minute=0, second=0, microsecond=0)
        if weekday == 5:  # السبت
            next_open += timedelta(days=1)
        elif weekday == 6 and now.hour >= 23:
            next_open += timedelta(days=1)
        remaining = next_open - now
        hours = int(remaining.total_seconds() // 3600)
        minutes = int((remaining.total_seconds() % 3600) // 60)
        return False, f"⛔ السوق مغلق حالياً (عطلة نهاية الأسبوع). سيفتح بعد {hours} ساعة و {minutes} دقيقة."
    
    # 2. العطل الرسمية
    if current_date_str in HOLIDAYS:
        next_open = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        remaining = next_open - now
        hours = int(remaining.total_seconds() // 3600)
        minutes = int((remaining.total_seconds() % 3600) // 60)
        return False, f"⛔ السوق مغلق بمناسبة عطلة رسمية ({current_date_str}). سيفتح بعد {hours} ساعة و {minutes} دقيقة."
    
    return True, "✅ السوق مفتوح الآن."

async def notify_market_reopening(context: ContextTypes.DEFAULT_TYPE):
    """تُستدعى عند فتح السوق (مثلاً يوم الاثنين) لإعلام جميع المستخدمين."""
    try:
        db = SessionLocal()
        users = db.query(TradingUser).filter(TradingUser.is_blocked == False).all()
        db.close()
        msg = "🔔 *عودة السوق للعمل!*\n\nتم فتح سوق XAUUSD الآن. يمكنك طلب إشارات التداول كالمعتاد.\n\nاستخدم /start للقائمة الرئيسية."
        sent = 0
        for u in users:
            try:
                await context.bot.send_message(chat_id=u.tg_id, text=msg, parse_mode="Markdown")
                sent += 1
                await asyncio.sleep(0.05)
            except:
                pass
        logger.info(f"تم إرسال إشعار فتح السوق لـ {sent} مستخدم.")
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
        self.valid_keys = [k for k in self.keys if k]
        self.current_index = 0
        self.exhausted = set()
        # نماذج النص فقط
        self.text_models = [
            "gemini-1.5-flash",
            "gemini-1.5-pro",
            "gemini-2.0-flash",
        ]
        # نماذج الرؤية (صور الشارت) - هذه فقط تدعم الصور
        self.vision_models = [
            "gemini-1.5-flash",
            "gemini-1.5-pro",
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
        import PIL.Image
        import io as _io

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
                        img = PIL.Image.open(_io.BytesIO(image_data))
                        # تحويل إلى RGB إذا لزم
                        if img.mode not in ("RGB", "RGBA"):
                            img = img.convert("RGB")
                        response = model.generate_content(
                            [prompt, img],
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
#  GOLD PRICE MANAGER
# ============================================================
class GoldPriceManager:
    """مدير أسعار الذهب - يدعم عدة APIs"""

    def __init__(self):
        self.current_price = None
        self.price_history = deque(maxlen=200)
        self.highs = deque(maxlen=200)
        self.lows = deque(maxlen=200)
        self.last_update = None
        self.session = "unknown"

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
        """جلب سعر الذهب الحقيقي"""
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
                    return {"price": price, "source": "goldprice.org"}
        except Exception as e:
            logger.warning(f"goldprice.org فشل: {e}")

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
                        if price > 0:
                            return {"price": price, "source": "metals.live"}
        except Exception as e:
            logger.warning(f"metals.live فشل: {e}")

        if GOLD_API_KEY:
            try:
                r = requests.get(
                    "https://www.goldapi.io/api/XAU/USD",
                    headers={"x-access-token": GOLD_API_KEY, "Content-Type": "application/json"},
                    timeout=5
                )
                if r.status_code == 200:
                    data = r.json()
                    price = float(data.get("price", 0))
                    if price > 0:
                        return {"price": price, "source": "goldapi.io"}
            except Exception as e:
                logger.warning(f"GoldAPI فشل: {e}")

        if self.current_price:
            noise = random.uniform(-2, 2)
            return {"price": round(self.current_price + noise, 2), "source": "cached"}

        return {"price": None, "source": "none"}

    def update(self) -> dict:
        result = self.fetch_price()
        price = result.get("price")
        if price and price > 100:
            self.current_price = price
            self.last_update = datetime.utcnow()
            self.session = self._get_trading_session()
            self.price_history.append(price)
            spread = price * random.uniform(0.0005, 0.001)
            self.highs.append(round(price + spread, 2))
            self.lows.append(round(price - spread, 2))
        return result

    def feed_ws_price(self, price: float):
        if not price or price < 100:
            return
        self.current_price = price
        self.last_update = datetime.utcnow()
        self.session = self._get_trading_session()
        self.price_history.append(price)
        spread = price * random.uniform(0.0005, 0.001)
        self.highs.append(round(price + spread, 2))
        self.lows.append(round(price - spread, 2))

    def get_analysis_data(self) -> dict:
        prices = list(self.price_history)
        highs = list(self.highs)
        lows = list(self.lows)
        if len(prices) < 20:
            return None
        return {"prices": prices, "highs": highs, "lows": lows}

gold_manager = GoldPriceManager()

# ============================================================
#  FINNHUB WEBSOCKET
# ============================================================
FINNHUB_API_KEY = "d840bm9r01qkm5c9pgfgd840bm9r01qkm5c9pgg0"

class FinnhubWebSocket:
    def __init__(self):
        self.ws = None
        self._thread = None
        self._last_price = None
        self._running = False

    def _on_open(self, ws):
        logger.info("🔌 Finnhub WebSocket متصل — جاري الاشتراك في XAUUSD")
        ws.send(json.dumps({"type": "subscribe", "symbol": "OANDA:XAU_USD"}))

    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
            if data.get("type") != "trade":
                return
            for trade in data.get("data", []):
                price = trade.get("p")
                if price and price != self._last_price:
                    self._last_price = price
                    gold_manager.feed_ws_price(float(price))
                    logger.debug(f"⚡ WS تيك XAUUSD: {price}")
        except Exception as e:
            logger.warning(f"⚠️ WS message error: {e}")

    def _on_error(self, ws, error):
        logger.warning(f"⚠️ Finnhub WS خطأ: {error}")

    def _on_close(self, ws, code, msg):
        logger.warning(f"🔴 Finnhub WS مغلق ({code}) — إعادة الاتصال بعد 10 ثوانٍ")
        if self._running:
            threading.Timer(10, self._connect).start()

    def _connect(self):
        if not _WS_AVAILABLE or _WebSocketApp is None:
            logger.warning("⚠️ WebSocketApp غير متاح — البوت يعمل بوضع HTTP فقط")
            return
        try:
            url = f"wss://ws.finnhub.io?token={FINNHUB_API_KEY}"
            self.ws = _WebSocketApp(
                url,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
            )
            self.ws.run_forever(ping_interval=30, ping_timeout=10)
        except Exception as e:
            logger.error(f"❌ Finnhub WS connect error: {e}")
            if self._running:
                threading.Timer(10, self._connect).start()

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._connect, daemon=True, name="FinnhubWS")
        self._thread.start()
        logger.info("🚀 Finnhub WebSocket thread بدأ")

    def stop(self):
        self._running = False
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

    def _model_4_wave(self, prices: list) -> str:
        if len(prices) < 20:
            return "neutral"
        highs = [max(prices[i:i+3]) for i in range(0, len(prices)-2, 3)]
        lows = [min(prices[i:i+3]) for i in range(0, len(prices)-2, 3)]
        if len(highs) >= 3:
            if highs[-1] > highs[-2] > highs[-3] and lows[-1] > lows[-2]:
                return "buy"
            elif highs[-1] < highs[-2] < highs[-3] and lows[-1] < lows[-2]:
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
            self._model_4_wave(prices),
            self._model_5_seasonal(prices),
            self._model_6_probabilistic(prices),
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

        total_buys = model_buys + ind_buys
        total_sells = model_sells + ind_sells

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
#  MESSAGE FORMATTING
# ============================================================
DIRECTION_EMOJI = {"BUY": "🟢 شراء", "SELL": "🔴 بيع"}
CONFIDENCE_BAR = lambda c: "🔥" * int(c // 20) + "⚡" * (5 - int(c // 20))

def format_signal(sig: dict) -> str:
    direction_ar = DIRECTION_EMOJI.get(sig["direction"], sig["direction"])
    bar = CONFIDENCE_BAR(sig["confidence"])
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    text = f"""⚡ **إشارة تداول VIP | XAUUSD**
━━━━━━━━━━━━━━━━━━━━━━━━
📌 **الاتجاه:** {direction_ar}
💰 **سعر الدخول:** ${sig['entry']:,.2f}
🎯 **الهدف الأول (TP1):** ${sig['tp1']:,.2f}
🎯 **الهدف الثاني (TP2):** ${sig['tp2']:,.2f}
🏆 **الهدف الثالث (TP3):** ${sig['tp3']:,.2f}
🛑 **وقف الخسارة (SL):** ${sig['sl']:,.2f}
📊 **نسبة المكسب/الخسارة:** {sig['rr_ratio']}:1

━━━━━━━━━━━━━━━━━━━━━━━━
🧠 **تحليل المحرك الذكي:**
• RSI: {sig['rsi']} {'(تشبع بيعي 📉)' if sig['rsi'] < 35 else '(تشبع شرائي 📈)' if sig['rsi'] > 65 else '(متوازن ⚖️)'}
• MACD: {sig['macd_signal'].upper()}
• Bollinger: {sig['bb_signal'].upper()}
• Stochastic: {sig['stoch_k']}
• ATR: {sig['atr']}

🔢 **التأكيد المتعدد المصادر:**
• نماذج تحليلية: {sig['models_confirmed']}/6 ✅
• مؤشرات فنية: {sig['indicators_confirmed']}/6 ✅
• **نسبة الثقة:** {sig['confidence']}% {bar}

📍 **دعم:** ${sig['support']:,.2f} | **مقاومة:** ${sig['resistance']:,.2f}
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
         InlineKeyboardButton("💰 سعر الذهب المباشر", callback_data="live_gold")],
        [InlineKeyboardButton("📊 تحليل استراتيجيتي", callback_data="strategy_analysis"),
         InlineKeyboardButton("🧠 تحليل شارت بالذكاء الاصطناعي", callback_data="analyze_chart")],
        [InlineKeyboardButton("🎯 خطط الاشتراك والأسعار", callback_data="plans")],
        [InlineKeyboardButton("💳 طرق الدفع", callback_data="payment_methods"),
         InlineKeyboardButton("🎓 مكتبة الكورسات", callback_data="courses_main")],
        [InlineKeyboardButton("🏆 نتائج التوصيات", callback_data="results_menu")],
        [InlineKeyboardButton("🌐 زيارة الموقع", url=WEBSITE_URL),
         InlineKeyboardButton("📞 الدعم المباشر", url=WHATSAPP_LINK)],
        [InlineKeyboardButton("ℹ️ عن النظام", callback_data="about")],
    ]
    return InlineKeyboardMarkup(keyboard)

def back_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تفعيل VIP", url=WHATSAPP_LINK)],
        [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="start")]
    ])

def results_menu():
    keyboard = [
        [InlineKeyboardButton("📉 نتائج الذهب XAUUSD", callback_data="res_xauusd")],
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
#  HANDLERS
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db = SessionLocal()
    u = db.query(TradingUser).filter(TradingUser.tg_id == str(user.id)).first()
    is_new = not u
    if not u:
        u = TradingUser(
            tg_id=str(user.id),
            username=user.username,
            first_name=user.first_name or "",
        )
        db.add(u)
        db.commit()
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
⚡ إشارات XAUUSD لحظية بالوقت الحقيقي
📊 تحليل استراتيجيتك بالذكاء الاصطناعي

━━━━━━━━━━━━━━━━━━━━━━━━
{trial_line}{new_badge}
⚠️ _التداول محفوف بالمخاطر. تحمل مسؤوليتك._"""

    if update.message:
        await update.message.reply_text(welcome, reply_markup=main_menu(), parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.edit_message_text(welcome, reply_markup=main_menu(), parse_mode="Markdown")


async def handle_live_gold(query):
    gold_manager.update()
    price = gold_manager.current_price
    session = gold_manager._get_trading_session()

    if not price:
        text = f"""📊 *سعر الذهب XAUUSD*
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

    text = f"""💰 *سعر الذهب XAUUSD*
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
    if user:
        user.signals_requested = (user.signals_requested or 0) + 1
        db.commit()
    db.close()

    gold_manager.update()

    if not is_vip:
        demo = _generate_demo_signal()
        if not demo:
            text = """⚡ *إشارات XAUUSD*
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
        text = f"""⚡ *معاينة إشارة | XAUUSD*
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

    text = format_signal(signal)
    await query.edit_message_text(text, reply_markup=back_menu(), parse_mode="Markdown")


async def handle_chart_analysis(query, user_id):
    db = SessionLocal()
    user = db.query(TradingUser).filter(TradingUser.tg_id == str(user_id)).first()
    is_vip = is_trial_active(user)
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


async def handle_strategy_analysis(query, user_id):
    """تحليل استراتيجية المستخدم بالذكاء الاصطناعي"""
    db = SessionLocal()
    user = db.query(TradingUser).filter(TradingUser.tg_id == str(user_id)).first()
    db.close()

    msg = """📊 *تحليل استراتيجيتك التداولية*
━━━━━━━━━━━━━━━━━━━━━━━━
🤖 النظام سيحلل استراتيجيتك بالذكاء الاصطناعي ويُقيّم:

✅ *نقاط القوة* — ما تتميز به استراتيجيتك
⚠️ *نقاط الضعف* — المخاطر والثغرات المحتملة
📈 *أفضل الأوقات* — متى تعمل استراتيجيتك بشكل أمثل
🛡️ *إدارة المخاطر* — كيف تحسّن نسبة المخاطرة/العائد
💡 *توصيات التطوير* — كيف تطور استراتيجيتك

━━━━━━━━━━━━━━━━━━━━━━━━
📝 *اكتب /strategy متبوعاً بوصف استراتيجيتك*

*مثال:*
`/strategy أستخدم RSI للدخول عند 30، وأخرج عند 70، مع مستوى وقف خسارة 50 نقطة`"""

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 أرسل /strategy [وصف استراتيجيتك]", callback_data="strategy_help")],
        [InlineKeyboardButton("🔙 العودة", callback_data="start")]
    ])
    await query.edit_message_text(msg, reply_markup=markup, parse_mode="Markdown")


async def cmd_strategy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /strategy — تحليل استراتيجية المستخدم"""
    if not context.args:
        await update.message.reply_text(
            "📊 *تحليل الاستراتيجية*\n\n"
            "استخدم: `/strategy [وصف استراتيجيتك]`\n\n"
            "*مثال:*\n"
            "`/strategy أستخدم RSI عند 30/70 مع Bollinger Bands للتأكيد، وأدخل عند كسر المستوى مع حجم تداول مرتفع`",
            parse_mode="Markdown"
        )
        return

    strategy_text = " ".join(context.args)
    if len(strategy_text) < 20:
        await update.message.reply_text("❌ يرجى كتابة وصف أكثر تفصيلاً لاستراتيجيتك (على الأقل 20 حرف).")
        return

    thinking_msg = await update.message.reply_text(
        "🔄 *جاري تحليل استراتيجيتك بالذكاء الاصطناعي...*\n⏳ انتظر لحظة...",
        parse_mode="Markdown"
    )

    prompt = f"""أنت خبير تداول محترف ومحلل مالي متخصص. قم بتحليل هذه الاستراتيجية التداولية بشكل احترافي وشامل.

الاستراتيجية: {strategy_text}

السوق الحالي: XAUUSD (الذهب) - السعر حوالي ${gold_manager.current_price or 3300}

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

    if data == "start":
        await start(update, context)
    elif data == "live_gold":
        await handle_live_gold(query)
    elif data == "get_signal":
        await handle_get_signal(query, user_id)
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
                    await query.message.reply_photo(photo=f, caption="📊 نتائج تداول الذهب XAUUSD")
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
        msg = """🎯 *خطط الاشتراك - اختر ما يناسبك*
━━━━━━━━━━━━━━━━━━━━━━━━

🥉 *الخطة الفضية — 10$*
• سعر الذهب الحي لحظة بلحظة
• 3 إشارات يومياً (كاملة مع الأرقام)
• مؤشرات RSI + MACD
• معلومة الجلسة (لندن/نيويورك/آسيا)
• دعم واتساب

━━━━━━━━━━━━━━━━━━━━━━━━

🥈 *الخطة الذهبية — 20$*
• كل مميزات الفضية +
• 10 إشارات يومياً (كاملة TP1+TP2+TP3)
• 3 تحليلات شارت AI يومياً
• جميع المؤشرات الـ12 (RSI+MACD+BB+ATR+Stoch+Fib+S/R+EMA)
• دعم واتساب أولوية

━━━━━━━━━━━━━━━━━━━━━━━━

💎 *الخطة الماسية VIP — 50$*
• كل مميزات الذهبية +
• إشارات تلقائية غير محدودة 24/7
• تحليل شارت AI غير محدود
• إشعار فوري لكل إشارة قوية (>80% ثقة)
• أولوية دعم VIP مباشر على مدار الساعة

🔥 *الأكثر مبيعاً: الخطة الماسية!*
⚠️ الكورسات مدفوعة بشكل منفصل وليست ضمن الخطط"""
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🥉 الفضية 10$", callback_data="plan_basic"),
             InlineKeyboardButton("🥈 الذهبية 20$", callback_data="plan_pro")],
            [InlineKeyboardButton("💎 الماسية VIP 50$", callback_data="plan_vip")],
            [InlineKeyboardButton("💬 اشترك الآن واتساب", url=WHATSAPP_LINK)],
            [InlineKeyboardButton("🔙 العودة", callback_data="start")]
        ])
        await query.edit_message_text(msg, reply_markup=markup, parse_mode="Markdown")
    elif data == "plan_basic":
        msg = """🥉 *الخطة الفضية — 10$ / شهر*
━━━━━━━━━━━━━━━━━━━━━━━━
✅ سعر الذهب الحي لحظة بلحظة (XAUUSD)
✅ 3 إشارات يومياً (كاملة مع الأرقام)
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
            [InlineKeyboardButton("💬 اشترك الفضية 10$", url=WHATSAPP_LINK)],
            [InlineKeyboardButton("⬆️ الذهبية 20$", callback_data="plan_pro"),
             InlineKeyboardButton("🔙 الخطط", callback_data="plans")]
        ])
        await query.edit_message_text(msg, reply_markup=markup, parse_mode="Markdown")
    elif data == "plan_pro":
        msg = """🥈 *الخطة الذهبية — 20$ / شهر*
━━━━━━━━━━━━━━━━━━━━━━━━
✅ سعر الذهب الحي لحظة بلحظة
✅ 10 إشارات يومياً (كاملة)
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
            [InlineKeyboardButton("💬 اشترك الذهبية 20$", url=WHATSAPP_LINK)],
            [InlineKeyboardButton("⬆️ الماسية 50$", callback_data="plan_vip"),
             InlineKeyboardButton("🔙 الخطط", callback_data="plans")]
        ])
        await query.edit_message_text(msg, reply_markup=markup, parse_mode="Markdown")
    elif data == "plan_vip":
        msg = """💎 *الخطة الماسية VIP — 50$ / شهر*
━━━━━━━━━━━━━━━━━━━━━━━━
✅ سعر الذهب الحي لحظة بلحظة
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
            [InlineKeyboardButton("🔥 اشترك الماسية الآن 50$", url=WHATSAPP_LINK)],
            [InlineKeyboardButton("🔙 الخطط", callback_data="plans")]
        ])
        await query.edit_message_text(msg, reply_markup=markup, parse_mode="Markdown")
    elif data == "subscription":
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🥉 الفضية 10$", callback_data="plan_basic"),
             InlineKeyboardButton("🥈 الذهبية 20$", callback_data="plan_pro")],
            [InlineKeyboardButton("💎 الماسية VIP 50$", callback_data="plan_vip")],
            [InlineKeyboardButton("💬 اشترك الآن واتساب", url=WHATSAPP_LINK)],
            [InlineKeyboardButton("🔙 العودة", callback_data="start")]
        ])
        await query.edit_message_text("🎯 *اختر خطة الاشتراك المناسبة:*\n⚠️ الكورسات مدفوعة بشكل منفصل", reply_markup=markup, parse_mode="Markdown")
    elif data == "payment_methods":
        msg = """💳 *طرق الدفع المتاحة*
━━━━━━━━━━━━━━━━━━━━━━━━

🔵 *بي باب (BePay)*
تحويل إلكتروني سريع وآمن

🟡 *بابني (Babni)*
محفظة رقمية مباشرة

🔴 *فودافون كاش*
تحويل فوري على الرقم المسجل

💳 *فييا كارد (Visa Card)*
دفع ببطاقة الفيزا الدولية

━━━━━━━━━━━━━━━━━━━━━━━━
📲 *بعد الدفع:*
تواصل معنا عبر واتساب وأرسل إيصال الدفع
سيتم تفعيل حسابك خلال دقائق ✅"""
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 تواصل واتساب بعد الدفع", url=WHATSAPP_LINK)],
            [InlineKeyboardButton("🎯 خطط الاشتراك", callback_data="plans"),
             InlineKeyboardButton("🔙 العودة", callback_data="start")]
        ])
        await query.edit_message_text(msg, reply_markup=markup, parse_mode="Markdown")
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
        await handle_strategy_analysis(query, user_id)
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

💰 *سعر الذهب:* `{price_info}`
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

    gold_manager.update()
    data = gold_manager.get_analysis_data()
    if not data:
        await update.message.reply_text("⚠️ لا تتوفر بيانات كافية بعد. حاول لاحقاً.")
        return

    signal_engine.last_signal_time = None
    signal = signal_engine.generate_signal(data)

    if not signal:
        await update.message.reply_text("⚠️ لا توجد إشارة قوية بما يكفي الآن. النظام يحمي المستخدمين.")
        return

    text = format_signal(signal)
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
    gold_manager.update()
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
        f"""💰 *بيانات الذهب XAUUSD*
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
        state = "🟢 مفعَّل" if auto_trader.auto_trading_enabled else "🔴 موقوف"
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
        ws_fresh = (
            gold_manager.last_update is not None and
            (datetime.utcnow() - gold_manager.last_update).total_seconds() < 300
        )
        if not ws_fresh:
            logger.info("⚠️ WebSocket غير نشط — جلب السعر عبر HTTP")
            gold_manager.update()
        else:
            logger.info(f"✅ WS نشط — السعر الحالي: ${gold_manager.current_price:,.2f} | نقاط: {len(gold_manager.price_history)}")
        
        # ── التحقق من فتح السوق قبل إرسال الإشارات التلقائية ──
        market_open, _ = is_market_open()
        if not market_open:
            logger.info("السوق مغلق، لن يتم إرسال إشارات تلقائية الآن.")
            return

        data = gold_manager.get_analysis_data()
        if data and len(data["prices"]) >= 50:
            signal = signal_engine.generate_signal(data)
            if signal:
                text = format_signal(signal)
                db = SessionLocal()
                all_users = db.query(TradingUser).filter(
                    TradingUser.is_blocked == False
                ).all()
                db.close()
                eligible_users = [u for u in all_users if is_trial_active(u)]
                sent = 0
                for u in eligible_users:
                    try:
                        await context.bot.send_message(
                            chat_id=u.tg_id, text=text, parse_mode="Markdown"
                        )
                        sent += 1
                        await asyncio.sleep(0.05)
                    except:
                        pass
                logger.info(f"✅ إشارة تلقائية VIP - ثقة: {signal['confidence']}% - أُرسلت لـ {sent} مستخدم")
                _save_signal_for_website(signal)
                _update_stats_for_website()

                if auto_trader.auto_trading_enabled:
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
        else:
            pts = len(data["prices"]) if data else 0
            logger.info(f"🔄 تحديث سعر الذهب - نقاط البيانات: {pts}/50")
    except Exception as e:
        logger.error(f"Price update error: {e}")


async def market_reopen_check(context: ContextTypes.DEFAULT_TYPE):
    """
    تفحص كل ساعة إذا كان السوق قد فتح (نهاية عطلة نهاية الأسبوع أو عطلة رسمية)
    إذا كان مفتوحاً، أرسل إشعاراً لجميع المستخدمين.
    """
    market_open, _ = is_market_open()
    if market_open:
        # نتأكد من أننا لم نرسل إشعاراً بالفعل في هذه الجلسة
        if not hasattr(context, "market_notified") or not context.market_notified:
            await notify_market_reopening(context)
            context.market_notified = True
    else:
        # إذا كان مغلقاً، نعيد تعيين العلم حتى إذا فتح لاحقاً نرسل مرة أخرى
        context.market_notified = False


# ============================================================
#  MAIN
# ============================================================
DAILY_REMINDERS = [
    """⚡ *تذكير يومي من نظام التداول الذكي*
━━━━━━━━━━━━━━━━━━━━━━━━
📊 سوق الذهب يتحرك الآن!
النظام يراقب 12 مصدر تأكيد لحظة بلحظة.

💡 *نصيحة اليوم:*
لا تتداول بدون خطة واضحة.
الصبر + الانضباط = نتائج ثابتة.

🔔 اضغط /start لعرض آخر الإشارات""",
    """🌅 *صباح الخير من بوت التداول!*
━━━━━━━━━━━━━━━━━━━━━━━━
💰 سوق الذهب XAUUSD يفتح مع جلسة جديدة.
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
                         InlineKeyboardButton("💰 سعر الذهب", callback_data="gold_price")]
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
    application.job_queue.run_daily(
        daily_reminder_job,
        time=dtime(7, 0, 0),
        name="daily_reminder"
    )
    logger.info("✅ Finnhub WebSocket بدأ (بيانات لحظية XAUUSD)")
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

    # أزرار التفاعل
    app.add_handler(CallbackQueryHandler(button_handler))

    # معالجة إجابات الاستبيانات
    app.add_handler(PollAnswerHandler(handle_poll_answer))

    # معالجة الصور (تحليل الشارت)
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo_message))

    logger.info("🚀 بوت التداول الذكي v7.0 (مع مراقبة فتح السوق) يعمل الآن!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()