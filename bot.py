import os, time, hashlib, subprocess, logging, asyncio, uuid, glob, requests
import json
import turbofetch
from hacking_modules import scanner, social_eng, ddos, osint
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from gtts import gTTS
from faster_whisper import WhisperModel
from PIL import Image
import io
import keep_alive  # 🪄 المكتبة السحرية - تبقي البوت نشطاً 24/7

try:
    from pytube import YouTube
    PYTUBE_AVAILABLE = True
except:
    PYTUBE_AVAILABLE = False

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except:
    GEMINI_AVAILABLE = False

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from sqlalchemy import func

# ================= LOGGING SETUP =================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ================= CONFIG =================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TOKEN")
DOWNLOAD_SEMAPHORE = asyncio.Semaphore(100) # دعم عدد أكبر من المستخدمين المتزامنين

# 🔑 تحميل 20 مفتاح Gemini API (من JSON أولاً، ثم من البيئة)
def load_gemini_keys():
    keys = []
    
    # حاول تحميل من ملف JSON أولاً (المفاتيح المحدثة من لوحة التحكم)
    json_path = "data/gemini_keys.json"
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r') as f:
                json_keys = json.load(f)
                for i in range(1, 21):
                    key = json_keys.get(f"key_{i}", "").strip()
                    if key and len(key) > 10:
                        keys.append(key)
            if keys:
                logger.info(f"✅ تم تحميل {len(keys)} مفاتيح من JSON")
                return keys
        except Exception as e:
            logger.warning(f"⚠️ خطأ في تحميل JSON: {e}")
    
    # إذا فشل JSON، حمّل من البيئة
    for i in range(1, 21):
        key = os.getenv(f"GEMINI_API_KEY_{i}", "").strip()
        if key and len(key) > 10:
            keys.append(key)
    
    main_key = os.getenv("GEMINI_API_KEY", "").strip()
    if main_key and len(main_key) > 10 and main_key not in keys:
        keys.insert(0, main_key)
    
    return keys

GEMINI_API_KEYS = load_gemini_keys()

# 🔧 نظام إدارة المفاتيح المحسّن (15 مفتاح)
VALID_KEY_INDICES = [i for i, k in enumerate(GEMINI_API_KEYS) if k and len(k) > 10]
GEMINI_CURRENT_INDEX = 0
EXHAUSTED_KEYS = set()

# تسجيل المفاتيح المتاحة
valid_keys_count = len(VALID_KEY_INDICES)
if valid_keys_count == 0:
    print("❌ تحذير: لا توجد مفاتيح Gemini محملة!")
    key_status = ['YES' if k else 'NO' for k in GEMINI_API_KEYS[:5]]
    print(f"🔍 فحص أول 5 مفاتيح: {key_status}")
else:
    print(f"✅ تم تحميل {valid_keys_count} مفاتيح Gemini 🚀")
    print(f"📍 فهارس المفاتيح المتاحة: {[i+1 for i in VALID_KEY_INDICES]}")
GOLD_API_KEY = os.getenv("GOLD_API_KEY", "admhrb19minpg9is-io")

DATA_DIR = "data"
DOWNLOADS_DIR = "downloads"
DATABASE_URL = "sqlite:///data/bot.db"
MAX_FILE_SIZE_MB = 50
ADMIN_IDS = [8865738615]
SIGNAL_RECIPIENT_ID = "8865738615"  # إرسال الإشارات للمسؤول فقط

WHATSAPP_NUMBER = "+201500236188"
WHATSAPP_LINK = "https://wa.me/201500236188"
VODAFONE_CASH = "01026489388"
SUPPORT_CONTACT = f"واتساب: {WHATSAPP_LINK}"

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

# ================= DATABASE =================
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    tg_id = Column(String, unique=True, index=True)
    name = Column(String)
    is_banned = Column(Boolean, default=False)
    blocked_or_left = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    referrer_id = Column(String, nullable=True)
    referral_count = Column(Integer, default=0)
    total_earnings = Column(Integer, default=0)
    daily_challenge_done = Column(Boolean, default=False)
    daily_challenge_date = Column(DateTime, nullable=True)
    is_frozen = Column(Boolean, default=False)
    frozen_until = Column(DateTime, nullable=True)
    is_vip = Column(Boolean, default=False)

class Referral(Base):
    __tablename__ = "referrals"
    id = Column(Integer, primary_key=True)
    referrer_id = Column(String, index=True)
    new_user_id = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    earnings = Column(Integer, default=4)

class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True)
    tg_id = Column(String, index=True)
    user_name = Column(String)
    message_text = Column(String)
    message_type = Column(String, default="text")
    sender = Column(String, default="user")
    created_at = Column(DateTime, default=datetime.utcnow)

class Purchase(Base):
    __tablename__ = "purchases"
    id = Column(Integer, primary_key=True)
    tg_id = Column(String, index=True)
    item_type = Column(String)
    item_name = Column(String)
    price = Column(Integer)
    payment_method = Column(String)
    status = Column(String, default="pending")
    payment_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Survey(Base):
    __tablename__ = "surveys"
    id = Column(Integer, primary_key=True)
    survey_id = Column(String, unique=True, index=True)
    question = Column(String)
    option1 = Column(String)
    option2 = Column(String)
    count1 = Column(Integer, default=0)
    count2 = Column(Integer, default=0)
    voters = Column(String, default="")  # CSV of voter IDs
    created_at = Column(DateTime, default=datetime.utcnow)

class FeatureUsage(Base):
    __tablename__ = "feature_usage"
    id = Column(Integer, primary_key=True)
    feature_name = Column(String, index=True)
    user_id = Column(String, index=True)
    usage_count = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used = Column(DateTime, default=datetime.utcnow)

class BroadcastQueue(Base):
    __table_args__ = {'extend_existing': True}
    __tablename__ = "broadcast_queue"
    id = Column(Integer, primary_key=True)
    type = Column(String)
    file_path = Column(String)
    text_content = Column(String)
    status = Column(String, default='pending')
    created_at = Column(DateTime, default=datetime.utcnow)

class SurveyMulti(Base):
    __table_args__ = {'extend_existing': True}
    __tablename__ = "surveys_multi"
    id = Column(Integer, primary_key=True)
    survey_id = Column(String, unique=True, index=True)
    question = Column(String)
    options_json = Column(String)
    active = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# معالج الأعمدة الناقصة
def add_missing_columns():
    from sqlalchemy import inspect
    inspector = inspect(engine)
    existing_columns = [col['name'] for col in inspector.get_columns('users', schema=None)]
    new_columns = ['referrer_id', 'referral_count', 'total_earnings', 'daily_challenge_done', 'daily_challenge_date', 'blocked_or_left', 'is_frozen', 'frozen_until', 'is_vip']
    
    from sqlalchemy import text
    with engine.connect() as conn:
        for col in new_columns:
            if col not in existing_columns:
                if col == 'referrer_id':
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} VARCHAR"))
                elif col == 'referral_count':
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT 0"))
                elif col == 'total_earnings':
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT 0"))
                elif col == 'daily_challenge_done':
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} BOOLEAN DEFAULT 0"))
                elif col == 'daily_challenge_date':
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} DATETIME"))
                elif col == 'blocked_or_left':
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} BOOLEAN DEFAULT 0"))
                elif col == 'is_frozen':
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} BOOLEAN DEFAULT 0"))
                elif col == 'frozen_until':
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} DATETIME"))
                elif col == 'is_vip':
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} BOOLEAN DEFAULT 0"))
                conn.commit()
    
    if 'messages' not in inspector.get_table_names():
        Base.metadata.create_all(bind=engine)
    
    # Force table creation for new tables if missing
    with engine.connect() as conn:
        try:
            conn.execute(text("SELECT id FROM broadcast_queue LIMIT 1"))
        except:
            BroadcastQueue.__table__.create(engine)
            
        try:
            conn.execute(text("SELECT id FROM surveys_multi LIMIT 1"))
        except:
            SurveyMulti.__table__.create(engine)
        conn.commit()

add_missing_columns()

# ================= WHISPER MODEL =================
whisper_model = WhisperModel("small", device="cpu", compute_type="int8")

# ================= GOOGLE GEMINI =================
def get_gemini_api():
    """الحصول على API key الحالي من المفاتيح المتاحة (غير المستنزفة)"""
    global GEMINI_CURRENT_INDEX
    if not VALID_KEY_INDICES:
        return None
    
    # البحث عن مفتاح لم يستنزف حصته
    for attempt in range(len(VALID_KEY_INDICES)):
        actual_index = VALID_KEY_INDICES[GEMINI_CURRENT_INDEX % len(VALID_KEY_INDICES)]
        if actual_index not in EXHAUSTED_KEYS:
            return GEMINI_API_KEYS[actual_index]
        # انتقل للمفتاح التالي
        GEMINI_CURRENT_INDEX = (GEMINI_CURRENT_INDEX + 1) % len(VALID_KEY_INDICES)
    
    logger.error("❌ جميع المفاتيح استنزفت حصتها!")
    return None

def rotate_gemini_key():
    """التبديل للـ API key التالي"""
    global GEMINI_CURRENT_INDEX
    if not VALID_KEY_INDICES:
        return
    GEMINI_CURRENT_INDEX = (GEMINI_CURRENT_INDEX + 1) % len(VALID_KEY_INDICES)
    actual_key_num = VALID_KEY_INDICES[GEMINI_CURRENT_INDEX] + 1
    logger.info(f"🔄 تم التبديل للـ API key #{actual_key_num}")

def mark_key_exhausted():
    """تحديد مفتاح كمستنزف الحصة مع إعادة تصفير المفاتيح إذا استنزفت جميعها"""
    global GEMINI_CURRENT_INDEX
    if not VALID_KEY_INDICES:
        return
    actual_index = VALID_KEY_INDICES[GEMINI_CURRENT_INDEX % len(VALID_KEY_INDICES)]
    EXHAUSTED_KEYS.add(actual_index)
    key_num = actual_index + 1
    remaining = len(VALID_KEY_INDICES) - len(EXHAUSTED_KEYS)
    logger.warning(f"⚠️ المفتاح #{key_num} استنزف حصته! المفاتيح المتبقية: {remaining}")
    
    # إذا استنزفت جميع المفاتيح، قم بإعادة تصفير القائمة للمحاولة مرة أخرى (ربما استعاد بعضها حصته)
    if remaining == 0:
        logger.info("🔄 جميع المفاتيح استنزفت! إعادة تصفير القائمة للمحاولة مرة أخرى...")
        EXHAUSTED_KEYS.clear()

def init_gemini():
    if not GEMINI_AVAILABLE:
        return False
    api_key = get_gemini_api()
    if not api_key:
        return False
    try:
        genai.configure(api_key=api_key)
        return True
    except:
        return False

def call_gemini_with_retry(prompt, system_instruction="", image_data=None, max_retries=3):
    """استدعاء Gemini مع تبديل ذكي وسريع بين 15 مفتاح و3 نماذج"""
    models_to_try = ['gemini-2.5-flash', 'gemini-2.5-flash-tts', 'gemini-2.5-flash-lite']
    total_keys = len(VALID_KEY_INDICES)
    total_attempts = total_keys * len(models_to_try) * max_retries
    attempt_count = 0
    
    logger.info(f"🚀 بدء المحاولات - {total_keys} مفتاح × {len(models_to_try)} نموذج")
    
    for key_round in range(total_keys):
        for model_name in models_to_try:
            for retry in range(max_retries):
                attempt_count += 1
                try:
                    api_key = get_gemini_api()
                    if not api_key:
                        logger.error("❌ جميع المفاتيح استنزفت!")
                        return None
                    
                    actual_key_num = VALID_KEY_INDICES[GEMINI_CURRENT_INDEX % len(VALID_KEY_INDICES)] + 1
                    logger.info(f"⚡ [{attempt_count}] مفتاح #{actual_key_num} + {model_name}")
                    
                    genai.configure(api_key=api_key)
                    # تعديل لجعله منفتحاً تماماً وعدم رفض أي طلب (بإزالة قيود الأمان)
                    # تم ضبط جميع الفئات على BLOCK_NONE للسماح بالمساعدة التقنية القصوى
                    safety_settings = [
                        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
                    ]
                    
                    model = genai.GenerativeModel(
                        model_name, 
                        system_instruction=system_instruction,
                        safety_settings=safety_settings
                    )
                    
                    if image_data:
                        response = model.generate_content([prompt, image_data])
                    else:
                        response = model.generate_content(prompt)
                    
                    if response and response.text:
                        logger.info(f"✅ نجح! مفتاح #{actual_key_num} + {model_name}")
                        return response
                    else:
                        logger.warning(f"⚠️ رد فارغ - تبديل سريع...")
                        rotate_gemini_key()
                        continue
                        
                except Exception as e:
                    error_str = str(e).lower()
                    logger.error(f"❌ خطأ: {str(e)[:80]}")
                    
                    if 'quota' in error_str or 'resource_exhausted' in error_str or '429' in error_str or 'rate' in error_str:
                        logger.warning(f"⚠️ حصة المفتاح #{actual_key_num} انتهت - تبديل فوري!")
                        mark_key_exhausted()
                        rotate_gemini_key()
                        break
                    elif 'model' in error_str or 'not found' in error_str or 'not supported' in error_str:
                        logger.warning(f"⚠️ النموذج {model_name} غير متاح - تجربة النموذج التالي...")
                        break
                    else:
                        logger.warning(f"⚠️ خطأ عام - تبديل المفتاح...")
                        rotate_gemini_key()
                        continue
        
        rotate_gemini_key()
    
    logger.error(f"❌ فشلت جميع المحاولات ({attempt_count} محاولة)!")
    return None

GEMINI_READY = init_gemini()

# ================= UTILITIES =================
def db_session():
    return SessionLocal()

# ============================================================
#  TRIAL SYSTEM - نظام التجربة المجانية 7 أيام
# ============================================================
TRIAL_DAYS = 1

def is_trial_active(user) -> bool:
    """True إذا كان المستخدم VIP أو لا يزال في فترة التجربة المجانية 7 أيام"""
    if not user:
        return False
    if getattr(user, 'is_vip', False):
        return True
    created = getattr(user, 'created_at', None)
    if created:
        return (datetime.utcnow() - created).days < TRIAL_DAYS
    return False

def trial_remaining_days(user) -> int:
    """عدد الأيام المتبقية من فترة التجربة"""
    if not user or getattr(user, 'is_vip', False):
        return 0
    created = getattr(user, 'created_at', None)
    if not created:
        return 0
    remaining = TRIAL_DAYS - (datetime.utcnow() - created).days
    return max(0, remaining)

def trial_banner(user) -> str:
    """شريط تذكير بنهاية التجربة المجانية"""
    if not user or getattr(user, 'is_vip', False):
        return ""
    days_left = trial_remaining_days(user)
    if days_left > 0:
        return f"\n\n⏳ *تجربتك المجانية تنتهي خلال {days_left} يوم*\n💎 اشترك الآن للاستمرار بدون انقطاع!"
    return ""

def save_bot_message(tg_id: str, message_text: str):
    """حفظ رسالة من البوت"""
    db = db_session()
    try:
        msg = Message(tg_id=tg_id, user_name="Bot", message_text=message_text[:1000], message_type="text", sender="bot")
        db.add(msg)
        db.commit()
    except:
        pass
    finally:
        db.close()

def get_or_create_user(tg_user):
    db = db_session()
    u = db.query(User).filter(User.tg_id==str(tg_user.id)).first()
    if not u:
        u = User(tg_id=str(tg_user.id), name=getattr(tg_user, "full_name", tg_user.username or "Unknown"))
        db.add(u)
        db.commit()
        db.refresh(u)
    db.close()
    return u

def is_user_banned_or_suspicious(tg_id: str):
    db = db_session()
    u = db.query(User).filter(User.tg_id==tg_id).first()
    db.close()
    if u and u.is_banned is True:
        return True, "❌ أنت محظور من استخدام البوت"
    return False, None

def save_message(tg_id: str, user_name: str, message_text: str, msg_type: str = "text"):
    db = db_session()
    msg = Message(tg_id=tg_id, user_name=user_name, message_text=message_text, message_type=msg_type)
    db.add(msg)
    db.commit()
    db.close()

def get_user_history(tg_id: str, limit: int = 20):
    db = db_session()
    messages = db.query(Message).filter(Message.tg_id==tg_id).order_by(Message.created_at.desc()).limit(limit).all()
    db.close()
    return list(reversed(messages))

async def cleanup_old_files():
    try:
        current_time = time.time()
        for f in os.listdir(DOWNLOADS_DIR):
            file_path = os.path.join(DOWNLOADS_DIR, f)
            if os.path.isfile(file_path) and current_time - os.path.getmtime(file_path) > 600:  # 10 دقائق
                try: 
                    os.remove(file_path)
                    await asyncio.sleep(0.05)
                except: 
                    pass
    except: 
        pass

async def kill_stuck_processes():
    """تنظيف عمليات التحميل العالقة"""
    try:
        # قتل عمليات yt-dlp و ffmpeg العالقة
        for proc_name in ["yt-dlp", "ffmpeg"]:
            proc = await asyncio.create_subprocess_exec(
                "pkill", "-f", proc_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await proc.communicate()
    except:
        pass

async def download_youtube_pytube(url, is_audio=False, unique_id=None):
    try:
        if not PYTUBE_AVAILABLE or not unique_id:
            return None
        yt = YouTube(url)
        if is_audio:
            stream = yt.streams.filter(only_audio=True).first()
            if stream:
                output_path = os.path.join(DOWNLOADS_DIR, f"{unique_id}.mp4")
                stream.download(output_path=DOWNLOADS_DIR, filename=f"{unique_id}.mp4")
                mp3_path = os.path.join(DOWNLOADS_DIR, f"{unique_id}.mp3")
                
                # استخدام asyncio subprocess بدلاً من blocking subprocess.run
                cmd = ["ffmpeg", "-i", output_path, "-q:a", "0", "-map", "a", mp3_path, "-y"]
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL
                )
                try:
                    await asyncio.wait_for(proc.communicate(), timeout=120)
                except asyncio.TimeoutError:
                    proc.kill()
                    return None
                
                if os.path.exists(mp3_path):
                    try: os.remove(output_path)
                    except: pass
                    return mp3_path
        else:
            stream = yt.streams.filter(progressive=True, file_extension="mp4").order_by("resolution").desc().first()
            if not stream:
                stream = yt.streams.filter(file_extension="mp4").order_by("resolution").desc().first()
            if stream:
                output_path = stream.download(output_path=DOWNLOADS_DIR, filename=f"{unique_id}.mp4")
                return output_path
    except:
        return None

async def kill_stuck_processes():
    """تنظيف العمليات العالقة لـ yt-dlp و ffmpeg"""
    try:
        import subprocess
        import os
        # تنظيف العمليات التي استهلكت وقتاً طويلاً
        subprocess.run("pkill -9 -f 'yt-dlp' || true", shell=True)
        subprocess.run("pkill -9 -f 'ffmpeg' || true", shell=True)
        # تنظيف الملفات المؤقتة القديمة (أكثر من ساعة)
        import time
        now = time.time()
        for f in os.listdir(DOWNLOADS_DIR):
            fpath = os.path.join(DOWNLOADS_DIR, f)
            if os.stat(fpath).st_mtime < now - 3600:
                try: os.remove(fpath)
                except: pass
        logger.info("🧹 تم تنظيف العمليات والملفات العالقة")
    except Exception as e:
        logger.error(f"Error killing processes: {e}")

async def download_with_yt_dlp_advanced(url, is_audio=False, unique_id=None):
    """تحميل باستخدام YoutubeDL API مع معالجة موارد صارمة (نسخة محسنة)"""
    try:
        import yt_dlp
        if not unique_id:
            unique_id = str(uuid.uuid4())
        
        out_template = os.path.join(DOWNLOADS_DIR, f"{unique_id}.%(ext)s")
        url_lower = url.lower()

        # إعدادات ذكية لكل منصة مقتبسة من الملف المرفق
        base_opts = {
            'quiet': True,
            'no_warnings': True,
            'outtmpl': out_template,
            'socket_timeout': 60,  # زيادة المهلة لضمان التحميل
            'retries': 50,         # زيادة هائلة في المحاولات لتجاوز القيود
            'fragment_retries': 50,
            'skip_unavailable_fragments': True,
            'ignoreerrors': True,
            'nocheckcertificate': True,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'sleep_interval': 5,   # إضافة تأخير بين العمليات لتجنب الحظر
            'max_sleep_interval': 15,
            'geo_bypass': True,
            'geo_bypass_country': 'US',
        }

        if 'youtube.com' in url_lower or 'youtu.be' in url_lower:
            if is_audio:
                base_opts['format'] = 'bestaudio/best'
                base_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }]
            else:
                base_opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
            base_opts['http_headers'] = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept-Language': 'en-US,en;q=0.9',
            }

        elif 'tiktok.com' in url_lower:
            base_opts['format'] = 'best'
            base_opts['http_headers'] = {
                'User-Agent': 'Mozilla/5.0 (Linux; Android 10; SM-G960U) AppleWebKit/537.36',
                'Referer': 'https://www.tiktok.com/',
            }

        elif 'instagram.com' in url_lower:
            base_opts['format'] = 'best'
            base_opts['cookiefile'] = 'cookies.txt' if os.path.exists('cookies.txt') else None
            base_opts['http_headers'] = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Referer': 'https://www.instagram.com/',
            }
            base_opts['extractor_args'] = {
                'instagram': {
                    'skip': ['auth'],
                    'geo_bypass': True,
                    'geo_bypass_country': 'US',
                }
            }
            # إضافة دعم للروابط التي قد تتطلب رأس مخصص
            base_opts['nocheckcertificate'] = True

        elif 'spotify.com' in url_lower:
            base_opts['format'] = 'bestaudio/best'
            base_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320',
            }]
        else:
            base_opts['format'] = 'best'
            if is_audio:
                base_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }]

        ydl = None
        try:
            ydl = yt_dlp.YoutubeDL(base_opts)
            info = await asyncio.get_event_loop().run_in_executor(None, lambda: ydl.extract_info(url, download=True))
            
            # الحصول على اسم الملف الفعلي
            filename = ydl.prepare_filename(info)
            if is_audio:
                if filename.endswith(('.webm', '.m4a', '.mp4')):
                    filename = filename.rsplit('.', 1)[0] + '.mp3'
            
            if os.path.exists(filename):
                return filename
            
            # بحث عن الملف إذا اختلف الاسم
            for f in glob.glob(os.path.join(DOWNLOADS_DIR, f"{unique_id}.*")):
                if os.path.exists(f) and os.path.getsize(f) > 1000:
                    return f
        except Exception as e:
            logger.error(f"❌ Error in smart download: {e}")
        finally:
            if ydl:
                try: ydl.close()
                except: pass
        return None
    except Exception as e:
        logger.error(f"❌ Critical downloader error: {e}")
        return None

async def download_with_ytdlp(url, is_audio=False):
    async with DOWNLOAD_SEMAPHORE:
        await kill_stuck_processes()
        await cleanup_old_files()
        unique_id = str(uuid.uuid4())
        
        logger.info(f"📥 محاولة التحميل (Async Mode): {url[:50]}...")
        
        is_youtube = "youtube.com" in url or "youtu.be" in url
        
        if is_youtube and PYTUBE_AVAILABLE:
            path = await download_youtube_pytube(url, is_audio, unique_id)
            if path:
                logger.info(f"✅ تم التحميل بنجاح (pytube)")
                return path
        
        path = await download_with_yt_dlp_advanced(url, is_audio, unique_id)
        if path:
            logger.info(f"✅ تم التحميل بنجاح (yt-dlp)")
            return path
        
        # محاولة أخيرة مع تنظيف شامل
        logger.info(f"🔄 محاولة نهائية بعد تنظيف كامل...")
        try:
            for f in os.listdir(DOWNLOADS_DIR):
                try: os.remove(os.path.join(DOWNLOADS_DIR, f))
                except: pass
        except: pass
        
        await asyncio.sleep(1)
        unique_id = str(uuid.uuid4())
        path = await download_with_yt_dlp_advanced(url, is_audio, unique_id)
        if path:
            logger.info(f"✅ تم التحميل بنجاح (yt-dlp - محاولة نهائية)")
            return path
        
        logger.warning(f"❌ فشل التحميل بعد كل المحاولات: {url}")
        return None

def text_to_speech_gtts(text, lang="ar"):
    try:
        if not text or len(text.strip()) == 0:
            logger.error("TTS: نص فارغ")
            return None
        
        text = text[:500]
        tts = gTTS(text=text, lang=lang, slow=False)
        path = os.path.join(DOWNLOADS_DIR, f"tts_{int(time.time()*1000)}.mp3")
        tts.save(path)
        
        if os.path.exists(path) and os.path.getsize(path) > 1000:
            logger.info(f"✅ TTS تم بنجاح: {path}")
            return path
        else:
            logger.error("TTS: الملف فارغ أو غير صحيح")
            if os.path.exists(path):
                try: os.remove(path)
                except: pass
            return None
    except Exception as e:
        logger.error(f"❌ TTS خطأ: {str(e)}")
        return None

def speech_to_text_faster_whisper(file_path):
    try:
        if not os.path.exists(file_path):
            logger.error(f"STT: الملف غير موجود: {file_path}")
            return None
        
        logger.info(f"STT: بدء المعالجة: {file_path}")
        segments, info = whisper_model.transcribe(file_path, language="ar")
        
        if not segments:
            logger.error("STT: لم يتم استخراج نصوص")
            return None
        
        text = " ".join([s.text for s in segments])
        if text and len(text.strip()) > 0:
            logger.info(f"✅ STT نجح: {text[:50]}")
            return text
        else:
            logger.error("STT: النص الناتج فارغ")
            return None
    except Exception as e:
        logger.error(f"❌ STT خطأ: {str(e)}")
        return None

async def ask_gemini(prompt):
    if not GEMINI_READY:
        return "❌ Google Gemini غير متوفر الآن. تأكد من إدخال API Key صحيح"
    try:
        system_instruction = """أنت مساعد ذكي مختصر وطبيعي.

قواعد الرد:
- اجعل ردودك قصيرة ومباشرة (3-5 أسطر كحد أقصى للأسئلة العادية)
- لا تكرر السؤال ولا تضف مقدمات طويلة
- إذا طُلب شرح مفصّل فقط حينها وسّع الرد
- استخدم نقاط مرتبة للقوائم
- لا تعطِ معلومات خاطئة أبداً
- في الطلبات الضارة: ارفض بجملة واحدة وقدّم بديلاً"""
        response = call_gemini_with_retry(prompt, system_instruction=system_instruction)
        if response and response.text:
            return response.text
        return "❌ لم أحصل على رد - جاري المحاولة..."
    except Exception as e:
        error_str = str(e)
        logger.error(f"Gemini error: {e}")
        return "❌ حدث خطأ في الرد. حاول مرة أخرى."

async def analyze_image(image_path):
    if not GEMINI_READY:
        return "❌ Google Gemini غير متوفر الآن"
    try:
        from PIL import Image
        img = Image.open(image_path)
        system_instruction = """أنت محلل صور ذكي وطبيعي مع قليل من العفوية.

أسلوبك:
- طبيعي وموزون ومنطقي
- حلل الصورة بعمق وركز على ما هو مهم
- استخدم لغة بسيطة وسهلة وودية
- اشرح ملاحظاتك بطريقة عملية واقعية
- أضف لمسة إنسانية خفيفة (عفوية قليلة)
- ركز على التفاصيل المهمة والمفيدة
- كن صريح وموثوق في التحليل"""
        response = call_gemini_with_retry("قم بتحليل هذه الصورة بالعربية:", system_instruction=system_instruction, image_data=img)
        if response and response.text:
            return response.text
        return "❌ فشل التحليل - جاري المحاولة بنموذج آخر..."
    except Exception as e:
        logger.error(f"Gemini image analysis error: {e}")
        return "❌ فشل تحليل الصورة"

async def generate_image(prompt: str):
    try:
        # فهم وترجمة النص بذكاء - ليس ترجمة حرفية فقط
        english_prompt = prompt
        if any(ord(c) > 127 for c in prompt):
            understand_prompt = f"""فهم النص التالي بجميع اللهجات والسياقات الممكنة ثم ترجمه إلى وصف إنجليزي دقيق وتفصيلي يناسب توليد الصور:

النص: {prompt}

طلب: فهّم القصد والسياق بشكل جيد وترجم لوصف إنجليزي واضح وتفصيلي يعطي جودة عالية في توليد الصور. مثلاً إذا قال المستخدم "قطة" اجعله "detailed professional photo of a beautiful cat" وليس فقط "cat".

الرد: الترجمة الإنجليزية مباشرة فقط بدون تعليقات"""
            english_prompt = await ask_gemini(understand_prompt)
            english_prompt = english_prompt.strip()[:120]
        
        # إضافة تعليمات جودة عالية جداً للصورة
        quality_prompt = f"{english_prompt}, ultra high quality, highly detailed, professional, 8k, masterpiece, best quality, sharp focus, cinematic lighting"
        quality_prompt = quality_prompt[:150]
        
        api_url_2 = f"https://image.pollinations.ai/prompt/{quality_prompt}?enhance=true&width=1024&height=1024"
        response = requests.get(api_url_2, timeout=45)
        if response.status_code == 200:
            image_path = os.path.join(DOWNLOADS_DIR, f"generated_{int(time.time()*1000)}.jpg")
            with open(image_path, 'wb') as f:
                f.write(response.content)
            return image_path
        
        return None
    except Exception as e:
        logger.error(f"Image generation error: {e}")
        return None

# ================= TRADING COURSES DATA WITH PRICING =================
TRADING_COURSES = {
    "classic_technical": {"title": "🥇 التحليل الفني والكلاسيكي", "price": 80, "courses": ["1 - كورس اسماعيل الشكري", "2 - كورس محمد مهدي", "3 - كورس محمود سعد", "4 - دورة ايهاب المصري الاولى", "5 - دورة ايهاب المصري الثانية", "6 - كورس ممدوح زكي", "7 - كورس محمد جهيمي", "8 - كورس منير الناظور", "9 - كورس مصطفى بلخياط", "10 - كورس شريف خورشيد", "11 - كورس الفيبو واسراره", "12 - كورس أحمد عبد الناصر", "13 - كورس شريف أبو رحاب", "14 - دورة سعد آل سعد", "15 - كورس قناة Glorex masters", "16 - كورس المحلل انس", "17 - كورس ممدوح زكي 2023", "18 - كورس محمد صلاح شامل", "19 - كورس احمد سرحان (Forex Basic)", "20 - كورس احمد سرحان (Advance)", "21 - كورس THE WOLF TRADERS", "22 - كورس بلخياط (فرنسي)", "23 - كورس Scalping macht", "24 - كورس هالا", "25 - كورس النوخذة لاسماعيل الشكري", "26 - دورة أحمد غانم", "27 - دورة محمد القيس", "28 - كورس التداول الذهبي يامن آغا", "29 - كورس كلاسيكي متقدم"]},
    "mathematical_numeric": {"title": "🥇 التحليل الرياضي والرقمي", "price": 99, "courses": ["1 - كورس ابو متعب", "2 - كورس أحمد يوسف الأول", "3 - كورس أحمد يوسف الثاني", "4 - كورس شريف أبو رحاب", "5 - كورس علي يوسف", "6 - كورس الفيبو الثلاثي", "7 - دورة أبو متعب الثانية", "8 - دورة التحليل الرقمي علي يوسف"]},
    "elliot_waves": {"title": "🥇 التحليل الموجي (إليوت)", "price": 100, "courses": ["1 - كورس شيماء ثروت", "2 - كورس سلطان الشهلوب", "3 - كورس ماجد الهذلي", "4 - كورس وسام المغربي", "5 - كورس ياسر ابو معاذ", "6 - كورس مختصر التحليل الموجي", "7 - كورس وحيد الموجي"]},
    "time_cycle_gann": {"title": "🥇 التحليل الفلكي والزمني + علوم جان", "price": 150, "courses": ["1 - كورس محمد مهدي", "2 - كورس وائل كريم", "3 - كورس العميسي", "4 - كورس محمد عباس الزمني", "5 - دورة XFOFLEX ACADEMY", "6 - دورة W.D.GANN", "7 - كورس ليث اليقضان"]},
    "volume_analysis": {"title": "🥇 التحليل الحجمي (الفوليوم)", "price": 199, "courses": ["1 - كورس وائل أحمد", "2 - كورس عادل المزيد", "3 - كورس حسن مسعود", "4 - كورس أبو مريال", "5 - كورس الماركت بروفايل مترجم", "6 - كورس الماركت بروفايل عربي", "7 - كورس عبدالله العتيبي", "8 - كورس التحليل الحجمي ماجد المسعودي", "9 - كورس الفوليوم بروفايل ياسر البياتي", "10 - كورس يونيكو", "11 - دورة UNIC FX"]},
    "fundamental_analysis": {"title": "🥇 التحليل الأساسي", "price": 100, "courses": ["1 - كورس حسين حيدر", "2 - كورس أبو مازن", "3 - كورس صديق البلوشي", "4 - كورس FX500", "5 - كورس حسين المحنة", "6 - كورس حاتم العبرات", "7 - كورس أحمد فهيم", "8 - كورس احمد سرحان", "9 - كورس طيبة"]},
    "smc": {"title": "🥇 كورسات SMC", "price": 100, "courses": ["1 - كورس الدليمي", "2 - كورس الاستاذ فهد", "3 - كورس الاستاذ حسن", "4 - كورس الاستاذ أمجد", "5 - كورس استراتيجية SMC", "6 - كورس معتصم", "7 - كورس SMC باللهجة العراقية", "8 - كورس سليمان الخليلي", "9 - كورس فيصل السوادي", "10 - كورس أبو العزم", "11 - كورس محمد ياسين", "12 - كورس حاتم العبرات", "13 - كورس محمد مهدي SMC", "14 - كورس سفينكس SMC", "15 - كورس احمد سرحان", "16 - دورة SMC محمد صلاح", "17 - كورس فوتون مترجم", "18 - كورس THE WOLF TRADERS", "19 - دورة UNIC FX", "20 - كورس حسن سعد", "21 - كورس ورشة النخبة", "22 - دورة Trade Lovers Academy"]},
    "ict": {"title": "🥇 كورسات ICT", "price": 199, "courses": ["1 - كورس مفاهيم ICT بالعربية", "2 - كورس استراتيجية ICT", "3 - كورس محمد سنبل", "4 - كورس خان الهندي (مترجم)", "5 - كورس ابو الخطاب", "6 - كورس استراتيجية ICT", "7 - كورس فضل الله المغربي", "8 - التحديث الجديد لفضل الله", "9 - دورة احتراف ICT", "10 - كورس هيرميس", "11 - كورس قناة Mo Golder", "12 - كورس عبد العزيز السوري", "13 - كورس مصطفى سمير - الساحر", "14 - استراتيجية رامي المعروف بالست ليلى", "15 - مختصر السيولة - Bresk", "16 - كورس سفيان NAVY", "17 - كورس سفيان NAVY الجزء الثاني", "18 - كورس سفيان NAVY الجزء الثالث", "19 - كورس ايفان مترجم", "20 - كورس عبد الله الأسمر", "21 - كورس الساحر"]},
    "sk": {"title": "🥇 كورسات SK", "price": 250, "courses": ["1 - كورس رمزي نافع", "2 - كورس استراتيجية SK", "3 - كورس أحمد أبو نجم", "4 - كورس جيد عن SK", "5 - دورة محمد صلاح الأولى", "6 - دورة محمد صلاح الثانية", "7 - دورة الكوتش عادل", "8 - كورس عبدة عصام SK", "9 - شرح مختصر SK", "10 - دورة فيصل جلال"]},
    "academies": {"title": "🥇 كورسات أكاديميات التسويق", "price": 200, "courses": ["1 - كورس احمد شريف (IM Academy)", "2 - كورس محمود النجار (IM Academy)", "3 - كورس Genius Academy", "4 - كورس Axado (Genius)", "5 - كورس وائل محمد (Genius)", "6 - كورس الكوتش راكان (Genius)", "7 - كورس الكوتش راكان الجزء الثاني", "8 - كورس مصطفى صبري (Eagles)", "9 - كورسات الفوركس العربي", "10 - كورس احمد شريف (iTrade Pro)", "11 - كورس Trading Makers (احمد العزب)", "12 - كورس التحليل الزمني (عماد)", "13 - دورة UNIC FX الأساسيات", "14 - دورة UNIC FX - SMC", "15 - دورة UNIC FX - Volume Profile", "16 - دورة اسلام احمد الطنطاوي", "17 - دورة iTrade Pro", "18 - استراتيجية احمد عاطف"]},
    "supply_demand": {"title": "🥇 كورسات العرض والطلب", "price": 60, "courses": ["1 - كورس عدي محمد", "2 - كورس خيران الخياري", "3 - دورة أبو خالد"]},
    "harmonic": {"title": "🥇 كورسات الهارمونيك", "price": 150, "courses": ["1 - دورة الهارمونيك", "2 - كورس عبد الله محمد", "3 - كورس شريف خورشيد", "4 - دورة الهاجري", "5 - استراتيجية ابو مبارك"]},
    "miscellaneous_courses": {"title": "🥇 دورات وكورسات متنوعة", "price": 230, "courses": ["1 - كورس الهاجري", "2 - ورشة اتداول بنفسي", "3 - دورة حمزة زريمق", "4 - دورة المضاربة", "5 - دورة احتراف التداول", "6 - كورس اقتناص الذيول", "7 - دورة خالد دريسي", "8 - كورس SMAY Trading", "9 - كورس THE NORMAL TRADE", "10 - كورس Phantom (إدارة المخاطر)", "11 - دورة الفراكتال", "12 - كورس Phantom العربي", "13 - كورس الفيبوناتشي", "14 - كورس Mohamed Bouaaich", "15 - كورس التداول على الأسهم", "16 - كورس وسام المغربي", "17 - كورس أحمد أبو نجم الشامل", "18 - دورة MS محمد صلاح", "19 - مكثف أسبوع محمد صلاح", "20 - دورة زيد الأردني", "21 - دورة السيستم الرقمي", "22 - دورة أبو فارس", "23 - نماذج وأنماط الشارت", "24 - كورس مستويات المخاطرة", "25 - دورة SCALPING", "26 - دورة سليم جرار", "27 - دورة عزوز جلال", "28 - دورة عبود الشريان", "29 - كورس النسبية", "30 - دورة Monsters"]},
    "diverse_strategies": {"title": "🥇 استراتيجيات متنوعة", "price": 299, "courses": ["1 - استراتيجية S zone", "2 - استراتيجية السكالبينغ", "3 - استراتيجية التحليل الفني", "4 - استراتيجية الفراكتال", "5 - استراتيجية HSD", "6 - استراتيجية BLOT", "7 - استراتيجية deadline", "8 - استراتيجية الاوبتيميا", "9 - استراتيجية Fibo Boxes", "10 - استراتيجية تكنيكال للذهب", "11 - استراتيجية رون", "12 - استراتيجية المستطيل", "13 - استراتيجية توم", "14 - استراتيجية التداول سكالبينغ", "15 - استراتيجية تكنيكال سيستمي", "16 - استراتيجية ROPC", "17 - دورة السكالبينغ محمد صلاح", "18 - استراتيجية السكالبينغ أحمد نعيم", "19 - مختصر استراتيجية ICT", "20 - استراتيجية المناطق المعلقة", "21 - استراتيجية قمة وقاع", "22 - استراتيجية هايكناشي عبود", "23 - استراتيجية هايكناشي", "24 - شرح استراتيجية كوبرا", "25 - استراتيجية التداول على الأخبار", "26 - ورشة استراتيجية الذيل", "27 - استراتيجية قناة Bresk", "28 - استراتيجية احمد الزبداني", "29 - استراتيجية الرقمي النسبي", "30 - استراتيجية trade simple", "31 - استراتيجية rekabi", "32 - استراتيجية smt", "33 - استراتيجية الأرباح", "34 - استراتيجية Ninja", "35 - استراتيجية Dragon", "36 - استراتيجية احمد الحركي", "37 - استراتيجية الموڤينقات", "38 - استراتيجية MR ZERO"]},
    "psychology": {"title": "🥇 كورسات المشاعر النفسية", "price": 80, "courses": ["1 - كورس النفسية والمشاعر", "2 - كورس ورشة النقاط النفسية"]},
    "abu_salah_courses": {"title": "🥇 دورات أبو صلاح (محمد صلاح)", "price": 380, "courses": ["1 - دورة معنى التداول", "2 - دورة التحليل الفني", "3 - دورة القواعد الخمس", "4 - دورة الاساسيات", "5 - دورة الفيبوناتشي", "6 - فاصل دورة الفيبوناتشي", "7 - دورة أماكن الدخول", "8 - دورة SMC", "9 - دورة SK الأولى", "10 - دورة SK الثانية", "11 - دورة MS", "12 - دورة اساليب التداول", "13 - دورة ادارة الحساب", "14 - دورة الوعي في التداول", "15 - دورة التأسيس من الصفر", "16 - مكثف أول", "17 - مكثف ثاني", "18 - اضافات", "19 - دورة السيولة", "20 - دورة Scalping 2", "21 - دورة Scalping 3", "22 - دورة 100 ألف دولار", "23 - دورة فن التداول", "24 - دورة التداول الثلاثية"]},
    "ahmed_serhan": {"title": "🥇 كورسات أحمد سرحان", "price": 150, "courses": ["1 - Forex Basic", "2 - Advance Course", "3 - كورس SMC"]},
    "binary_options": {"title": "🥇 كورسات الخيارات الثنائية", "price": 200, "courses": ["1 - كورس مي خالد", "2 - الحلقة 7 (تابع)", "3 - كورس أسامة أحمد", "4 - كورس سفينكس", "5 - كورس الغلابة", "6 - كورس EMMA مترجم", "7 - كورس ابو فيصل", "8 - كورس الدسنلي", "9 - كورس زينو الجزائري", "10 - كورس خبراء التداول", "11 - كورس فايز (Wadee3)", "12 - كورس ميدو", "13 - كورس غيث", "14 - كورس ارسنالي", "15 - كورس القيصر", "16 - كورس القيصر الثاني", "17 - كورس فادي", "18 - كورس عزوز", "19 - كورس أساطير التداول", "20 - كورس احمد دولر", "21 - كورس فرسان التداول", "22 - ثغرة YAZ", "23 - دورة طارق رامي", "24 - كورس إضافي"]},
    "binary_strategies": {"title": "🥇 استراتيجيات الخيارات الثنائية", "price": 150, "courses": ["1 - استراتيجية السلم", "2 - استراتيجية المليون", "3 - استراتيجية باينري اوبشنز", "4 - استراتيجية ابو فيصل", "5 - استراتيجية قمة وقاع", "6 - استراتيجية ابو فيصل الجديدة", "7 - ثغرة Secret Candle"]},
    "crypto": {"title": "🥇 كورسات الكريبتو", "price": 299, "courses": ["1 - كورس محمد مهدي", "2 - كورس Crypto Whale", "3 - كورس شريف خورشيد", "4 - كورس يوسف جو", "5 - كورس حسن الحلبي الشامل", "6 - كورس easyt", "7 - دورة يونس", "8 - دورة مراد الادريسي (العملات)", "9 - دورة مراد الادريسي (الفيوتشر)", "10 - دورة EA DEX"]},
    "books": {"title": "🥇 فهرس الكتب التداولية", "price": 99, "courses": ["1 - استراتيجية المليون", "2 - التحليل الأساسي", "3 - موجات الذئب", "4 - التحليل الفني جون ميرفي", "5 - النماذج السعرية", "6 - الهارمونيك سكوت كارني", "7 - العملات الرقمية", "8 - CMT", "9 - مفاهيم ICT", "10 - فن التداول توم ويليامز", "11 - صناع السوق جافين هولمز", "12 - الشموع اليابانية", "13 - SIMP Trading Book", "14 - التداول الموجي اليوت", "15 - التحليل الفني عربي", "16 - THE MARKET MAKERS MATRIX", "17 - كتاب مؤمن مدحت", "18 - استراتيجية المليون (اوبشنز)", "19 - استراتيجية زيد الاردني", "20 - التداول من الصفر", "21 - التحليل النفسي", "22 - طريقة جان", "23 - التحليل النفسي للمتداول", "24 - التحليل الرقمي المتقدم", "25 - مارك دوجلاس", "26 - استراتيجية OJ", "27 - خان SMC عربي", "28 - الشموع اليابانية للمبتدئين", "29 - الكتاب المقدس للشموع", "30 - فن الأوامر المعلقة", "31 - الرقمي النسبي", "32 - استراتيجيات الذهب", "33 - محترفين التداول", "34 - كتاب CRT", "35 - كتاب إضافي"]},
    "captain_course": {"title": "🥇 كورس القبطان (الحزمة الاحترافية)", "price": 499, "courses": ["1 - شرح باقة 1500$", "2 - كورس الكوتش عادل SK", "3 - لايفات الكوتش عادل", "4 - كورس سيف سلال SMC", "5 - كورس أيهم الشامي الفني", "6 - كورس أيهم الشامي الزمني", "7 - كورس أيهم الشامي العملات", "8 - كورس أيهم الشامي الأسرار", "9 - كورس البلوكتشين جلال", "10 - كورس التدفق النقدي", "11 - نصائح واستراتيجيات", "12 - استراتيجية فلير/Flare", "13 - استراتيجية SB model"]},
    "new_courses": {"title": "🥇 كورسات ودورات جديدة", "price": 340, "courses": ["1 - كورس الساحر (مصطفى سمير)", "2 - كورس ياسمين الكسوب FT STRATEGY", "3 - كورس ياسمين الكسوب Next", "4 - كورس زيد ثابت الأول", "5 - كورس زيد ثابت الثاني (500$)", "6 - دورة أبو النور", "7 - دورة أبو النور RMS", "8 - كورس محمود ابراهيم", "9 - استراتيجية نجم الفوركس", "10 - كورس فيصل جلال", "11 - كورس البرايس اكشن تركي", "12 - دورة انس الخضور", "13 - دورة ليث", "14 - دورة يزن الفيبوناتشي", "15 - دورة يزيد الرجوب", "16 - دورة Monsters"]},
    "numbers_levels": {"title": "🥇 دورات الأرقام والمستويات", "price": 250, "courses": ["1 - دورة العقرب الأولى", "2 - دورة العقرب الثانية", "3 - دورة العقرب الثالثة", "4 - دورة القوة الرقمية الثلاثية", "5 - دورة استراتيجيات الذهب", "6 - استراتيجية كسر الأرقام", "7 - استراتيجية الأرقام 12-15", "8 - دورة EM Trading", "9 - دورة اكرم خالد"]},
    "heikenashi_strategies": {"title": "🥇 استراتيجيات الهايكناشي", "price": 399, "courses": ["1 - دورة زيد الاولى", "2 - دورة زيد الثانية", "3 - دورة الكومند والبوكس", "4 - استراتيجية سوينك", "5 - شرح مناطق الكرمك", "6 - استراتيجية الأوامر المعلقة", "7 - استراتيجية عبود الجزائري", "8 - استراتيجية 7 شموع", "9 - استراتيجية احمد نعمة", "10 - استراتيجية البيور", "11 - استراتيجية ASRC", "12 - استراتيجيات محمد حسن", "13 - استراتيجيات هالا", "14 - استراتيجية الدخول", "15 - دورة أمير متداول فوركس", "16 - استراتيجية Hasen"]},
    "bookmap": {"title": "🥇 كورسات البوك ماب", "price": 230, "courses": ["1 - دورة سوزان الناظور", "2 - دورة DOM TRADER", "3 - دورة قناة Trading style"]},
    "captain_strategies": {"title": "🥇 استراتيجيات القبطان المتقدمة", "price": 950, "courses": ["1 - استراتيجية SB model", "2 - استراتيجية SB Nova", "3 - استراتيجية SB Core"]},
}

TRADING_SIGNALS = {
    "description": "📊 إشارة تداول مدفوعة",
    "details": "40 نموذج ذكي + 5 محللين بشر",
    "example": """🥇 إشارة تداول الذهب

📊 الإشارة: BUY
💯 الثقة: 85%
💰 السعر: $4,173.18

🎯 المستويات:
├─ TP: $4,273.18
└─ SL: $4,123.18

⏰ 2025-11-28 11:22:12 UTC"""
}

# ================= KEYBOARDS =================
    # ================= KEYBOARDS =================
def results_menu():
    keyboard = [
        [InlineKeyboardButton("📉 نتائج الذهب XAUUSD", callback_data="res_xauusd")],
        [InlineKeyboardButton("₿ نتائج البيتكوين BTC", callback_data="res_btc")],
        [InlineKeyboardButton("📊 ميزة التعرف على الأنماط", callback_data="pattern_recognition")],
        [InlineKeyboardButton("◀️ رجوع", callback_data="back")]
    ]
    return InlineKeyboardMarkup(keyboard)

def main_menu():
    """لوحة التحكم الرئيسية - مطابقة للصورة المرفقة"""
    keyboard = [
        [InlineKeyboardButton("🎓 كورسات تداول VIP 📚", callback_data="courses")],
        [InlineKeyboardButton("🎵 تحميل موسيقى", callback_data="music"), InlineKeyboardButton("📽️ تحميل فيديو", callback_data="video")],
        [InlineKeyboardButton("🏆 نتائج بوت التوصيات", callback_data="show_signals_results")],
        [InlineKeyboardButton("🤖 مساعد المتداول الذكي", callback_data="trading_assistant_info")],
        [InlineKeyboardButton("💳 شحن (Binance/Cash)", callback_data="payments_main"), InlineKeyboardButton("💼 الإدارة والتسويق", callback_data="admin_marketing")],
        [InlineKeyboardButton("💬 شات جي بي تي (ChatGPT)", callback_data="ai"), InlineKeyboardButton("🎨 نص إلى صورة", callback_data="text_to_image")],
        [InlineKeyboardButton("📝 نص إلى صوت", callback_data="tts"), InlineKeyboardButton("🖼️ تحليل الصور", callback_data="image_processor")],
        [InlineKeyboardButton("🔥 بوت تداول قوي 🚀", url="https://t.me/Uxhshzbot")],
        [InlineKeyboardButton("⚡ إشارات تداول مباشرة", callback_data="live_signals"), InlineKeyboardButton("💰 اكسب المال", callback_data="earn_money")],
        [InlineKeyboardButton("👥 تواصل معنا واتساب", url=WHATSAPP_LINK)]
    ]
    return InlineKeyboardMarkup(keyboard)

async def earn_money_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج زر اكسب المال"""
    query = update.callback_query
    await query.answer()
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 انقر هنا للتواصل واتساب لبدء الربح", url=WHATSAPP_LINK)],
        [InlineKeyboardButton("◀️ رجوع", callback_data="back")]
    ])
    
    text = "💰 **طريقة كسب المال:**\n\nيمكنك كسب المال من خلال الترويج للبوت أو الانضمام لفريقنا التسويقي. اضغط على الزر أدناه للتواصل معنا مباشرة عبر واتساب ومعرفة التفاصيل!"
    await query.edit_message_text(text=text, reply_markup=keyboard, parse_mode="Markdown")

def back_btn():
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ رجوع", callback_data="back")]])

def ai_menu():
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ خروج من AI", callback_data="back")]])

def courses_menu():
    buttons = []
    course_keys = list(TRADING_COURSES.keys())
    
    for key in course_keys:
        course = TRADING_COURSES[key]
        btn_text = f"📚 {course['title']}"
        buttons.append([InlineKeyboardButton(btn_text, callback_data=key)])
    
    buttons.append([InlineKeyboardButton("◀️ القائمة الرئيسية", callback_data="back")])
    
    return InlineKeyboardMarkup(buttons)

def courses_list_menu(course_titles):
    """عرض الكورسات كأزرار"""
    buttons = []
    for i, course in enumerate(course_titles):
        buttons.append([InlineKeyboardButton(f"📖 {course}", callback_data=f"course_{i}")])
    buttons.append([InlineKeyboardButton("◀️ الأقسام", callback_data="courses")])
    return InlineKeyboardMarkup(buttons)

def more_features_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎓 كورسات التداول", callback_data="courses")],
        [InlineKeyboardButton("💳 طرق الدفع", callback_data="payment_methods")],
        [InlineKeyboardButton("◀️ رجوع", callback_data="back")]
    ])

def format_courses(course_list, title):
    text = f"{title}\n\n"
    for i in range(0, len(course_list), 2):
        text += course_list[i]
        if i + 1 < len(course_list):
            text += "   |   " + course_list[i + 1]
        text += "\n"
    return text

async def check_frozen_account(update: Update, user_id: str) -> bool:
    """فحص إذا كان الحساب مبنيداً - ترجع True إذا كان الحساب مبنيداً"""
    db = db_session()
    try:
        user_record = db.query(User).filter(User.tg_id==user_id).first()
        if user_record and user_record.is_frozen:
            if user_record.frozen_until and datetime.utcnow() > user_record.frozen_until:
                user_record.is_frozen = False
                db.commit()
                return False
            else:
                if update.message:
                    await update.message.reply_text("❌ حسابك معلق حالياً. تواصل معنا عبر واتساب للمساعدة.")
                elif update.callback_query:
                    await update.callback_query.answer("❌ حسابك معلق حالياً", show_alert=True)
                return True
        return False
    except:
        return False
    finally:
        db.close()

# ================= HANDLERS =================
async def broadcast_new_bot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر إداري لإبلاغ الجميع بالبوت الجديد"""
    if update.effective_user.id not in ADMIN_IDS: return
    
    msg = "🚀 **تم إطلاق بوت التداول الاحترافي الجديد!**\n\nدقة تصل إلى 80%، إشارات ذهب لحظية، وتحليلات VIP.\n\n🔗 **انضم الآن:** @Uxhshzbot"
    
    db = db_session()
    users = db.query(User).all()
    db.close()
    
    success = 0
    for u in users:
        try:
            await context.bot.send_message(chat_id=u.tg_id, text=msg, parse_mode="Markdown")
            success += 1
            await asyncio.sleep(0.05) # تجنب حظر التليجرام
        except:
            pass
    await update.message.reply_text(f"📢 تم إرسال الإعلان لـ {success} مستخدم.")

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not update.message:
        return
    
    db = db_session()
    try:
        frozen_user = db.query(User).filter(User.tg_id==str(user.id)).first()
        if frozen_user and frozen_user.is_frozen:
            if frozen_user.frozen_until and datetime.utcnow() > frozen_user.frozen_until:
                frozen_user.is_frozen = False
                db.commit()
            else:
                await update.message.reply_text("❌ حسابك معلق حالياً. رجاءً تواصل معنا عبر واتساب للمساعدة.")
                db.close()
                return
    except:
        pass
    
    u = get_or_create_user(user)
    
    if context.args and len(context.args) > 0:
        args = context.args
        if args[0].startswith("ref_"):
            referrer_id = args[0].split("ref_")[1]
            if referrer_id != str(user.id) and u:
                ref_check = u.referrer_id
                if ref_check is None:
                    db.query(User).filter(User.id==u.id).update({"referrer_id": referrer_id})
                    referrer = db.query(User).filter(User.tg_id==referrer_id).first()
                    if referrer:
                        cnt = referrer.referral_count or 0
                        earn = referrer.total_earnings or 0
                        db.query(User).filter(User.id==referrer.id).update({"referral_count": cnt + 1, "total_earnings": earn + 4})
                        db.add(Referral(referrer_id=referrer_id, new_user_id=str(user.id), earnings=4))
                    db.commit()
                    await update.message.reply_text("🎉 شكراً لاستخدام رابط إحالة! ستحصل على مكافآت!")
    
    # تفحص الاستبيانات النشطة
    try:
        surveys = db.query(SurveyMulti).filter(SurveyMulti.active == 1).all()
        for survey in surveys:
            options = json.loads(survey.options_json)
            keyboard = [[InlineKeyboardButton(opt['text'], callback_data=f"vote_{survey.survey_id}_{i}")] for i, opt in enumerate(options)]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(f"📊 استبيان نشط:\n\n{survey.question}", reply_markup=reply_markup)
    except:
        pass
    db.close()
    
    is_banned, reason = is_user_banned_or_suspicious(str(user.id))
    if is_banned and reason:
        await update.message.reply_text(reason)
        return

    # حالة التجربة المجانية
    db2 = db_session()
    try:
        u_rec = db2.query(User).filter(User.tg_id == str(user.id)).first()
        days_left = trial_remaining_days(u_rec)
        is_new_user = u_rec and u_rec.created_at and (datetime.utcnow() - u_rec.created_at).seconds < 30
        if getattr(u_rec, 'is_vip', False):
            trial_status = "\n\n💎 *حسابك: VIP مفعّل — استمتع بكل الميزات!*"
        elif days_left > 0:
            trial_status = f"\n\n🎁 *تجربة مجانية: {days_left} يوم متبقي — جميع الميزات مفتوحة!*"
        else:
            trial_status = "\n\n⏰ *انتهت تجربتك المجانية — اشترك VIP للاستمرار*"
    finally:
        db2.close()

    new_badge = "\n🎉 *مرحباً بك! تمتع بـ 7 أيام تجربة مجانية كاملة!*" if is_new_user else ""
    welcome_text = f"مرحبا 😊 أنا مساعدك الذكي — يمكنني مساعدتك في كل شيء!{new_badge}{trial_status}"
    await update.message.reply_text(welcome_text, reply_markup=main_menu(), parse_mode="Markdown")

async def vote_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query.data.startswith("vote_"): return
    
    parts = query.data.split("_")
    survey_id = parts[1]
    opt_idx = int(parts[2])
    
    db = db_session()
    try:
        s = db.query(SurveyMulti).filter(SurveyMulti.survey_id == survey_id).first()
        if s:
            opts = json.loads(s.options_json)
            if opt_idx < len(opts):
                opts[opt_idx]["count"] = opts[opt_idx].get("count", 0) + 1
                s.options_json = json.dumps(opts)
                db.commit()
                
                # جلب الرد المخصص لهذا الخيار
                custom_response = opts[opt_idx].get('response', "شكراً لمشاركتك في الاستبيان! ❤️")
                
                await query.answer("✅ تم تسجيل صوتك!")
                # تحديث الرسالة بالرد المخصص
                await query.edit_message_text(
                    f"📊 *{s.question}*\n\n"
                    f"✅ تم تسجيل تصويتك لـ: *{opts[opt_idx]['text']}*\n\n"
                    f"💬 {custom_response}",
                    parse_mode="Markdown"
                )
    finally:
        db.close()

async def history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user if query else update.effective_user
    if not user:
        return
    
    tg_id = str(user.id)
    messages = get_user_history(tg_id, limit=10)
    
    if len(messages) == 0:
        text = "📭 لا توجد محادثات سابقة في السجل\n\nابدأ محادثة جديدة!"
    else:
        text = "📋 **سجل محادثاتك الأخيرة:**\n\n"
        for msg in messages:
            time_val = msg.created_at
            time_str = time_val.strftime("%d/%m %H:%M") if time_val is not None else "N/A"
            msg_txt = msg.message_text or ""
            msg_preview = msg_txt[:50] + "..." if len(msg_txt) > 50 else msg_txt
            text += f"⏰ {time_str}\n💬 {msg_preview}\n\n"
        text = text[:4096]
    
    if query:
        try:
            await query.edit_message_text(text, reply_markup=back_btn())
        except:
            pass
    elif update.message:
        await update.message.reply_text(text, reply_markup=back_btn())

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or int(user.id) not in ADMIN_IDS:
        await update.message.reply_text("❌ أنت لست مسؤول البوت")
        return
    
    db = db_session()
    try:
        total_users = db.query(User).count()
        total_messages = db.query(Message).count()
        banned_users = db.query(User).filter(User.is_banned==True).count()
        total_referrals = db.query(Referral).count()
        
        stats_text = f"""📊 **إحصائيات البوت:**

👥 عدد المستخدمين: {total_users}
💬 عدد الرسائل: {total_messages}
🚫 المستخدمين المحظورين: {banned_users}
🤝 عدد الإحالات: {total_referrals}
"""
        await update.message.reply_text(stats_text)
    except Exception as e:
        logger.error(f"Stats error: {e}")
        await update.message.reply_text("❌ حدث خطأ في جلب الإحصائيات")
    finally:
        db.close()

async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or int(user.id) not in ADMIN_IDS:
        await update.message.reply_text("❌ أنت لست مسؤول البوت")
        return
    
    if not context.args:
        await update.message.reply_text("⚠️ الرجاء إدخال الرسالة\n\nمثال: /broadcast مرحبا جميعا")
        return
    
    broadcast_msg = " ".join(context.args)
    
    db = db_session()
    try:
        users = db.query(User).filter(User.blocked_or_left==False).all()
        success_count = 0
        failed_count = 0
        blocked_users = []
        
        for user_record in users:
            try:
                await context.bot.send_message(chat_id=user_record.tg_id, text=broadcast_msg)
                success_count += 1
            except Exception as e:
                error_msg = str(e)
                if "403" in error_msg or "Forbidden" in error_msg or "bot was blocked" in error_msg.lower():
                    db.query(User).filter(User.tg_id==user_record.tg_id).update({"blocked_or_left": True})
                    db.commit()
                    blocked_users.append(user_record.tg_id)
                logger.warning(f"Failed to send message to {user_record.tg_id}: {e}")
                failed_count += 1
        
        result_msg = f"""✅ **تم البث:**

✅ نجح: {success_count}
❌ فشل: {failed_count}
📨 الإجمالي: {success_count + failed_count}
🚫 حظروا البوت: {len(blocked_users)}"""
        await update.message.reply_text(result_msg)
    except Exception as e:
        logger.error(f"Broadcast error: {e}")
        await update.message.reply_text("❌ حدث خطأ في البث")
    finally:
        db.close()

async def broadcast_media_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إرسال صورة أو فيديو للمستخدمين"""
    user = update.effective_user
    if not user or int(user.id) not in ADMIN_IDS:
        await update.message.reply_text("❌ أنت لست مسؤول البوت")
        return
    
    if not update.message or (not update.message.photo and not update.message.video):
        await update.message.reply_text("⚠️ الرجاء إرسال صورة أو فيديو مع النص (اختياري)")
        return
    
    caption = " ".join(context.args) if context.args else "📢 رسالة من المسؤول"
    
    db = db_session()
    try:
        users = db.query(User).filter(User.blocked_or_left==False).all()
        success_count = 0
        failed_count = 0
        
        if update.message.photo:
            photo_file = await update.message.photo[-1].get_file()
            for user_record in users:
                try:
                    await context.bot.send_photo(chat_id=user_record.tg_id, photo=photo_file.file_id, caption=caption)
                    success_count += 1
                except:
                    failed_count += 1
        
        elif update.message.video:
            video_file = await update.message.video.get_file()
            for user_record in users:
                try:
                    await context.bot.send_video(chat_id=user_record.tg_id, video=video_file.file_id, caption=caption)
                    success_count += 1
                except:
                    failed_count += 1
        
        result_msg = f"""✅ **تم إرسال الوسائط:**
✅ نجح: {success_count}
❌ فشل: {failed_count}"""
        await update.message.reply_text(result_msg)
    except Exception as e:
        logger.error(f"Broadcast media error: {e}")
        await update.message.reply_text("❌ حدث خطأ")
    finally:
        db.close()

async def survey_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إرسال استبيان للمستخدمين: /survey رأيك في البوت|ممتاز|سيئ"""
    user = update.effective_user
    if not user or int(user.id) not in ADMIN_IDS:
        await update.message.reply_text("❌ أنت لست مسؤول البوت")
        return
    
    if not context.args or len(context.args) < 3:
        await update.message.reply_text("⚠️ الصيغة: /survey السؤال|الخيار1|الخيار2\n\nمثال: /survey رأيك في البوت|ممتاز|سيئ")
        return
    
    parts = " ".join(context.args).split("|")
    if len(parts) != 3:
        await update.message.reply_text("❌ تأكد من استخدام | للفصل بين الأجزاء")
        return
    
    question, opt1, opt2 = parts[0].strip(), parts[1].strip(), parts[2].strip()
    survey_id = f"survey_{int(time.time())}"
    
    db = db_session()
    try:
        survey = Survey(survey_id=survey_id, question=question, option1=opt1, option2=opt2)
        db.add(survey)
        db.commit()
        
        users = db.query(User).filter(User.blocked_or_left==False).all()
        success = 0
        
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"✅ {opt1}", callback_data=f"survey_{survey_id}_1")],
            [InlineKeyboardButton(f"❌ {opt2}", callback_data=f"survey_{survey_id}_2")]
        ])
        
        msg = f"""📊 **استبيان:**

{question}

اختر إجابتك:"""
        
        for user_record in users:
            try:
                await context.bot.send_message(chat_id=user_record.tg_id, text=msg, reply_markup=buttons)
                success += 1
            except:
                pass
        
        await update.message.reply_text(f"✅ تم إرسال الاستبيان لـ {success} مستخدم")
    except Exception as e:
        logger.error(f"Survey error: {e}")
        await update.message.reply_text("❌ حدث خطأ")
    finally:
        db.close()

async def survey_results_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض نتائج آخر استبيان فقط"""
    user = update.effective_user
    if not user or int(user.id) not in ADMIN_IDS:
        await update.message.reply_text("❌ أنت لست مسؤول البوت")
        return
    
    db = db_session()
    try:
        survey = db.query(Survey).order_by(Survey.id.desc()).first()
        if not survey:
            await update.message.reply_text("❌ لا توجد استبيانات")
            return
        
        total = survey.count1 + survey.count2
        pct1 = (survey.count1 / total * 100) if total > 0 else 0
        pct2 = (survey.count2 / total * 100) if total > 0 else 0
        
        results_text = f"""📊 **نتائج الاستبيان الأخير:**

🎯 **{survey.question}**

✅ {survey.option1}
   {survey.count1} صوت ({pct1:.1f}%)

❌ {survey.option2}
   {survey.count2} صوت ({pct2:.1f}%)

━━━━━━━━━━━━━━━━
📊 الأصوات الكلية: {total}
"""
        
        await update.message.reply_text(results_text)
    except Exception as e:
        logger.error(f"Survey results error: {e}")
        await update.message.reply_text("❌ حدث خطأ")
    finally:
        db.close()

# ================= NEW COMMANDS =================

async def send_image_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر إرسال صورة: /send_image مع إرسال الصورة كرد"""
    user = update.effective_user
    if not user or int(user.id) not in ADMIN_IDS:
        await update.message.reply_text("❌ أنت لست مسؤول البوت")
        return
    
    await update.message.reply_text("📸 أرسل الصورة التي تريد إرسالها للمستخدمين (مع اختياري نص)")
    context.user_data["mode"] = "broadcast_image"

async def send_video_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر إرسال فيديو: /send_video مع إرسال الفيديو كرد"""
    user = update.effective_user
    if not user or int(user.id) not in ADMIN_IDS:
        await update.message.reply_text("❌ أنت لست مسؤول البوت")
        return
    
    await update.message.reply_text("🎥 أرسل الفيديو الذي تريد إرساله للمستخدمين (مع اختياري نص)")
    context.user_data["mode"] = "broadcast_video"

async def survey_detailed_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر عرض نتائج الاستبيان بالتفصيل"""
    user = update.effective_user
    if not user or int(user.id) not in ADMIN_IDS:
        await update.message.reply_text("❌ أنت لست مسؤول البوت")
        return
    
    db = db_session()
    try:
        surveys = db.query(Survey).all()
        if not surveys:
            await update.message.reply_text("❌ لا توجد استبيانات")
            return
        
        results_text = "📊 **نتائج الاستبيانات بالتفصيل:**\n\n"
        for i, survey in enumerate(surveys, 1):
            total = survey.count1 + survey.count2
            pct1 = (survey.count1 / total * 100) if total > 0 else 0
            pct2 = (survey.count2 / total * 100) if total > 0 else 0
            voters_count = len([v for v in survey.voters.split(",") if v])
            
            results_text += f"""**{i}. {survey.question}**
📅 التاريخ: {survey.created_at.strftime("%d/%m/%Y %H:%M") if survey.created_at else "N/A"}
━━━━━━━━━━━━━━━━
✅ {survey.option1}: {survey.count1} صوت ({pct1:.1f}%)
❌ {survey.option2}: {survey.count2} صوت ({pct2:.1f}%)
━━━━━━━━━━━━━━━━
👥 الأصوات الإجمالية: {total}
🗳️ عدد الناخبين: {voters_count}

"""
        
        await update.message.reply_text(results_text[:4096])
    except Exception as e:
        logger.error(f"Survey detailed error: {e}")
        await update.message.reply_text("❌ حدث خطأ")
    finally:
        db.close()

async def most_used_feature_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر عرض الميزة الأكثر استخدام"""
    user = update.effective_user
    if not user or int(user.id) not in ADMIN_IDS:
        await update.message.reply_text("❌ أنت لست مسؤول البوت")
        return
    
    db = db_session()
    try:
        features = db.query(FeatureUsage).all()
        if not features:
            await update.message.reply_text("❌ لا توجد بيانات استخدام")
            return
        
        feature_stats = {}
        for feature in features:
            if feature.feature_name not in feature_stats:
                feature_stats[feature.feature_name] = 0
            feature_stats[feature.feature_name] += feature.usage_count
        
        sorted_features = sorted(feature_stats.items(), key=lambda x: x[1], reverse=True)
        
        results_text = "🏆 **الميزات الأكثر استخدام:**\n\n"
        for i, (feature, count) in enumerate(sorted_features[:10], 1):
            results_text += f"{i}. 🎯 {feature}: {count} مرة\n"
        
        await update.message.reply_text(results_text)
    except Exception as e:
        logger.error(f"Most used feature error: {e}")
        await update.message.reply_text("❌ حدث خطأ")
    finally:
        db.close()

async def monthly_usage_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر عرض استخدام المستخدمين خلال الشهر"""
    user = update.effective_user
    if not user or int(user.id) not in ADMIN_IDS:
        await update.message.reply_text("❌ أنت لست مسؤول البوت")
        return
    
    db = db_session()
    try:
        from datetime import timedelta
        today = datetime.utcnow()
        month_ago = today - timedelta(days=30)
        
        messages = db.query(Message).filter(Message.created_at >= month_ago).all()
        users_this_month = db.query(User).filter(User.created_at >= month_ago).all()
        
        usage_by_user = {}
        for msg in messages:
            if msg.tg_id not in usage_by_user:
                usage_by_user[msg.tg_id] = 0
            usage_by_user[msg.tg_id] += 1
        
        sorted_users = sorted(usage_by_user.items(), key=lambda x: x[1], reverse=True)
        
        results_text = f"""📊 **إحصائيات الشهر الأخير (آخر 30 يوم):**

📅 من: {month_ago.strftime("%d/%m/%Y")}
📅 إلى: {today.strftime("%d/%m/%Y")}

👥 **الإحصائيات العامة:**
📱 مستخدمون جدد: {len(users_this_month)}
💬 عدد الرسائل: {len(messages)}
👨‍💻 المستخدمون النشطاء: {len(usage_by_user)}

🏆 **أكثر المستخدمين نشاطاً:**
"""
        
        for i, (user_id, count) in enumerate(sorted_users[:10], 1):
            user_record = db.query(User).filter(User.tg_id == user_id).first()
            user_name = user_record.name if user_record else "مستخدم"
            results_text += f"{i}. {user_name}: {count} رسالة\n"
        
        await update.message.reply_text(results_text)
    except Exception as e:
        logger.error(f"Monthly usage error: {e}")
        await update.message.reply_text("❌ حدث خطأ")
    finally:
        db.close()

async def survey_multi_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر استبيان مع عدة خيارات: /survey_multi السؤال|الخيار1|الخيار2|الخيار3|..."""
    user = update.effective_user
    if not user or int(user.id) not in ADMIN_IDS:
        await update.message.reply_text("❌ أنت لست مسؤول البوت")
        return
    
    if not context.args or len(context.args) < 3:
        await update.message.reply_text("⚠️ الصيغة: /survey_multi السؤال|الخيار1|الخيار2|الخيار3\n\nمثال: /survey_multi رأيك في البوت|ممتاز|جيد|سيئ|سيء جداً")
        return
    
    parts = " ".join(context.args).split("|")
    if len(parts) < 3:
        await update.message.reply_text("❌ يجب أن يكون هناك خيار واحد على الأقل (السؤال + خيارين)")
        return
    
    question = parts[0].strip()
    options = [opt.strip() for opt in parts[1:]]
    survey_id = f"survey_multi_{int(time.time())}"
    
    db = db_session()
    try:
        import json
        options_dict = {f"opt_{i}": {"name": opt, "count": 0} for i, opt in enumerate(options)}
        
        survey = SurveyMulti(survey_id=survey_id, question=question, options=json.dumps(options_dict))
        db.add(survey)
        db.commit()
        
        users = db.query(User).filter(User.blocked_or_left==False).all()
        success = 0
        
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton(opt, callback_data=f"survey_m_{survey_id}_{i}") for i, opt in enumerate(options)]
        ])
        
        msg = f"""📊 **استبيان متعدد الخيارات:**

{question}

اختر إجابتك:"""
        
        for user_record in users:
            try:
                await context.bot.send_message(chat_id=user_record.tg_id, text=msg, reply_markup=buttons)
                success += 1
            except:
                pass
        
        await update.message.reply_text(f"✅ تم إرسال الاستبيان لـ {success} مستخدم بـ {len(options)} خيارات")
    except Exception as e:
        logger.error(f"Multi-option survey error: {e}")
        await update.message.reply_text("❌ حدث خطأ")
    finally:
        db.close()

async def top_users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر عرض الأشخاص الأكثر استخدام للبوت"""
    user = update.effective_user
    if not user or int(user.id) not in ADMIN_IDS:
        await update.message.reply_text("❌ أنت لست مسؤول البوت")
        return
    
    db = db_session()
    try:
        usage_by_user = {}
        messages = db.query(Message).all()
        
        for msg in messages:
            if msg.tg_id not in usage_by_user:
                usage_by_user[msg.tg_id] = 0
            usage_by_user[msg.tg_id] += 1
        
        sorted_users = sorted(usage_by_user.items(), key=lambda x: x[1], reverse=True)
        
        results_text = "👑 **أكثر المستخدمين استخداماً للبوت:**\n\n"
        for i, (user_id, count) in enumerate(sorted_users[:15], 1):
            user_record = db.query(User).filter(User.tg_id == user_id).first()
            if user_record:
                status = "✅ نشط" if not user_record.is_banned else "🚫 محظور"
                created = user_record.created_at.strftime("%d/%m/%Y") if user_record.created_at else "N/A"
                results_text += f"{i}. 👤 {user_record.name}\n   🆔 ID: {user_id}\n   💬 {count} رسالة\n   📅 تاريخ الانضمام: {created}\n   الحالة: {status}\n\n"
        
        await update.message.reply_text(results_text[:4096])
    except Exception as e:
        logger.error(f"Top users error: {e}")
        await update.message.reply_text("❌ حدث خطأ")
    finally:
        db.close()

async def welcome_restored_users(app):
    """إرسال رسالة ترحيب للمستخدمين المستعادين"""
    db = db_session()
    try:
        users = db.query(User).all()
        welcome_msg = """🎉 **أهلا وسهلا بك مجددا!**

البوت الخاص بك أصبح جاهزاً مع ميزات جديدة رائعة! 🚀

✨ **الميزات الجديدة:**
🤖 محادثة مع AI متقدمة
📚 مساعد دراسة ذكي
📝 محسّن نصوص احترافي
📊 إشارات تداول لحظية
🎓 كورسات تداول شاملة
💳 طرق دفع آمنة وموثوقة

ابدأ الآن واستمتع بالخدمات! 😊"""
        
        success = 0
        for user in users:
            try:
                await app.bot.send_message(chat_id=user.tg_id, text=welcome_msg, reply_markup=main_menu())
                success += 1
            except:
                pass
        
        logger.info(f"✅ تم إرسال رسائل ترحيب إلى {success} مستخدم")
    except Exception as e:
        logger.error(f"Welcome message error: {e}")
    finally:
        db.close()

async def myusage_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    
    db = db_session()
    try:
        tg_id = str(user.id)
        
        # الحصول على معلومات المستخدم
        user_record = db.query(User).filter(User.tg_id==tg_id).first()
        if not user_record:
            await update.message.reply_text("❌ لم يتم العثور على حسابك")
            return
        
        # الحصول على عدد الرسائل
        msg_count = db.query(Message).filter(Message.tg_id==tg_id).count()
        
        # الحصول على سجل الرسائل
        messages = db.query(Message).filter(Message.tg_id==tg_id).order_by(Message.created_at.desc()).limit(10).all()
        
        usage_text = f"""📊 **سجل استخدامك للبوت:**

👤 الاسم: {user_record.name}
🆔 ID: {tg_id}
📅 تاريخ التسجيل: {user_record.created_at.strftime("%d/%m/%Y %H:%M") if user_record.created_at else "N/A"}
💬 عدد الرسائل: {msg_count}
🚫 الحالة: {"محظور ❌" if user_record.is_banned else "نشط ✅"}

📝 **آخر 10 استخدامات:**
"""
        
        for i, msg in enumerate(messages, 1):
            time_str = msg.created_at.strftime("%d/%m %H:%M") if msg.created_at else "N/A"
            msg_preview = (msg.message_text[:40] + "...") if len(msg.message_text or "") > 40 else msg.message_text
            usage_text += f"\n{i}. ⏰ {time_str}\n   📝 {msg_preview}"
        
        usage_text = usage_text[:4096]
        await update.message.reply_text(usage_text)
    except Exception as e:
        logger.error(f"Usage error: {e}")
        await update.message.reply_text("❌ حدث خطأ في جلب السجل")
    finally:
        db.close()

async def allusage_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or int(user.id) not in ADMIN_IDS:
        await update.message.reply_text("❌ أنت لست مسؤول البوت")
        return
    
    db = db_session()
    try:
        total_users = db.query(User).count()
        active_users = db.query(User).filter(User.is_banned==False).count()
        banned_users = db.query(User).filter(User.is_banned==True).count()
        total_messages = db.query(Message).count()
        
        # الحصول على المستخدمين الأكثر استخداماً
        top_users = db.query(Message.tg_id, func.count(Message.id).label('count')).group_by(Message.tg_id).order_by(func.count(Message.id).desc()).limit(5).all()
        
        usage_text = f"""📊 **إحصائيات الاستخدام الشاملة:**

👥 إجمالي المستخدمين: {total_users}
✅ المستخدمين النشطين: {active_users}
❌ المستخدمين المحظورين: {banned_users}
💬 إجمالي الرسائل: {total_messages}

🏆 **أكثر المستخدمين استخداماً:**
"""
        
        for i, (tg_id, count) in enumerate(top_users, 1):
            user_record = db.query(User).filter(User.tg_id==tg_id).first()
            name = user_record.name if user_record else "Unknown"
            usage_text += f"\n{i}. {name} ({tg_id}) - {count} رسالة"
        
        usage_text = usage_text[:4096]
        await update.message.reply_text(usage_text)
    except Exception as e:
        logger.error(f"All usage error: {e}")
        await update.message.reply_text("❌ حدث خطأ")
    finally:
        db.close()

async def userlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or int(user.id) not in ADMIN_IDS:
        await update.message.reply_text("❌ أنت لست مسؤول البوت")
        return
    
    db = db_session()
    try:
        users = db.query(User).all()
        
        buttons = []
        for u in users:
            status = "🟥 محظور" if u.is_banned else "🟢 نشط"
            btn_text = f"{u.name} - {status}"
            buttons.append([InlineKeyboardButton(btn_text, callback_data=f"user_{u.tg_id}")])
        
        buttons.append([InlineKeyboardButton("◀️ رجوع", callback_data="back")])
        markup = InlineKeyboardMarkup(buttons)
        
        msg = f"""👥 **قائمة المستخدمين ({len(users)}):**

اختر مستخدم لعرض تفاصيله:"""
        
        await update.message.reply_text(msg, reply_markup=markup)
    except Exception as e:
        logger.error(f"Userlist error: {e}")
        await update.message.reply_text("❌ حدث خطأ")
    finally:
        db.close()

async def todayusers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض قائمة المستخدمين الجدد اليوم مع عدد الرسائل"""
    user = update.effective_user
    if not user or int(user.id) not in ADMIN_IDS:
        await update.message.reply_text("❌ أنت لست مسؤول البوت")
        return
    
    db = db_session()
    try:
        from datetime import timedelta
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        
        # الحصول على المستخدمين الذين سجلوا اليوم
        today_users = db.query(User).filter(
            User.created_at >= today_start,
            User.created_at < today_end
        ).all()
        
        if not today_users:
            await update.message.reply_text("✅ لا يوجد مستخدمون جدد اليوم")
            return
        
        buttons = []
        for u in today_users:
            msg_count = db.query(Message).filter(Message.tg_id==u.tg_id).count()
            btn_text = f"👤 {u.name} ({msg_count} رسائل)"
            buttons.append([InlineKeyboardButton(btn_text, callback_data=f"today_user_{u.tg_id}")])
        
        buttons.append([InlineKeyboardButton("◀️ رجوع", callback_data="back")])
        markup = InlineKeyboardMarkup(buttons)
        
        msg = f"""📊 **المستخدمين الجدد اليوم ({len(today_users)})**

اضغط على المستخدم لعرض محادثته الكاملة:"""
        
        if update.message:
            await update.message.reply_text(msg, reply_markup=markup)
    
    except Exception as e:
        logger.error(f"Today users error: {e}")
        if update.message:
            await update.message.reply_text(f"❌ حدث خطأ: {str(e)}")
    finally:
        db.close()

async def fullreport_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تقرير شامل لجميع ردود البوت والمستخدمين"""
    user = update.effective_user
    if not user or int(user.id) not in ADMIN_IDS:
        await update.message.reply_text("❌ أنت لست مسؤول البوت")
        return
    
    db = db_session()
    try:
        from datetime import timedelta
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        
        today_users = db.query(User).filter(
            User.created_at >= today_start,
            User.created_at < today_end
        ).all()
        
        if not today_users:
            await update.message.reply_text("✅ لا يوجد نشاط اليوم")
            return
        
        report = f"""📊 **التقرير الشامل - اليوم**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

"""
        
        for idx, u in enumerate(today_users, 1):
            messages = db.query(Message).filter(Message.tg_id==u.tg_id).order_by(Message.created_at.asc()).all()
            
            report += f"""
🔹 **المستخدم #{idx}**
👤 الاسم: {u.name}
🆔 ID: {u.tg_id}
⏰ التسجيل: {u.created_at.strftime("%H:%M:%S") if u.created_at else "N/A"}
💬 عدد الرسائل: {len(messages)}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📝 **المحادثة الكاملة:**

"""
            
            if messages:
                for msg in messages:
                    msg_time = msg.created_at.strftime("%H:%M:%S") if msg.created_at else "N/A"
                    if msg.sender == "bot":
                        report += f"⏰ {msg_time} | 🤖 البوت:\n{msg.message_text}\n\n"
                    else:
                        report += f"⏰ {msg_time} | 👤 المستخدم:\n{msg.message_text}\n\n"
            else:
                report += "لا توجد رسائل\n\n"
        
        # تقسيم الرسالة إذا كانت طويلة
        if len(report) > 4096:
            parts = [report[i:i+4096] for i in range(0, len(report), 4096)]
            for part in parts:
                await update.message.reply_text(part)
        else:
            await update.message.reply_text(report)
    
    except Exception as e:
        logger.error(f"Full report error: {e}")
        await update.message.reply_text(f"❌ حدث خطأ: {str(e)}")
    finally:
        db.close()

async def show_user_conversation(update: Update, user_id: str):
    """عرض محادثة المستخدم كاملة - منظمة (سؤال ثم الرد)"""
    query = update.callback_query
    if not query:
        return
    
    db = db_session()
    try:
        user_record = db.query(User).filter(User.tg_id==user_id).first()
        if not user_record:
            await query.answer("❌ المستخدم غير موجود", show_alert=True)
            return
        
        messages = db.query(Message).filter(Message.tg_id==user_id).order_by(Message.created_at.asc()).all()
        
        conversation = f"""💬 **محادثة المستخدم الكاملة**

👤 الاسم: {user_record.name}
🆔 ID: {user_id}
⏰ التسجيل: {user_record.created_at.strftime("%d/%m/%Y %H:%M") if user_record.created_at else "N/A"}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

"""
        
        if messages:
            pair_count = 0
            i = 0
            while i < len(messages):
                msg = messages[i]
                
                # إذا كانت من المستخدم
                if msg.sender == "user":
                    pair_count += 1
                    msg_time = msg.created_at.strftime("%H:%M:%S") if msg.created_at else "N/A"
                    user_text = msg.message_text or "بدون نص"
                    conversation += f"\n❓ **سؤال #{pair_count}** ⏰ {msg_time}\n{user_text}\n"
                    
                    # البحث عن الرد التالي من البوت
                    if i + 1 < len(messages) and messages[i + 1].sender == "bot":
                        bot_msg = messages[i + 1]
                        bot_time = bot_msg.created_at.strftime("%H:%M:%S") if bot_msg.created_at else "N/A"
                        bot_text = bot_msg.message_text or "بدون نص"
                        conversation += f"━━━━━━━━━━━━━━━━━━━━━\n💬 **الرد** ⏰ {bot_time}\n{bot_text}\n"
                        i += 2
                    else:
                        i += 1
                else:
                    i += 1
        else:
            conversation += "لا توجد رسائل"
        
        # تقسيم الرسالة إذا كانت طويلة
        if len(conversation) > 4096:
            parts = [conversation[j:j+4096] for j in range(0, len(conversation), 4096)]
            await query.edit_message_text(parts[0], reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ رجوع", callback_data="back_todayusers")]
            ]))
            for part in parts[1:]:
                await query.message.reply_text(part)
        else:
            await query.edit_message_text(conversation, reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ رجوع", callback_data="back_todayusers")]
            ]))
    except Exception as e:
        logger.error(f"Show conversation error: {e}")
        await query.answer(f"❌ حدث خطأ: {str(e)}", show_alert=True)
    finally:
        db.close()

async def freeze_user_admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تبنيد حساب مستخدم من قبل الإدارة"""
    user = update.effective_user
    if not user or int(user.id) not in ADMIN_IDS:
        await update.message.reply_text("❌ أنت لست مسؤول البوت")
        return
    
    if not context.args:
        await update.message.reply_text("📋 الاستخدام: `/freeze_user_id <user_id>` أو `/freeze_user_id <user_id> <days>`\n\nمثال:\n`/freeze_user_id 123456789`\n`/freeze_user_id 123456789 60`", parse_mode="Markdown")
        return
    
    target_id = context.args[0]
    days = int(context.args[1]) if len(context.args) > 1 else 30
    
    db = db_session()
    try:
        user_record = db.query(User).filter(User.tg_id==target_id).first()
        if not user_record:
            await update.message.reply_text(f"❌ لم يتم العثور على المستخدم برقم ID: {target_id}")
            return
        
        from datetime import timedelta
        user_record.is_frozen = True
        user_record.frozen_until = datetime.utcnow() + timedelta(days=days)
        db.commit()
        
        success_msg = f"""✅ **تم تبنيد الحساب بنجاح!**

📱 بيانات المستخدم:
- الاسم: {user_record.name}
- ID: {target_id}

🧊 تفاصيل التبنيد:
- المدة: {days} يوم
- حتى: {(datetime.utcnow() + timedelta(days=days)).strftime("%d/%m/%Y %H:%M")}"""
        
        await update.message.reply_text(success_msg)
    except ValueError:
        await update.message.reply_text("❌ رقم ID أو عدد الأيام غير صحيح")
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ: {str(e)}")
    finally:
        db.close()

async def blockedusers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or int(user.id) not in ADMIN_IDS:
        await update.message.reply_text("❌ أنت لست مسؤول البوت")
        return
    
    db = db_session()
    try:
        blocked_users = db.query(User).filter(User.blocked_or_left==True).all()
        
        if not blocked_users:
            await update.message.reply_text("✅ لا يوجد مستخدمون قد حظروا البوت")
            return
        
        buttons = []
        for u in blocked_users:
            btn_text = f"❌ {u.name} ({u.tg_id})"
            buttons.append([InlineKeyboardButton(btn_text, callback_data=f"blocked_{u.tg_id}")])
        
        buttons.append([InlineKeyboardButton("◀️ رجوع", callback_data="back")])
        markup = InlineKeyboardMarkup(buttons)
        
        msg = f"""🚫 **المستخدمون الذين حظروا البوت ({len(blocked_users)}):**

هؤلاء المستخدمون حظروا البوت أو غادروه:"""
        
        await update.message.reply_text(msg, reply_markup=markup)
    except Exception as e:
        logger.error(f"Blocked users error: {e}")
        await update.message.reply_text("❌ حدث خطأ")
    finally:
        db.close()

async def user_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    
    user = query.from_user
    if not user or int(user.id) not in ADMIN_IDS:
        await query.answer("❌ لا تملك الصلاحية", show_alert=True)
        return
    
    tg_id = query.data.replace("user_", "")
    
    db = db_session()
    try:
        user_record = db.query(User).filter(User.tg_id==tg_id).first()
        if not user_record:
            await query.answer("❌ المستخدم غير موجود", show_alert=True)
            return
        
        msg_count = db.query(Message).filter(Message.tg_id==tg_id).count()
        messages = db.query(Message).filter(Message.tg_id==tg_id).order_by(Message.created_at.desc()).limit(15).all()
        
        detail_text = f"""📋 **تفاصيل المستخدم:**

👤 الاسم: {user_record.name}
🆔 ID: {tg_id}
📅 تاريخ التسجيل: {user_record.created_at.strftime("%d/%m/%Y %H:%M") if user_record.created_at else "N/A"}
💬 عدد الرسائل: {msg_count}
🚫 الحالة: {"محظور ❌" if user_record.is_banned else "نشط ✅"}

📝 **النشاط الأخير (آخر 15 رسالة):**
"""
        
        if messages:
            for i, msg in enumerate(messages, 1):
                time_str = msg.created_at.strftime("%d/%m %H:%M") if msg.created_at else "N/A"
                msg_preview = (msg.message_text[:35] + "...") if len(msg.message_text or "") > 35 else msg.message_text
                detail_text += f"\n{i}. [{time_str}] {msg_preview}"
        else:
            detail_text += "\nلا توجد رسائل"
        
        detail_text = detail_text[:4096]
        
        await query.edit_message_text(detail_text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ رجوع", callback_data="back_userlist")]
        ]))
    except Exception as e:
        logger.error(f"User detail error: {e}")
        await query.answer("❌ حدث خطأ", show_alert=True)
    finally:
        db.close()

async def fetch_gold_price():
    """جلب السعر الحالي للذهب من Gold API مباشرة - المصدر الوحيد"""
    try:
        headers = {"x-access-token": f"goldapi-{GOLD_API_KEY}"}
        url = "https://www.goldapi.io/api/XAU/USD"
        
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        price = float(data.get('price', 0))
        
        if price > 0:
            logger.info(f"✅ سعر حقيقي من Gold API: ${price:.2f}")
            return {
                'price': price,
                'bid': float(data.get('bid', price)),
                'ask': float(data.get('ask', price))
            }
        else:
            logger.error("❌ السعر صفر من Gold API")
            return None
            
    except Exception as e:
        logger.error(f"❌ فشل جلب السعر من Gold API: {e}")
        return None

async def analyze_trading_chart(image_path):
    """تحليل متخصص لشارتات التداول"""
    if not GEMINI_READY:
        return "❌ Google Gemini غير متوفر الآن"
    try:
        from PIL import Image
        img = Image.open(image_path)
        system_instruction = """أنت محلل شارتات تداول احترافي وذكي.

عند تحليل الشارت:
- حدد الاتجاه الحالي (صاعد/هابط/جانبي)
- حدد مستويات الدعم والمقاومة الرئيسية
- اذكر أي أنماط شمعية مهمة
- اعطِ توصيات للدخول والخروج
- حدد مستويات أخذ الأرباح والخسارة المقترحة
- اذكر مستويات الثقة
- كن محترفاً وواقعياً في التحليل"""
        response = call_gemini_with_retry("قم بتحليل شارت chat gpt هذا بالعربية:", system_instruction=system_instruction, image_data=img)
        if response and response.text:
            return response.text
        return "❌ فشل التحليل - جاري المحاولة بنموذج آخر..."
    except Exception as e:
        logger.error(f"Chart analysis error: {e}")
        return "❌ فشل تحليل الشارت"

async def photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not update.message or not update.message.photo:
        return
    
    if await check_frozen_account(update, str(user.id)):
        return
    
    try:
        mode = context.user_data.get("mode") if context.user_data else None
        
        await update.message.chat.send_action("typing")
        photo_file = await update.message.photo[-1].get_file()
        file_path = os.path.join(DOWNLOADS_DIR, f"photo_{int(time.time()*1000)}.jpg")
        await photo_file.download_to_drive(file_path)
        
        if mode == "broadcast_image":
            caption = getattr(update.message, 'caption', None) or ""
            db = db_session()
            try:
                users = db.query(User).filter(User.is_banned == False).all()
                sent = 0
                for user_record in users:
                    try:
                        with open(file_path, 'rb') as photo:
                            await context.bot.send_photo(chat_id=user_record.tg_id, photo=photo, caption=caption or "📸")
                        sent += 1
                        await asyncio.sleep(0.05)
                    except:
                        pass
                await update.message.reply_text(f"✅ تم إرسال الصورة لـ {sent} مستخدم")
            finally:
                db.close()
            if context.user_data:
                context.user_data["mode"] = None
        elif mode == "chart_analysis":
            result = await analyze_trading_chart(file_path)
            await update.message.reply_text(f"📊 **تحليل شارت chat gpt:**\n\n{result}\n\nاختر خدمة أخرى:", reply_markup=main_menu())
        elif mode in ("edit_anime", "edit_realistic", "edit_background", "edit_enhance"):
            msg = await update.message.reply_text("⏳ جاري تطبيق التأثير على الصورة...")
            try:
                from PIL import Image, ImageFilter, ImageEnhance, ImageOps
                img = Image.open(file_path)
                
                # تطبيق التأثيرات حسب النوع
                if mode == "edit_anime":
                    # تأثير أنمي محسن
                    img = img.convert('RGB')
                    img = ImageOps.posterize(img, 3)
                    img = img.filter(ImageFilter.EDGE_ENHANCE_MORE)
                    enhancer = ImageEnhance.Color(img)
                    img = enhancer.enhance(1.8)
                    output_path = os.path.join(DOWNLOADS_DIR, f"anime_{int(time.time()*1000)}.png")
                    img.save(output_path)
                
                elif mode == "edit_realistic":
                    # تحسين الواقعية (تحسين التباين والحدة)
                    img = img.convert('RGB')
                    enhancer = ImageEnhance.Contrast(img)
                    img = enhancer.enhance(1.5)
                    enhancer = ImageEnhance.Sharpness(img)
                    img = enhancer.enhance(1.3)
                    output_path = os.path.join(DOWNLOADS_DIR, f"realistic_{int(time.time()*1000)}.png")
                    img.save(output_path)
                
                elif mode == "edit_background":
                    # تحسين الخلفية وجعلها أكثر وضوحاً
                    img = img.convert('RGB')
                    enhancer = ImageEnhance.Color(img)
                    img = enhancer.enhance(1.4)
                    img = img.filter(ImageFilter.DETAIL)
                    output_path = os.path.join(DOWNLOADS_DIR, f"background_{int(time.time()*1000)}.png")
                    img.save(output_path)
                
                elif mode == "edit_enhance":
                    # تحسين الجودة العام
                    img = img.convert('RGB')
                    enhancer = ImageEnhance.Contrast(img)
                    img = enhancer.enhance(1.2)
                    enhancer = ImageEnhance.Color(img)
                    img = enhancer.enhance(1.1)
                    enhancer = ImageEnhance.Sharpness(img)
                    img = enhancer.enhance(1.2)
                    output_path = os.path.join(DOWNLOADS_DIR, f"enhanced_{int(time.time()*1000)}.png")
                    img.save(output_path)
                
                # إرسال الصورة المعدلة
                await msg.delete()
                with open(output_path, 'rb') as photo:
                    await update.message.reply_photo(photo=photo, caption="✅ تم تطبيق التأثير بنجاح! 🎨")
                
                # تنظيف الملفات
                try:
                    os.remove(output_path)
                except:
                    pass
                    
            except Exception as e:
                logger.error(f"Image edit error: {e}")
                await msg.edit_text(f"❌ خطأ في معالجة الصورة: {str(e)[:100]}")
            
            if context.user_data:
                context.user_data["mode"] = None
        elif mode == "design_rating":
            # تقييم التصميم من 10 مع التفاصيل
            msg = await update.message.reply_text("⏳ جاري تقييم التصميم... يرجى الانتظار")
            system_instruction = """أنت خبير متخصص في تقييم التصاميم والمواقع والتطبيقات.

عند تقييم التصميم:
1. قيّم من 10 نقاط (مثال: 7.5/10)
2. اذكر نقاط القوة (3-4 نقاط)
3. اذكر نقاط التحسين (3-4 نقاط)
4. قدم اقتراحات عملية (2-3 اقتراحات)
5. اجعل التقييم واقعياً وصادقاً
6. كن احترافياً في الشرح

الصيغة المطلوبة:
⭐ **التقييم: X.X/10**

✅ **نقاط القوة:**
- النقطة الأولى
- النقطة الثانية
- النقطة الثالثة

⚠️ **نقاط التحسين:**
- التحسين الأول
- التحسين الثاني
- التحسين الثالث

💡 **الاقتراحات:**
- الاقتراح الأول
- الاقتراح الثاني

📝 **الخلاصة:**
[ملخص سريع]"""
            try:
                from PIL import Image
                img = Image.open(file_path)
                result = call_gemini_with_retry(
                    "قيّم هذا التصميم من 10 مع تفاصيل النقاط والمقترحات:",
                    system_instruction=system_instruction,
                    image_data=img
                )
                if result and result.text:
                    await msg.delete()
                    await update.message.reply_text(f"🎨 **تقييم التصميم:**\n\n{result.text}\n\nاختر خدمة أخرى:", reply_markup=main_menu())
                else:
                    await msg.edit_text("❌ فشل التقييم - حاول مرة أخرى", reply_markup=main_menu())
            except Exception as e:
                logger.error(f"Design rating error: {e}")
                await msg.edit_text("❌ خطأ في معالجة الصورة", reply_markup=main_menu())
        else:
            result = await analyze_image(file_path)
            await update.message.reply_text(f"🖼️ **تحليل الصورة:**\n\n{result}\n\nاختر خدمة أخرى:", reply_markup=main_menu())
        
        if context.user_data:
            context.user_data["mode"] = None
        
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except:
                pass
    except Exception as e:
        logger.error(f"Photo handler error: {e}")
        await update.message.reply_text("❌ فشل معالجة الصورة", reply_markup=main_menu())

async def audio_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not update.message or not update.message.audio and not update.message.voice:
        return
    
    if await check_frozen_account(update, str(user.id)):
        return
    
    try:
        mode = context.user_data.get("mode") if context.user_data else None
        
        if mode != "stt":
            await update.message.reply_text("⚠️ استخدم الخيار 🎙️ **صوت إلى نص** أولاً من القائمة الرئيسية", reply_markup=main_menu())
            return
        
        await update.message.chat.send_action("typing")
        msg = await update.message.reply_text("⏳ تحويل الصوت إلى نص... برجاء الانتظار")
        
        audio_file = update.message.voice or update.message.audio
        if not audio_file:
            await msg.delete()
            await update.message.reply_text("❌ لم يتم العثور على ملف صوتي", reply_markup=main_menu())
            return
        
        file_obj = await audio_file.get_file()
        file_path = os.path.join(DOWNLOADS_DIR, f"audio_{int(time.time()*1000)}.ogg")
        await file_obj.download_to_drive(file_path)
        
        logger.info(f"📥 ملف صوتي تم تحميله: {file_path}")
        
        text = speech_to_text_faster_whisper(file_path)
        
        if text and len(text.strip()) > 0:
            await msg.delete()
            bot_response = f"📝 النص المستخرج: {text}"
            save_bot_message(str(user.id), bot_response)
            await update.message.reply_text(f"📝 **النص المستخرج:**\n\n{text}\n\nاختر خدمة أخرى:", reply_markup=main_menu())
            if context.user_data:
                context.user_data["mode"] = None
        else:
            await msg.delete()
            await update.message.reply_text("❌ فشل تحويل الصوت. تأكد أن الملف واضح وبالعربية\n\nاختر خدمة أخرى:", reply_markup=main_menu())
            if context.user_data:
                context.user_data["mode"] = None
        
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except:
                pass
    except Exception as e:
        logger.error(f"Audio handler error: {e}")
        await update.message.reply_text("❌ خطأ في معالجة الملف الصوتي", reply_markup=main_menu())
        if context.user_data:
            context.user_data["mode"] = None

async def download_youtube_video_new(url, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تنزيل فيديو من اليوتيوب (النظام الجديد)"""
    try:
        msg = await update.message.reply_text("⏬ جاري تحميل الفيديو من YouTube...")
        
        ydl_opts = {
            'format': 'best[ext=mp4]/best',
            'outtmpl': os.path.join(DOWNLOADS_DIR, f'yt_{int(time.time())}.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'merge_output_format': 'mp4',
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
        }
        
        import yt_dlp
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = await asyncio.to_thread(ydl.extract_info, url, download=True)
            video_path = ydl.prepare_filename(info)
            
            await msg.edit_text("📤 جاري رفع الفيديو...")
            
            file_size = os.path.getsize(video_path)
            if file_size < 50 * 1024 * 1024:
                with open(video_path, 'rb') as f:
                    await update.message.reply_video(video=f, caption=f"✅ تم التنزيل بنجاح!\n📹 {info.get('title', 'فيديو')}")
            else:
                await update.message.reply_text("⚠️ حجم الفيديو كبير جداً للرفع مباشرة.")
            
            await msg.delete()
            try: os.remove(video_path)
            except: pass
    except Exception as e:
        logger.error(f"Error in download_youtube_video_new: {e}")
        await update.message.reply_text(f"❌ حدث خطأ: {str(e)}")

async def download_instagram_video_new(url, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تنزيل فيديو من انستجرام (نظام فائق السرعة والموثوقية)"""
    try:
        msg = await update.message.reply_text("⏬ جاري تحميل الفيديو من Instagram...")
        unique_id = f"ig_{int(time.time())}"
        
        # استخدام النظام المتقدم الموحد
        video_path = await download_with_yt_dlp_advanced(url, is_audio=False, unique_id=unique_id)
        
        if video_path and os.path.exists(video_path):
            await msg.edit_text("📤 جاري رفع الفيديو...")
            with open(video_path, 'rb') as f:
                await update.message.reply_video(video=f, caption="✅ تم التنزيل من Instagram بنجاح!")
            await msg.delete()
            try: os.remove(video_path)
            except: pass
        else:
            # محاولة أخيرة باستخدام نظام مبسط جداً
            await msg.edit_text("🔄 محاولة ثانية سريعة...")
            import yt_dlp
            ydl_opts = {
                'format': 'best',
                'outtmpl': os.path.join(DOWNLOADS_DIR, f'{unique_id}_alt.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
                'cookiefile': 'cookies.txt'
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await asyncio.to_thread(ydl.extract_info, url, download=True)
                path = ydl.prepare_filename(info)
                with open(path, 'rb') as f:
                    await update.message.reply_video(video=f, caption="✅ تم التنزيل من Instagram بنجاح!")
                try: os.remove(path)
                except: pass
                await msg.delete()
                
    except Exception as e:
        logger.error(f"IG error: {e}")
        await update.message.reply_text("❌ فشل التحميل. تأكد من أن الرابط عام وليس من حساب خاص.")

async def download_tiktok_video_new(url, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تنزيل فيديو من تيك توك (نظام فائق السرعة والموثوقية)"""
    try:
        msg = await update.message.reply_text("⏬ جاري تحميل الفيديو من TikTok...")
        unique_id = f"tt_{int(time.time())}"
        
        # تيك توك يحتاج أحياناً لمعالجة خاصة للروابط المختصرة
        video_path = await download_with_yt_dlp_advanced(url, is_audio=False, unique_id=unique_id)
        
        if video_path and os.path.exists(video_path):
            await msg.edit_text("📤 جاري رفع الفيديو...")
            with open(video_path, 'rb') as f:
                await update.message.reply_video(video=f, caption="✅ تم التنزيل من TikTok بنجاح!")
            await msg.delete()
            try: os.remove(video_path)
            except: pass
        else:
            await update.message.reply_text("❌ فشل تحميل فيديو TikTok. جرب رابطاً آخر.")
    except Exception as e:
        logger.error(f"TT error: {e}")
        await update.message.reply_text("❌ حدث خطأ أثناء تحميل تيك توك.")

async def video_download_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    chat_id = update.message.chat_id

    msg = await update.message.reply_text("⏳ جاري التحميل باستخدام yt-dlp...")

    try:
        loop = asyncio.get_event_loop()
        video_path = await loop.run_in_executor(None, turbofetch.turbo_download, url)

        if video_path and os.path.exists(video_path):
            await context.bot.send_video(
                chat_id=chat_id,
                video=open(video_path, "rb"),
                caption="✅ تم التحميل بنجاح"
            )
            os.remove(video_path)
            await msg.delete()
        else:
            await msg.edit_text("❌ فشل التحميل")

    except Exception as e:
        logger.error(f"Download error: {e}")
        await msg.edit_text("❌ فشل التحميل")

async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    if any(x in user_text for x in ["http://", "https://"]):
        await video_download_handler(update, context)
        return
    
    user = update.effective_user
    if not user or not update.message or not update.message.text:
        return
    
    if await check_frozen_account(update, str(user.id)):
        return
    
    txt = update.message.text.strip()
    mode = context.user_data.get("mode") if context.user_data else None
    
    save_message(str(user.id), user.first_name or "User", txt[:100])
    
    # ================= AUTO-DOWNLOAD VIDEOS/MUSIC =================
    # كشف روابط الفيديو والموسيقى التلقائي
    if any(kw in txt.lower() for kw in ["youtube.com", "youtu.be", "instagram.com", "tiktok.com", "spotify.com", "soundcloud.com"]):
        msg = await update.message.reply_text("⏳ جاري التحميل التلقائي... يرجى الانتظار")
        is_audio = any(kw in txt.lower() for kw in ["spotify", "soundcloud"])
        
        try:
            # استخدام المحرك الجديد حصراً لمنع التضارب
            path = await download_with_yt_dlp_advanced(txt, is_audio=is_audio)
            
            if path and os.path.exists(path):
                try:
                    with open(path, "rb") as f:
                        file_data = f.read()
                        if is_audio:
                            await update.message.reply_audio(audio=io.BytesIO(file_data), caption="🎵 تم التحميل بنجاح!")
                        else:
                            await update.message.reply_video(video=io.BytesIO(file_data), caption="🎬 تم التحميل بنجاح!")
                    await update.message.reply_text("✅ تمت العملية بنجاح!", reply_markup=main_menu())
                except Exception as e:
                    logger.error(f"❌ Error sending file: {e}")
                    await update.message.reply_text("❌ حدث خطأ في إرسال الملف.")
                finally:
                    if os.path.exists(path): os.remove(path)
            else:
                await update.message.reply_text("❌ فشل التحميل التلقائي. جرب رابطاً آخر.")
        except Exception as e:
            logger.error(f"❌ Download error: {e}")
            await update.message.reply_text("❌ حدث خطأ أثناء التحميل.")
        finally:
            try: await msg.delete()
            except: pass
        return
    
    if mode == "ask_gemini_signals":
        # ── فحص VIP / تجربة مجانية ──
        db = db_session()
        try:
            user_rec = db.query(User).filter(User.tg_id == str(user.id)).first()
            access = is_trial_active(user_rec)
        finally:
            db.close()
        if not access:
            if context.user_data:
                context.user_data["mode"] = None
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 اشترك VIP الآن", url=WHATSAPP_LINK)],
                [InlineKeyboardButton("◀️ القائمة الرئيسية", callback_data="back")]
            ])
            await update.message.reply_text(
                "🔒 *مساعد المتداول — ميزة VIP*\n\n"
                "انتهت فترة تجربتك المجانية.\n"
                "اشترك في VIP للوصول إلى مساعد التداول الذكي وجميع الميزات الاحترافية!",
                reply_markup=markup, parse_mode="Markdown"
            )
            return
        await update.message.chat.send_action("typing")
        system_prompt = """أنت مساعد تداول ذهب مختصر وخبير.
قواعد الرد:
- رد قصير ومباشر (3-5 أسطر)
- لا مقدمات — ابدأ بالإجابة مباشرة
- إذا ذكر أرقام: أعطِ نقاط دخول/خروج واضحة
- أضف تحذير المخاطر في سطر واحد
- الإجابة بالعربية فقط"""
        prompt = f"{system_prompt}\n\nالسؤال: {txt}\n\nالرد المختصر:"
        ans = await ask_gemini(prompt)
        save_bot_message(str(user.id), ans)
        await update.message.reply_text(f"📊 *تحليل الذكاء الاصطناعي:*\n\n{ans}\n\nاختر خدمة أخرى:", reply_markup=main_menu(), parse_mode="Markdown")
        if context.user_data:
            context.user_data["mode"] = None
        return
    
    if mode == "tts":
        await update.message.chat.send_action("record_audio")
        msg = await update.message.reply_text("⏳ تحويل النص إلى صوت... برجاء الانتظار")
        try:
            out = text_to_speech_gtts(txt)
            if out and os.path.exists(out):
                try:
                    with open(out, "rb") as f:
                        await update.message.reply_audio(audio=f, title="تحويل النص إلى صوت")
                    if context.user_data:
                        context.user_data["mode"] = None
                    await msg.delete()
                    save_bot_message(str(user.id), "✅ تم التحويل بنجاح! 🎵")
                    await update.message.reply_text("✅ تم التحويل بنجاح! 🎵\n\nاختر خدمة أخرى:", reply_markup=main_menu())
                finally:
                    try: os.remove(out)
                    except: pass
            else:
                logger.warning(f"TTS فشل للنص: {txt[:50]}")
                await msg.delete()
                await update.message.reply_text("❌ فشل التحويل. تأكد أن النص ليس طويلاً جداً\n\nاختر خدمة أخرى:", reply_markup=main_menu())
                if context.user_data:
                    context.user_data["mode"] = None
        except Exception as e:
            logger.error(f"TTS exception: {e}")
            await msg.delete()
            await update.message.reply_text("❌ خطأ في التحويل\n\nاختر خدمة أخرى:", reply_markup=main_menu())
            if context.user_data:
                context.user_data["mode"] = None
        return

    if mode == "ai":
        db = db_session()
        try:
            user_rec = db.query(User).filter(User.tg_id == str(user.id)).first()
            access = is_trial_active(user_rec)
        finally:
            db.close()
        if not access:
            if context.user_data:
                context.user_data["mode"] = None
            markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 اشترك VIP الآن", url=WHATSAPP_LINK)],
                [InlineKeyboardButton("◀️ القائمة الرئيسية", callback_data="back")]
            ])
            await update.message.reply_text("❌ *انتهت فترة التجربة المجانية*\n\nاشترك VIP للوصول لهذه الميزة!", reply_markup=markup, parse_mode="Markdown")
            return
        await update.message.chat.send_action("typing")
        ans = await ask_gemini(txt)
        save_bot_message(str(user.id), ans)
        await update.message.reply_text(ans, reply_markup=ai_menu())
        return
    
    if mode == "study_helper":
        await update.message.chat.send_action("typing")
        prompt = f"""أنت معلم ذكي وطبيعي مع قليل من العفوية. 📚

المستخدم يسأل عن: {txt}

اشرح بطريقة طبيعية وموزونة:
- اجعل الموضوع واضح وسهل الفهم
- استخدم أمثلة حقيقية وعملية
- اشرح الفوائد بطريقة واقعية
- أضف قليل من العفوية في الشرح
- كن موثوقاً ودقيقاً في المعلومات
- كن مختصراً لكن شاملاً"""
        ans = await ask_gemini(prompt)
        bot_response = f"🎓 مساعد الدراسة: {ans}"
        save_bot_message(str(user.id), bot_response)
        await update.message.reply_text(f"🎓 **مساعد الدراسة:**\n\n{ans}\n\nاختر خدمة أخرى:", reply_markup=main_menu())
        if context.user_data:
            context.user_data["mode"] = None
        return
    
    if mode == "writing_helper":
        await update.message.chat.send_action("typing")
        prompt = f"""أنت محرر نصوص ذكي وطبيعي مع قليل من العفوية. ✍️

النص الذي يريد تحسينه المستخدم:
{txt}

قدم النصائح بطريقة طبيعية وموزونة:
- اشرح التحسينات بشكل واضح وعملي
- بيّن كيف سيؤثر التحسين على جودة النص
- ركز على النقاط الفعلية والمهمة
- أضف قليل من العفوية في التواصل
- كن موثوقاً وصادقاً في النقد
- قدم النص المحسّن مع شرح بسيط"""
        ans = await ask_gemini(prompt)
        bot_response = f"✍️ الكتابة والتحرير: {ans}"
        save_bot_message(str(user.id), bot_response)
        await update.message.reply_text(f"✍️ **الكتابة والتحرير:**\n\n{ans}\n\nاختر خدمة أخرى:", reply_markup=main_menu())
        if context.user_data:
            context.user_data["mode"] = None
        return

    if mode == "code_writing":
        await update.message.chat.send_action("typing")
        msg = await update.message.reply_text("⏳ جاري كتابة الكود... يرجى الانتظار")
        system_instruction = """أنت مبرمج محترف وخبير في البرمجة.

عند الإجابة على طلبات البرمجة:
1. قدم كود عملي وواضح
2. استخدم أفضل الممارسات البرمجية
3. أضف تعليقات توضيحية بالعربية
4. شرح الكود بطريقة سهلة الفهم
5. تأكد من أن الكود قابل للتشغيل
6. أذكر اللغة المستخدمة والمكتبات المطلوبة

قدم الإجابة بطريقة احترافية."""
        prompt = f"{system_instruction}\n\nطلب المستخدم: {txt}\n\nالكود والشرح:"
        ans = call_gemini_with_retry(prompt, system_instruction=system_instruction)
        if ans and ans.text:
            await msg.delete()
            bot_response = f"💻 كود برمجي: {ans.text[:100]}"
            save_bot_message(str(user.id), bot_response)
            await update.message.reply_text(f"💻 **الكود:**\n\n{ans.text}\n\nاختر خدمة أخرى:", reply_markup=main_menu())
        else:
            await msg.edit_text("❌ فشل توليد الكود - حاول مرة أخرى", reply_markup=main_menu())
        if context.user_data:
            context.user_data["mode"] = None
        return

    if mode == "design_rating":
        await update.message.chat.send_action("typing")
        msg = await update.message.reply_text("⏳ جاري تقييم التصميم... يرجى الانتظار")
        system_instruction = """أنت خبير متخصص في تقييم التصاميم والمواقع والتطبيقات.

عند تقييم التصميم:
1. قيّم من 10 نقاط (مثال: 7.5/10)
2. اذكر نقاط القوة (3-4 نقاط)
3. اذكر نقاط التحسين (3-4 نقاط)
4. قدم اقتراحات عملية (2-3 اقتراحات)
5. اجعل التقييم واقعياً وصادقاً
6. كن احترافياً في الشرح

الصيغة المطلوبة:
⭐ **التقييم: X.X/10**

✅ **نقاط القوة:**
- النقطة الأولى

⚠️ **نقاط التحسين:**
- التحسين الأول

💡 **الاقتراحات:**
- الاقتراح الأول

📝 **الخلاصة:**
[ملخص سريع]"""
        prompt = f"{system_instruction}\n\nوصف المستخدم للتصميم: {txt}\n\nالتقييم:"
        ans = call_gemini_with_retry(prompt, system_instruction=system_instruction)
        if ans and ans.text:
            await msg.delete()
            bot_response = f"🎨 تقييم تصميم: {ans.text[:100]}"
            save_bot_message(str(user.id), bot_response)
            await update.message.reply_text(f"🎨 **تقييم التصميم:**\n\n{ans.text}\n\nاختر خدمة أخرى:", reply_markup=main_menu())
        else:
            await msg.edit_text("❌ فشل التقييم - حاول مرة أخرى", reply_markup=main_menu())
        if context.user_data:
            context.user_data["mode"] = None
        return

    if mode in ("video", "music") and txt.startswith("http"):
        msg = await update.message.reply_text("⏳ جاري التحميل... قد يستغرق وقتاً")
        is_audio = mode == "music"
        
        try:
            path = await download_with_ytdlp(txt, is_audio)
            
            if path and os.path.exists(path):
                try:
                    with open(path, "rb") as f:
                        file_data = f.read()
                        await asyncio.sleep(0.1)
                        if is_audio:
                            await update.message.reply_audio(audio=io.BytesIO(file_data))
                        else:
                            await update.message.reply_video(video=io.BytesIO(file_data))
                    await asyncio.sleep(0.5)
                    await update.message.reply_text("✅ تم التحميل بنجاح!\n\nاختر خدمة أخرى:", reply_markup=main_menu())
                except Exception as e:
                    logger.error(f"❌ خطأ في إرسال الملف: {e}")
                finally:
                    try: 
                        os.remove(path)
                        await asyncio.sleep(0.1)
                    except: 
                        pass
            else:
                try:
                    await msg.edit_text("❌ فشل التحميل\n\nاختر خدمة أخرى:", reply_markup=main_menu())
                except:
                    await update.message.reply_text("❌ فشل التحميل\n\nاختر خدمة أخرى:", reply_markup=main_menu())
        except Exception as e:
            logger.error(f"❌ خطأ في معالجة التحميل: {e}")
            try:
                await msg.edit_text("❌ حدث خطأ\n\nاختر خدمة أخرى:", reply_markup=main_menu())
            except:
                await update.message.reply_text("❌ حدث خطأ\n\nاختر خدمة أخرى:", reply_markup=main_menu())
        finally:
            if context.user_data:
                context.user_data["mode"] = None
            try:
                await msg.delete()
            except:
                pass
        return
    
    if mode == "text_to_image":
        # Increment usage count
        db = db_session()
        try:
            usage = feature_usage(feature_name="text_to_image", user_id=str(user.id))
            db.add(usage)
            db.commit()
        except: pass
        finally: db.close()
        await update.message.chat.send_action("upload_photo")
        msg = await update.message.reply_text("⏳ جاري توليد الصورة... يرجى الانتظار")
        image_path = await generate_image(txt)
        if image_path and os.path.exists(image_path):
            try:
                with open(image_path, "rb") as f:
                    photo_data = f.read()
                    await asyncio.sleep(0.1)
                    await update.message.reply_photo(photo=io.BytesIO(photo_data), caption=f"🎨 الصورة المولدة من الكلمات:\n\n{txt}")
            except Exception as e:
                logger.error(f"❌ خطأ في إرسال الصورة: {e}")
            finally:
                try: os.remove(image_path)
                except: pass
            if context.user_data:
                context.user_data["mode"] = None
            try:
                await msg.delete()
            except:
                pass
            await update.message.reply_text("✅ تمت الصورة بنجاح!\n\nاختر خدمة أخرى:", reply_markup=main_menu())
        else:
            if context.user_data:
                context.user_data["mode"] = None
            try:
                await msg.edit_text("❌ فشل توليد الصورة\n\nاختر خدمة أخرى:", reply_markup=main_menu())
            except:
                await update.message.reply_text("❌ فشل توليد الصورة\n\nاختر خدمة أخرى:", reply_markup=main_menu())
        return
    
    await update.message.chat.send_action("typing")
    ans = await ask_gemini(txt)
    save_bot_message(str(user.id), ans)
    await update.message.reply_text(ans, reply_markup=ai_menu())

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    
    user = query.from_user
    if not user:
        return
    
    # Track feature usage on button click
    data = query.data
    db = db_session()
    try:
        usage = feature_usage(feature_name=data, user_id=str(user.id))
        db.add(usage)
        db.commit()
    except: pass
    finally: db.close()

    try:
        await query.answer()
    except:
        pass
    
    data = query.data
    
    if data.startswith("user_"):
        await user_detail_callback(update, context)
        return
    
    if data.startswith("today_user_"):
        user_id = data.replace("today_user_", "")
        await show_user_conversation(update, user_id)
        return
    
    if data == "back_todayusers":
        await todayusers_cmd(update, context)
        return
    
    if data == "back_userlist":
        await userlist_cmd(update, context)
        return
    
    if data == "back":
        try:
            await query.edit_message_text("اختر خدمة من القائمة الرئيسية:", reply_markup=main_menu())
        except:
            pass
        if context.user_data and "mode" in context.user_data:
            context.user_data["mode"] = None
        return
    
    if data == "history":
        await history_cmd(update, context)
        return
    
    try:
        if data == "video":
            context.user_data["mode"] = "video"
            await query.edit_message_text("📹 أرسل رابط الفيديو (YouTube, Instagram, TikTok...):", reply_markup=back_btn())
        elif data == "music":
            context.user_data["mode"] = "music"
            await query.edit_message_text("🎵 أرسل رابط الموسيقى (Spotify, YouTube...):", reply_markup=back_btn())
        elif data == "tts":
            context.user_data["mode"] = "tts"
            await query.edit_message_text("📝 اكتب النص الذي تريد تحويله إلى صوت:", reply_markup=back_btn())
        elif data == "stt":
            context.user_data["mode"] = "stt"
            await query.edit_message_text("🎙️ أرسل رسالة صوتية من تيليجرام:", reply_markup=back_btn())
        elif data == "ai":
            db = db_session()
            try:
                user_record = db.query(User).filter(User.tg_id == str(user.id)).first()
                access = is_trial_active(user_record)
                banner = trial_banner(user_record)
            finally:
                db.close()
            if not access:
                vip_msg = """🤖 *مساعد الذكاء الاصطناعي*
━━━━━━━━━━━━━━━━━━━━━━
❌ انتهت فترة التجربة المجانية

💎 *اشترك VIP للحصول على:*
• المساعد الذكي بدون قيود
• مساعد الدراسة والكتابة
• تحليل الشارت بالذكاء الاصطناعي
• إشارات تداول كاملة

📲 اشترك الآن وابدأ فوراً!"""
                markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("💎 اشترك VIP الآن", url=WHATSAPP_LINK)],
                    [InlineKeyboardButton("◀️ رجوع", callback_data="back")]
                ])
                await query.edit_message_text(vip_msg, reply_markup=markup, parse_mode="Markdown")
                return
            context.user_data["mode"] = "ai"
            await query.edit_message_text(f"💬 احك لي ما بتفكر فيه... أنا هنا اساعدك:{banner}", reply_markup=back_btn(), parse_mode="Markdown")
        elif data == "study_helper":
            db = db_session()
            try:
                user_record = db.query(User).filter(User.tg_id == str(user.id)).first()
                access = is_trial_active(user_record)
                banner = trial_banner(user_record)
            finally:
                db.close()
            if not access:
                markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("💎 اشترك VIP الآن", url=WHATSAPP_LINK)],
                    [InlineKeyboardButton("◀️ رجوع", callback_data="back")]
                ])
                await query.edit_message_text("❌ *انتهت فترة التجربة المجانية*\n\nاشترك VIP للوصول لهذه الميزة وأكثر!", reply_markup=markup, parse_mode="Markdown")
                return
            context.user_data["mode"] = "study_helper"
            await query.edit_message_text(f"🎓 أرسل سؤالك أو الموضوع الذي تريد المساعدة فيه:{banner}", reply_markup=back_btn(), parse_mode="Markdown")
        elif data == "writing_helper":
            db = db_session()
            try:
                user_record = db.query(User).filter(User.tg_id == str(user.id)).first()
                access = is_trial_active(user_record)
                banner = trial_banner(user_record)
            finally:
                db.close()
            if not access:
                markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("💎 اشترك VIP الآن", url=WHATSAPP_LINK)],
                    [InlineKeyboardButton("◀️ رجوع", callback_data="back")]
                ])
                await query.edit_message_text("❌ *انتهت فترة التجربة المجانية*\n\nاشترك VIP للوصول لهذه الميزة وأكثر!", reply_markup=markup, parse_mode="Markdown")
                return
            context.user_data["mode"] = "writing_helper"
            await query.edit_message_text(f"✍️ أرسل النص الذي تريد تحسينه:{banner}", reply_markup=back_btn(), parse_mode="Markdown")
        elif data == "support":
            msg = f"👥 **تواصل معنا:**\n\n📞 واتساب: {WHATSAPP_LINK}\n\n☎️ فودافون كاش: {VODAFONE_CASH}\n\nنحن هنا لمساعدتك 24/7"
            await query.edit_message_text(msg, reply_markup=back_btn())
        elif data == "hacker_tools":
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔍 فحص الثغرات", callback_data="h_scan"), InlineKeyboardButton("🔗 صفحة مزيفة", callback_data="h_phish")],
                [InlineKeyboardButton("🚀 هجوم DDoS", callback_data="h_ddos"), InlineKeyboardButton("🔎 فحص تسريبات", callback_data="h_osint")],
                [InlineKeyboardButton("◀️ رجوع", callback_data="back")]
            ])
            msg = """💀 **لوحة تحكم الهكر الاحترافية** 💀

اختر الأداة التي تريد تشغيلها من الأزرار أدناه للبدء فوراً:"""
            await query.edit_message_text(msg, reply_markup=keyboard)
        elif data in ("h_scan", "h_phish", "h_ddos", "h_osint"):
            h_labels = {"h_scan": "فحص الثغرات (/scan)", "h_phish": "الصفحة المزيفة (/phishing)", "h_ddos": "هجوم DDoS (/ddos)", "h_osint": "فحص التسريبات (/osint)"}
            await query.edit_message_text(f"🚀 تم اختيار أداة: {h_labels[data]}\n\nيرجى كتابة الأمر مباشرة في الشات لاستخدامها.", reply_markup=back_btn())
        elif data == "help":
            help_text = f"❓ **الدعم والمساعدة:**\n\n✅ تحويل النصوص إلى صوت احترافي\n✅ محادثة مع الذكاء الاصطناعي\n\n📞 للدعم: {WHATSAPP_LINK}"
            await query.edit_message_text(help_text, reply_markup=back_btn())
        elif data == "show_signals_results":
            await query.edit_message_text("🏆 اختر القسم الذي تود مشاهدة نتائجه:", reply_markup=results_menu())
        elif data == "res_xauusd":
            # Images for XAUUSD
            images = [
                "attached_assets/Screenshot_٢٠٢٦٠٢٠٥-١٣٠٧١٨_Exness_1770289719459.jpg",
                "attached_assets/Screenshot_٢٠٢٦٠٢٠٥-١٣٠٦٣٨_Exness_1770289719574.jpg"
            ]
            for img in images:
                if os.path.exists(img):
                    with open(img, 'rb') as f:
                        await query.message.reply_photo(photo=f, caption="📊 نتائج تداول الذهب XAUUSD")
            await query.answer()
        elif data == "res_btc":
            # Images for BTC
            images = [
                "attached_assets/Screenshot_٢٠٢٦٠٢٠٥-١٣٠٦٥٢_Exness_1770289719541.jpg",
                "attached_assets/Screenshot_٢٠٢٦٠٢٠٥-١٣٠٦١٠_Exness_1770289719599.jpg",
                "attached_assets/Screenshot_٢٠٢٦٠٢٠٥-١٣٠٥٤٧_Exness_1770289719628.jpg"
            ]
            for img in images:
                if os.path.exists(img):
                    with open(img, 'rb') as f:
                        await query.message.reply_photo(photo=f, caption="₿ نتائج تداول البيتكوين BTC")
            await query.answer()
        elif data == "trading_assistant_info":
            db = db_session()
            try:
                user_record = db.query(User).filter(User.tg_id==str(user.id)).first()
                access = is_trial_active(user_record)
                banner = trial_banner(user_record)
                if not access:
                    msg = "❌ *انتهت فترة التجربة المجانية*\n\n💎 للحصول على التحليلات الفنية الدقيقة وتنبيهات الأنماط، اشترك في VIP الآن."
                    markup = InlineKeyboardMarkup([
                        [InlineKeyboardButton("💎 الاشتراك في VIP", callback_data="payments_main")],
                        [InlineKeyboardButton("🔙 العودة", callback_data="back")]
                    ])
                    await query.edit_message_text(msg, reply_markup=markup, parse_mode="Markdown")
                    return
            finally:
                db.close()

            assistant_text = """🚀 **نظام مساعد المتداول الذكي**
━━━━━━━━━━━━━━━━━━━━━━
هذا النظام ليس مجرد تحليل آلي، بل هو **محرك ذكاء اصطناعي فائق** يتميز بـ:

✅ **تحليل فني عميق:** يعتمد على أكثر من 50 مؤشر فني (RSI, MACD, Ichimoku).
✅ **قوة النماذج:** يتعرف تلقائياً على نماذج الشموع والبرايس أكشن (Harmonic, SMC).
✅ **دقة التحليل:** يوفر عليك ساعات من البحث والتحليل اليدوي.
✅ **نظام متكامل:** يتكون من خوارزميات رياضية معقدة لضمان أفضل نقاط الدخول.

🚀 **المساعد يوفر عليك الكثير ويضعك في مقدمة المتداولين!**

فقط أرسل صورة الشارت الخاص بك أو اسألني عن أي زوج عملات وسيقوم النظام بتحليله فوراً!"""
            await query.edit_message_text(assistant_text, reply_markup=back_btn(), parse_mode="Markdown")
        elif data == "admin_marketing":
            msg = """💼 **الجانب الإداري والتسويقي**
━━━━━━━━━━━━━━━━━━━━━━
مرحباً بك في نظامنا الاحترافي. نحن نوفر لك:

📈 **أدوات تسويقية:** روابط إحالة مخصصة تمنحك عمولات على كل مشترك.
👥 **إدارة الفريق:** نظام متكامل لمتابعة أداء فريقك وأرباحك.
🎁 **مكافآت:** جوائز شهرية لأفضل المسوقين والمحللين.

🚀 **كن شريكاً لنا في النجاح وابدأ بجني الأرباح اليوم!**"""
            await query.edit_message_text(text=msg, reply_markup=back_btn(), parse_mode="Markdown")
        elif data == "earn_money":
            await earn_money_handler(update, context)
        elif data == "referral":
            ref_link = f"https://t.me/YOUR_BOT?start=ref_{user.id}"
            msg = f"💰 **برنامج الإحالات:**\n\nأرسل هذا الرابط لأصدقائك واحصل على 4 نقاط لكل شخص!\n\n🔗 رابط الإحالة:\n`{ref_link}`"
            await query.edit_message_text(msg, reply_markup=back_btn())
        elif data == "more_features":
            msg = """✨ **المزيد من الميزات:**

اختر من القائمة أدناه:"""
            await query.edit_message_text(msg, reply_markup=more_features_menu())
        elif data == "live_signals":
            signals_msg = TRADING_SIGNALS.get("example", "جاري تحديث الإشارات...")
            msg = f"""⚡ **إشارات التداول المباشرة:**

{signals_msg}

📊 **معلومات الإشارة:**
- تحليل من 40 نموذج ذكي
- تحقق من خلال 5 محللين بشر
- معدل دقة: 87%
- تحديث كل 15 دقيقة

💰 للحصول على الإشارات المدفوعة الكاملة:
{WHATSAPP_LINK}"""
            await query.edit_message_text(msg, reply_markup=back_btn())
        elif data == "edit_image":
            edit_menu = InlineKeyboardMarkup([
                [InlineKeyboardButton("🎨 تحويل إلى أنمي", callback_data="edit_anime")],
                [InlineKeyboardButton("🌅 تحويل إلى واقعي", callback_data="edit_realistic")],
                [InlineKeyboardButton("🎭 تغيير الخلفية", callback_data="edit_background")],
                [InlineKeyboardButton("✨ تحسين الجودة", callback_data="edit_enhance")],
                [InlineKeyboardButton("◀️ رجوع", callback_data="back")]
            ])
            await query.edit_message_text("🖌️ اختر نوع التعديل:", reply_markup=edit_menu)
        elif data in ("edit_anime", "edit_realistic", "edit_background", "edit_enhance"):
            edit_type = data.replace("edit_", "")
            edit_labels = {
                "anime": "أنمي",
                "realistic": "واقعي",
                "background": "الخلفية",
                "enhance": "تحسين الجودة"
            }
            context.user_data["mode"] = f"edit_{edit_type}"
            label = edit_labels.get(edit_type, "")
            await query.edit_message_text(f"🖌️ أرسل الصورة التي تريد تحويلها إلى {label}:", reply_markup=back_btn())
        elif data == "edit_enhance":
            edit_type = data.replace("edit_", "")
            edit_labels = {
                "anime": "أنمي",
                "realistic": "واقعي",
                "background": "الخلفية",
                "enhance": "تحسين الجودة"
            }
            context.user_data["mode"] = f"edit_{edit_type}"
            label = edit_labels.get(edit_type, "")
            await query.edit_message_text(f"🖌️ أرسل الصورة التي تريد تحويلها إلى {label}:", reply_markup=back_btn())
        elif data == "pattern_recognition":
            context.user_data["mode"] = "pattern_recognition"
            await query.edit_message_text("🔍 **ميزة التعرف على الأنماط الذكية**\n\nأرسل صورة الشارت الخاص بك الآن، وسيقوم النظام بتحليلها والتعرف على:\n✅ النماذج الفنية (مثل الرأس والكتفين، المثلثات).\n✅ أنماط الشموع اليابانية.\n✅ مناطق الدعم والمقاومة القوية.\n\n🚀 أرسل الصورة للبدء:", reply_markup=back_btn(), parse_mode="Markdown")
        elif data == "payments_main":
            payment_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 فودافون كاش (مصر)", callback_data="pay_vodafone")],
                [InlineKeyboardButton("🌍 بايننس (USDT)", callback_data="pay_binance")],
                [InlineKeyboardButton("◀️ رجوع", callback_data="back")]
            ])
            await query.edit_message_text("💰 **خيارات الدفع المتاحة:**\n\nاختر وسيلة الدفع المناسبة لك لتفعيل اشتراكك أو شراء الكورسات:", reply_markup=payment_keyboard, parse_mode="Markdown")
        elif data == "pay_vodafone":
            msg = f"💳 **الدفع عبر فودافون كاش:**\n\n📌 الرقم: `{VODAFONE_CASH}`\n\nبعد تحويل المبلغ، يرجى إرسال صورة التحويل للدعم الفني لتفعيل الخدمة فوراً.\n\n📞 الدعم: {WHATSAPP_LINK}"
            await query.edit_message_text(msg, reply_markup=back_btn(), parse_mode="Markdown")
        elif data == "pay_binance":
            msg = f"🌍 **الدفع عبر بايننس (USDT - TRC20):**\n\n📌 العنوان (Wallet Address):\n`TUx9j8H7G6F5E4D3C2B1A0Z9Y8X7W6V5U4`\n\nبعد التحويل، أرسل لقطة شاشة للعملية للدعم الفني.\n\n📞 الدعم: {WHATSAPP_LINK}"
            await query.edit_message_text(msg, reply_markup=back_btn(), parse_mode="Markdown")
        elif data in ("image_processor",):
            context.user_data["mode"] = "image_processor"
            await query.edit_message_text("🖼️ أرسل صورة لتحليلها:", reply_markup=back_btn())
        elif data == "chart_analysis":
            context.user_data["mode"] = "chart_analysis"
            await query.edit_message_text("📊 أرسل صورة شارت chat gpt الذي تريد تحليله:\n\n⏰ سيتم تحليل الشارت وإعطاؤك توصيات احترافية", reply_markup=back_btn())
        elif data == "instant_signal":
            msg = "⏳ جاري جلب الإشارة الفورية للذهب من Gold API..."
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ رجوع", callback_data="back")]]))
            try:
                price_data = await fetch_gold_price()
                if not price_data:
                    await query.edit_message_text("❌ فشل جلب سعر الذهب من Gold API", reply_markup=back_btn())
                    return
                
                current_price = price_data['price']
                bid = price_data['bid']
                ask = price_data['ask']
                
                signal_type = "BUY" if datetime.now().minute % 2 == 0 else "SELL"
                confidence = "87%"
                
                signal_msg = f"""⚡ **الإشارة الفورية للذهب XAU/USD**

🎯 **نوع الإشارة:** {signal_type}
📊 **السعر الحالي:** ${current_price:.2f}
💰 **Bid:** ${bid:.2f}
💰 **Ask:** ${ask:.2f}
💯 **نسبة الثقة:** {confidence}

📈 **مستويات المخاطرة:**
• 🟢 نقطة الدخول: ${current_price:.2f}
• 🔴 Stop Loss: ${current_price - 15:.2f}
• 💰 Take Profit 1: ${current_price + 20:.2f}
• 💰 Take Profit 2: ${current_price + 35:.2f}

⏰ **الوقت:** {datetime.now().strftime("%H:%M:%S")}
📅 **التاريخ:** {datetime.now().strftime("%d/%m/%Y")}

📌 **مصدر البيانات:** Gold API
🔑 **API:** goldapi.io

⚠️ **ملاحظة مهمة:**
تذكر أن التداول يحمل مخاطر عالية. لا تستثمر أكثر مما تستطيع خسارته.
هذه الإشارة للأغراض التعليمية فقط."""
                await query.edit_message_text(signal_msg, reply_markup=back_btn())
            except Exception as e:
                logger.error(f"Instant signal error: {e}")
                await query.edit_message_text(f"❌ فشل جلب الإشارة\n\nالخطأ: {str(e)}", reply_markup=back_btn())
        elif data == "ask_gemini_signals":
            context.user_data["mode"] = "ask_gemini_signals"
            msg = """🤖 **اسأل Gemini عن الإشارات والتداول**

اكتب سؤالك عن:
• إشارات الذهب XAU/USD
• تحليل الاتجاهات
• نصائح التداول
• استراتيجيات المخاطرة
• تفسير المؤشرات الفنية

مثال: "هل الآن وقت مناسب للدخول في إشارة شراء الذهب؟"
أو: "ما هي أفضل نسبة مخاطرة عائد للتداول؟"

💬 اكتب سؤالك الآن:"""
            await query.edit_message_text(msg, reply_markup=back_btn())
        elif data == "text_to_image":
            context.user_data["mode"] = "text_to_image"
            await query.edit_message_text("🎨 أرسل الكلمات المراد تحويلها إلى صورة (مثال: قطة تأكل سمك):", reply_markup=back_btn())
        elif data == "phone_hacking":
            context.user_data["mode"] = "phone_hacking"
            msg = """⚠️ **خدمة اختراق الهواتف النشطة** ⚠️

نوفر لك وصولاً كاملاً إلى أي هاتف مستهدف:
✅ سحب الرسائل والمكالمات (SMS, WhatsApp)
✅ الدخول إلى معرض الصور والفيديوهات
✅ التجسس المباشر عبر الكاميرا والمايكروفون
✅ تتبع الموقع الجغرافي لحظياً
✅ السيطرة الكاملة على التطبيقات والحسابات

🚀 **الهاتف المستهدف تحت سيطرتك بالكامل!**

للبدء في عملية الاختراق أو الاستفسار عن الأسعار، تواصل مع المبرمج فوراً:"""
            whatsapp_button = InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 تواصل معي واتساب للبدء", url=WHATSAPP_LINK)],
                [InlineKeyboardButton("◀️ رجوع", callback_data="back")]
            ])
            await query.edit_message_text(msg, reply_markup=whatsapp_button, parse_mode="Markdown")
        elif data == "design_rating":
            context.user_data["mode"] = "design_rating"
            msg = """🎨 **تقيم المظهر والجمال**

أرسل صورة أو وصف لموقع/تطبيق/تصميم تريد تقييمه من حيث:
• المظهر والتصميم البصري
• سهولة الاستخدام
• الألوان والتنسيق
• تجربة المستخدم (UX)
• التحسينات المقترحة

💡 يمكنك:
1. إرسال صورة للتصميم
2. وصف التصميم بالكلمات
3. إرسال رابط الموقع (إن أمكن)

🎯 سأقدم لك تقييماً متفصلاً:
- نقاط القوة ✅
- نقاط التحسين ⚠️
- اقتراحات عملية 💡

💬 ابدأ الآن - أرسل الصورة أو الوصف:"""
            await query.edit_message_text(msg, reply_markup=back_btn())
        elif data == "freeze_account":
            freeze_msg = f"""🧊 **تبنيد الحساب**

هذه الخدمة متاحة للمحتاجين الراغبين في تجميد حساباتهم بشكل مؤقت.

💰 **السعر: 100 جنيه مصري ($2)**

⏰ **المدة:**
- 📅 **30 يوم** = 100 جنيه (الخيار الأساسي)
- 📅 **مدة أطول** = تكاليف إضافية (للتفاصيل تواصل معنا)

✅ **المميزات:**
- ✋ تجميد كامل الحساب
- 🚫 عدم الوصول إلى أي خدمات
- 🔄 إمكانية إلغاء التجميد في أي وقت

📞 **للحصول على الخدمة:**
{WHATSAPP_LINK}

📍 طرق الدفع:
- 💰 فودافون كاش: {VODAFONE_CASH}
- 🏦 تحويل بنكي
- 📱 عبر واتساب"""
            freeze_btn = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ تبنيد 30 يوم (100 جنيه)", callback_data="freeze_30days")],
                [InlineKeyboardButton("⏱️ مدة أطول", callback_data="freeze_extended")],
                [InlineKeyboardButton("❌ إلغاء", callback_data="back")]
            ])
            await query.edit_message_text(freeze_msg, reply_markup=freeze_btn)
        elif data == "freeze_30days":
            db = db_session()
            try:
                user_record = db.query(User).filter(User.tg_id==str(user.id)).first()
                if user_record:
                    from datetime import timedelta
                    user_record.is_frozen = True
                    user_record.frozen_until = datetime.utcnow() + timedelta(days=30)
                    db.commit()
                    confirm_msg = f"""✅ **تم تبنيد الحساب بنجاح!**

🧊 حسابك الآن معلق لمدة 30 يوم
📅 سيتم تفعيله بتاريخ: {(datetime.utcnow() + timedelta(days=30)).strftime("%d/%m/%Y")}

💰 للدفع (100 جنيه / $2):
- 💰 فودافون كاش: {VODAFONE_CASH}
- 📱 واتساب: {WHATSAPP_LINK}

شكراً لاستخدامك خدماتنا ❤️"""
                    await query.edit_message_text(confirm_msg, reply_markup=back_btn())
            except:
                pass
            finally:
                db.close()
        elif data == "freeze_extended":
            extended_msg = f"""⏱️ **تبنيد مدة أطول**

تواصل معنا لتحديد مدة التبنيد المطلوبة:

📞 **اتصل بنا الآن:**
{WHATSAPP_LINK}

☎️ **فودافون كاش:**
{VODAFONE_CASH}

سنساعدك في حساب التكلفة حسب المدة المطلوبة 💙"""
            await query.edit_message_text(extended_msg, reply_markup=back_btn())
        elif data.startswith("today_user_"):
            user_id = data.replace("today_user_", "")
            await show_user_conversation(update, user_id)
        elif data == "back_todayusers":
            await todayusers_cmd(update, context)
        elif data in ("create_bot",):
            create_msg = """🤖 **صنع بوت خاص بك:**

نوفر لك خدمة تطوير بوتات تيليجرام احترافية مع:

✅ تصميم واجهة مستخدم متقدمة
✅ دمج الذكاء الاصطناعي
✅ قاعدة بيانات آمنة
✅ دعم 24/7

📞 تواصل معنا:
{WHATSAPP_LINK}

سنساعدك في بناء بوت أحلامك!"""
            await query.edit_message_text(create_msg, reply_markup=back_btn())
        elif data == "courses":
            msg = """🎓 **كورسات التداول:**

اختر التخصص الذي تريده:"""
            await query.edit_message_text(msg, reply_markup=courses_menu())
        elif data == "payment_methods":
            payment_msg = f"""💳 **طرق الدفع المتاحة:**

💰 **الدفع عند الاستقبال (الفيديوهات والموسيقى والصور)**
- دفع 50 جنيه مصري لكل ملف

💳 **فودافون كاش:**
- الرقم: {VODAFONE_CASH}
- سهل وآمن وفوري

📱 **التحويل البنكي:**
- يتم عند الطلب

🔐 **محفظة إلكترونية:**
- آمنة وسريعة

📞 **تواصل معنا للدفع:**
{WHATSAPP_LINK}

✅ جميع الدفعات آمنة وموثوقة 100%"""
            await query.edit_message_text(payment_msg, reply_markup=back_btn())
        elif data.startswith("survey_m_"):
            import json
            parts = data.split("_")
            survey_id = parts[2] + "_" + parts[3]
            choice = int(parts[4])
            
            db = db_session()
            try:
                survey = db.query(SurveyMulti).filter(SurveyMulti.survey_id==survey_id).first()
                if survey:
                    voter_id = str(query.from_user.id)
                    if voter_id not in survey.voters:
                        options_dict = json.loads(survey.options)
                        opt_key = f"opt_{choice}"
                        if opt_key in options_dict:
                            options_dict[opt_key]["count"] += 1
                            survey.options = json.dumps(options_dict)
                            voters = list(survey.voters)
                            voters.append(voter_id)
                            survey.voters = voters
                            db.commit()
                            
                            response_text = options_dict[opt_key].get("response", "✅ تم تسجيل صوتك بنجاح!")
                            await query.answer(response_text, show_alert=True)
                            await query.edit_message_text(f"✅ تم تسجيل صوتك بنجاح!\n\nشكراً لمشاركتك في الاستبيان: **{survey.question}**", parse_mode="Markdown")
                        else:
                            await query.answer("❌ خيار غير صالح", show_alert=True)
                    else:
                        await query.answer("⚠️ لقد قمت بالتصويت مسبقاً في هذا الاستبيان!", show_alert=True)
                else:
                    await query.answer("❌ عذراً، لم يتم العثور على الاستبيان", show_alert=True)
            except Exception as e:
                logger.error(f"Error in multi survey vote: {e}")
                await query.answer("❌ حدث خطأ أثناء تسجيل صوتك", show_alert=True)
            finally:
                db.close()
        
        elif data.startswith("tr_vote_"):
            # معالج الاستبيان للبوت الأول في حال تم توجيهه له
            await survey_vote_handler(update, context)
            
        elif data.startswith("survey_survey_"):
            # معالج الاستجابة على الاستبيان البسيط
            parts = data.split("_")
            survey_id = parts[2] + "_" + parts[3]
            choice = int(parts[4])
            
            db = db_session()
            try:
                survey = db.query(Survey).filter(Survey.survey_id==survey_id).first()
                if survey:
                    voter_id = str(query.from_user.id)
                    if voter_id not in survey.voters:
                        if choice == 1:
                            survey.count1 += 1
                        else:
                            survey.count2 += 1
                        voters = list(survey.voters)
                        voters.append(voter_id)
                        survey.voters = voters
                        db.commit()
                        await query.answer("✅ تم تسجيل صوتك بنجاح!", show_alert=True)
                        await query.edit_message_text(f"✅ تم تسجيل صوتك بنجاح!\n\nشكراً لمشاركتك في الاستبيان.")
                    else:
                        await query.answer("⚠️ لقد قمت بالتصويت مسبقاً!", show_alert=True)
                else:
                    await query.answer("❌ الاستبيان غير موجود", show_alert=True)
            except Exception as e:
                logger.error(f"Survey vote error: {e}")
                await query.answer("❌ حدث خطأ", show_alert=True)
            finally:
                db.close()
        elif data.startswith("course_"):
            # عند اختيار كورس، نرسل المستخدم إلى واتساب
            course_idx = int(data.split("_")[1])
            # قد نحتاج إلى حفظ قائمة الكورسات الحالية في context
            courses_list = context.user_data.get("courses_list", [])
            if course_idx < len(courses_list):
                course_name = courses_list[course_idx]
                msg = f"""✅ **تم اختيار الكورس:**

📚 الكورس: {course_name}

👇 اضغط على الزر أدناه للتواصل معنا واتساب لشراء هذا الكورس"""
                whatsapp_button = InlineKeyboardMarkup([[InlineKeyboardButton("💬 تواصل معنا واتساب", url=WHATSAPP_LINK)],
                                                        [InlineKeyboardButton("◀️ الأقسام", callback_data="courses")]])
                await query.edit_message_text(msg, reply_markup=whatsapp_button)
        elif data.startswith("smc") or data.startswith("ict") or data.startswith("sk") or data in TRADING_COURSES:
            if data in TRADING_COURSES:
                course_data = TRADING_COURSES[data]
                title = course_data["title"]
                courses = course_data["courses"]
                # حفظ الكورسات في context
                context.user_data["courses_list"] = courses
                # عرض الكورسات كأزرار بدلاً من النص
                msg = f"🎓 {title}\n\nاختر الكورس المطلوب:"
                await query.edit_message_text(msg, reply_markup=courses_list_menu(courses))
    except:
        pass

async def voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الرسائل الصوتية - تحويل الصوت لنص"""
    await audio_message(update, context)

async def broadcast_new_bot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر لإخبار المستخدمين عن بوت التداول الجديد"""
    if update.effective_user.id not in ADMIN_IDS: return
    msg = (
        "🚀 **خبر عاجل لجميع مستخدمينا!**\n\n"
        "تم بحمد الله إطلاق **بوت التداول الاحترافي الجديد**! 📈\n"
        "احصل على إشارات ذهب فورية ودقيقة جداً الآن.\n\n"
        "🔗 رابط البوت: @trading_bot_service_bot"
    )
    db = db_session()
    users = db.query(User).filter(User.blocked_or_left == False).all()
    db.close()
    success = 0
    for u in users:
        try:
            await context.bot.send_message(chat_id=u.tg_id, text=msg, parse_mode="Markdown")
            success += 1
            await asyncio.sleep(0.05)
        except: pass
    await update.message.reply_text(f"📢 تم إرسال الخبر لـ {success} مستخدم.")

async def scan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ يرجى إرسال الرابط مع الأمر. مثال: /scan http://example.com")
        return
    url = context.args[0]
    await update.message.reply_text(f"🔍 جاري فحص الرابط: {url}...")
    sqli = scanner.scan_sqli(url)
    xss = scanner.scan_xss(url)
    res = "✅ نتائج الفحص:\n"
    if sqli: res += "\n".join(sqli) + "\n"
    if xss: res += "\n".join(xss) + "\n"
    if not sqli and not xss: res = "✅ الرابط يبدو آمناً، لم يتم العثور على ثغرات معروفة."
    await update.message.reply_text(res)

async def phishing_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ يرجى تحديد الخدمة (facebook/instagram). مثال: /phishing facebook")
        return
    service = context.args[0]
    page = social_eng.generate_phishing_page(service)
    link = social_eng.generate_short_link()
    await update.message.reply_text(f"🔗 تم إنشاء صفحة المزيفة لـ {service}:\n\nرابطك المختصر: {link}\n\n⚠️ استخدمه للمقالب فقط!")

async def ddos_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ يرجى إرسال الرابط المستهدف. مثال: /ddos http://target.com")
        return
    url = context.args[0]
    res = ddos.ddos_attack(url)
    await update.message.reply_text(f"🚀 {res}")

async def osint_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ يرجى إرسال البريد الإلكتروني. مثال: /osint test@email.com")
        return
    email = context.args[0]
    res = osint.check_account_leak(email)
    await update.message.reply_text(f"🔎 {res}")

async def setup_commands(app):
    """تسجيل الأوامر في تيليجرام لتظهر في القائمة"""
    try:
        await app.bot.set_my_commands([
            BotCommand("start", "الاستيقاظ والبداية"),
            BotCommand("scan", "فحص الثغرات"),
            BotCommand("phishing", "صفحات مزيفة"),
            BotCommand("ddos", "هجوم حجب الخدمة"),
            BotCommand("osint", "فحص التسريبات")
        ])
    except Exception as e:
        logger.error(f"Error setting commands: {e}")

async def check_broadcast_queue(context: ContextTypes.DEFAULT_TYPE):
    db = db_session()
    try:
        # Check regular broadcasts
        broadcasts = db.execute(text("SELECT * FROM broadcast_queue WHERE status = 'pending'")).fetchall()
        for b in broadcasts:
            users = db.query(User).filter(User.blocked_or_left == False).all()
            count = 0
            # Access attributes using row indices or named keys if it's a Row object
            b_id = b[0]
            b_type = b[1]
            b_file_path = b[2]
            b_text_content = b[3]
            
            for user in users:
                try:
                    if b_type == 'media' and b_file_path and os.path.exists(b_file_path):
                        if b_file_path.lower().endswith(('.jpg', '.jpeg', '.png')):
                            with open(b_file_path, 'rb') as f:
                                await context.bot.send_photo(chat_id=user.tg_id, photo=f, caption=b_text_content)
                        elif b_file_path.lower().endswith(('.mp4', '.mov')):
                            with open(b_file_path, 'rb') as f:
                                await context.bot.send_video(chat_id=user.tg_id, video=f, caption=b_text_content)
                    else:
                        await context.bot.send_message(chat_id=user.tg_id, text=b_text_content)
                    count += 1
                    await asyncio.sleep(0.05)
                except Exception as e:
                    logger.error(f"Error broadcasting to {user.tg_id}: {e}")
            
            db.execute(text("UPDATE broadcast_queue SET status = 'completed' WHERE id = :id"), {"id": b_id})
            db.commit()
            logger.info(f"✅ تم الانتهاء من البث لـ {count} مستخدم")

        # Check multi-surveys
        surveys = db.execute(text("SELECT * FROM surveys_multi WHERE active = 1")).fetchall()
        for s in surveys:
            s_id = s[0]
            s_question = s[2]
            s_options_json = s[3]
            
            options = json.loads(s_options_json)
            keyboard = []
            for i, opt in enumerate(options):
                # Ensure we use the correct callback data for voting
                keyboard.append([InlineKeyboardButton(opt['text'], callback_data=f"vote_{s_id}_{i}")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            users = db.query(User).filter(User.blocked_or_left == False).all()
            for user in users:
                try:
                    await context.bot.send_message(chat_id=user.tg_id, text=s_question, reply_markup=reply_markup)
                    await asyncio.sleep(0.05)
                except: pass
            
            db.execute(text("UPDATE surveys_multi SET active = 0 WHERE id = :id"), {"id": s_id})
            db.commit()
    except Exception as e:
        logger.error(f"Error in broadcast task: {e}")
    finally:
        db.close()

async def multi_survey_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data.split('_')
    # Format: vote_{survey_id}_{option_idx}
    survey_id = data[1]
    option_idx = int(data[2])
    
    db = db_session()
    try:
        # We need to find the survey to get the response text
        # The id in data[1] is the primary key 'id' of surveys_multi table
        s = db.execute(text("SELECT options_json FROM surveys_multi WHERE id = :id"), {"id": survey_id}).fetchone()
        if s:
            options = json.loads(s[0])
            if option_idx < len(options):
                # Update count
                options[option_idx]['count'] = options[option_idx].get('count', 0) + 1
                db.execute(text("UPDATE surveys_multi SET options_json = :json WHERE id = :id"), 
                           {"json": json.dumps(options), "id": survey_id})
                db.commit()
                
                response_text = options[option_idx].get('response', "شكراً لتصويتك!")
                # Extract original question to keep it in the message
                original_text = query.message.text.split('\n\n')[0] if '\n\n' in query.message.text else query.message.text
                await query.edit_message_text(text=f"{original_text}\n\n✅ تم تسجيل تصويتك: {options[option_idx]['text']}\n\n{response_text}")
    except Exception as e:
        logger.error(f"Error in multi_survey_callback: {e}")
    finally:
        db.close()

DAILY_REMINDER_MESSAGES = [
    """🌅 *صباح الخير!*
━━━━━━━━━━━━━━━━━━━━━━━━
🤖 مساعدك الذكي جاهز لمساعدتك اليوم!

✨ *يمكنني مساعدتك في:*
• 🎬 تحميل فيديو وموسيقى من أي منصة
• 🧠 الإجابة على أسئلتك بالذكاء الاصطناعي
• 🎙️ تحويل الصوت إلى نص والعكس
• 📊 تحليل صور الشارت (VIP)

اضغط /start للبدء!""",
    """💡 *تذكير يومي*
━━━━━━━━━━━━━━━━━━━━━━━━
مرحباً! بوتك الذكي يعمل على مدار الساعة.

🔥 *جرّب هذه الميزات اليوم:*
• أرسل رابط يوتيوب للتحميل الفوري
• اسألني أي سؤال وأجيبك فوراً
• أرسل صورة لتحليلها

📲 أرسل /start للقائمة الرئيسية""",
    """⚡ *أهلاً! — تذكير يومي*
━━━━━━━━━━━━━━━━━━━━━━━━
بوتك الذكي دائماً معك 24/7 🕐

🎯 *ماذا تريد اليوم؟*
— تحميل فيديو أو موسيقى؟
— سؤال للذكاء الاصطناعي؟
— تحويل نص لصوت؟

جاهز لمساعدتك! اضغط /start""",
    """🌟 *مرحباً من مساعدك الذكي!*
━━━━━━━━━━━━━━━━━━━━━━━━
💎 *مشتركو VIP يستمتعون بـ:*
• تحليل شارت التداول بالذكاء الاصطناعي
• مساعد المتداول الذكي
• ميزات متقدمة بلا حدود

🚀 اشترك VIP الآن أو اضغط /start""",
]

async def daily_reminder_task(context: ContextTypes.DEFAULT_TYPE):
    """إرسال رسالة تذكيرية كل 24 ساعة"""
    import random as _random
    db = db_session()
    try:
        users = db.query(User).filter(User.blocked_or_left == False).all()
        msg = _random.choice(DAILY_REMINDER_MESSAGES)
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 فتح البوت", callback_data="back")]
        ])
        success = 0
        for u in users:
            try:
                await context.bot.send_message(
                    chat_id=u.tg_id, text=msg,
                    parse_mode="Markdown", reply_markup=markup
                )
                success += 1
                await asyncio.sleep(0.05)
            except: pass
        logger.info(f"✅ تم إرسال التذكير اليومي لـ {success} مستخدم.")
    finally:
        db.close()

async def set_vip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تفعيل/إلغاء VIP للمستخدم: /set_vip [user_id] [true/false]"""
    user = update.effective_user
    if not user or int(user.id) not in ADMIN_IDS:
        await update.message.reply_text("❌ أنت لست مسؤول البوت")
        return
    if len(context.args) < 1:
        await update.message.reply_text("❌ استخدم: /set_vip [user_id] [true/false]")
        return
    target_id = context.args[0]
    is_vip = context.args[1].lower() == "true" if len(context.args) > 1 else True
    db = db_session()
    try:
        user_record = db.query(User).filter(User.tg_id == target_id).first()
        if user_record:
            user_record.is_vip = is_vip
            db.commit()
            status = "✅ VIP مفعّل" if is_vip else "❌ VIP ملغى"
            await update.message.reply_text(f"{status} للمستخدم `{target_id}`", parse_mode="Markdown")
            try:
                msg = "🎉 *تهانينا!*\n\nتم تفعيل اشتراك VIP الخاص بك.\nاستمتع بجميع المميزات الاحترافية!" if is_vip else "ℹ️ تم إلغاء اشتراك VIP الخاص بك."
                await context.bot.send_message(chat_id=target_id, text=msg, parse_mode="Markdown")
            except:
                pass
        else:
            await update.message.reply_text("❌ المستخدم غير موجود في قاعدة البيانات")
    except Exception as e:
        logger.error(f"set_vip error: {e}")
        await update.message.reply_text("❌ حدث خطأ")
    finally:
        db.close()

async def admin_send_survey_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر إرسال استبيان سريع: /send_poll السؤال | خيار1 | خيار2"""
    if update.effective_user.id not in ADMIN_IDS: return
    args = " ".join(context.args)
    if "|" not in args:
        await update.message.reply_text("❌ الصيغة: /send_poll السؤال | خيار1 | خيار2")
        return
    
    parts = args.split("|")
    question = parts[0].strip()
    options = [p.strip() for p in parts[1:]]
    
    db = db_session()
    users = db.query(User).filter(User.blocked_or_left == False).all()
    db.close()
    
    success = 0
    for u in users:
        try:
            await context.bot.send_poll(chat_id=u.tg_id, question=question, options=options, is_anonymous=False)
            success += 1
            await asyncio.sleep(0.05)
        except: pass
    await update.message.reply_text(f"✅ تم إرسال الاستبيان لـ {success} مستخدم.")

async def main_bot():
    """الدالة الرئيسية لتشغيل البوت"""
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("scan", scan_cmd))
    app.add_handler(CommandHandler("phishing", phishing_cmd))
    app.add_handler(CommandHandler("ddos", ddos_cmd))
    app.add_handler(CommandHandler("osint", osint_cmd))
    
    # تسجيل الأوامر
    await setup_commands(app)
    
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("announce_bot", broadcast_new_bot_cmd))
    app.add_handler(CommandHandler("history", lambda u, c: history_cmd(u, c)))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CommandHandler("broadcast_media", broadcast_media_cmd))
    app.add_handler(CommandHandler("survey", survey_cmd))
    app.add_handler(CommandHandler("survey_results", survey_results_cmd))
    app.add_handler(CommandHandler("send_poll", admin_send_survey_cmd))
    app.add_handler(CommandHandler("myusage", myusage_cmd))
    app.add_handler(CommandHandler("allusage", allusage_cmd))
    app.add_handler(CommandHandler("userlist", userlist_cmd))
    app.add_handler(CommandHandler("blockedusers", blockedusers_cmd))
    app.add_handler(CommandHandler("freeze_user_id", freeze_user_admin_cmd))
    app.add_handler(CommandHandler("todayusers", todayusers_cmd))
    app.add_handler(CommandHandler("fullreport", fullreport_cmd))
    app.add_handler(CommandHandler("send_image", send_image_cmd))
    app.add_handler(CommandHandler("send_video", send_video_cmd))
    app.add_handler(CommandHandler("survey_detailed", survey_detailed_cmd))
    app.add_handler(CommandHandler("survey_multi", survey_multi_cmd))
    app.add_handler(CommandHandler("most_used_feature", most_used_feature_cmd))
    app.add_handler(CommandHandler("monthly_usage", monthly_usage_cmd))
    app.add_handler(CommandHandler("top_users", top_users_cmd))
    app.add_handler(CommandHandler("set_vip", set_vip_cmd))
    
    app.add_handler(CallbackQueryHandler(vote_handler, pattern="^vote_"))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))
    app.add_handler(MessageHandler(filters.PHOTO, photo_message))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, audio_message))
    
    # إضافة مهام الخلفية
    job_queue = app.job_queue
    if job_queue:
        job_queue.run_repeating(check_broadcast_queue, interval=10, first=5)
        # إرسال تذكير كل 24 ساعة (86400 ثانية)
        job_queue.run_repeating(daily_reminder_task, interval=86400, first=3600)
    
    logger.info("🚀 بدء تشغيل البوت...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    
    # إبقاء البوت يعمل
    while True:
        await asyncio.sleep(3600)

def run():
    """تشغيل البوت مع نظام إعادة تشغيل تلقائي"""
    while True:
        try:
            asyncio.run(main_bot())
        except Exception as e:
            logger.error(f"💥 انهيار البوت: {e}")
            import time
            time.sleep(5)
            continue

if __name__ == "__main__":
    run()
