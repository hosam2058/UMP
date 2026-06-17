#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
import glob
import subprocess
from gtts import gTTS

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# إعداد التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
if not TOKEN:
    logger.error("❌ TELEGRAM_BOT_TOKEN غير معرف!")
    exit(1)

# بيانات الدفع
VODAFONE_CASH = "0102 648 9388"
WHATSAPP_NUMBER = "+201500236188"

# تعريف الحالات
START, VIDEO_DOWNLOAD, TEXT_SPEECH, AUDIO_TEXT = range(4)

# متغيرات النمط
MUSIC_MODE = "music"
VIDEO_MODE = "video"

# ========================
# قوائم الأزرار
# ========================

def get_main_menu():
    """القائمة الرئيسية"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎤 تحويل نص → صوت", callback_data='text_speech'),
            InlineKeyboardButton("🎙️ تحويل صوت → نص", callback_data='audio_text'),
        ],
        [
            InlineKeyboardButton("📚 كورسات التداول", callback_data='courses'),
            InlineKeyboardButton("💰 طرق الدفع", callback_data='payment'),
        ],
        [
            InlineKeyboardButton("📞 تواصل معنا", callback_data='contact'),
        ]
    ])

def get_back_menu():
    """زر الرجوع للقائمة الرئيسية"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data='back_to_main')]
    ])

# ========================
# معالجات الأوامر الرئيسية
# ========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالج الأمر /start"""
    user = update.message.from_user
    
    welcome_text = f"""
🤖 *أهلا وسهلا {user.first_name}!*

مرحباً بك في بوت المحترف العربي 🎉

هذا البوت يوفر لك خدمات احترافية:
✨ تنزيل الفيديوهات بسرعة فائقة
🎵 تنزيل الموسيقى بصيغة MP3
🎤 تحويل النصوص إلى صوت واضح
🎙️ تحويل التسجيلات الصوتية إلى نصوص
📚 دورات تدريبية في التداول
💳 طرق دفع آمنة وموثوقة

اختر من الخيارات أدناه للبدء 👇
    """
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=get_main_menu(),
        parse_mode='Markdown'
    )
    return START

# ========================
# معالجات الأزرار الرئيسية
# ========================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالج الأزرار الرئيسي"""
    query = update.callback_query
    await query.answer()
    
    # الرجوع للقائمة الرئيسية
    if query.data == 'back_to_main':
        await query.edit_message_text(
            text="🏠 أنت الآن في القائمة الرئيسية\n\nاختر الخدمة المطلوبة:",
            reply_markup=get_main_menu(),
            parse_mode='Markdown'
        )
        return START
    
    # قائمة الفيديو
    elif query.data == 'video_menu':
        context.user_data['download_mode'] = VIDEO_MODE
        video_text = """
📹 *تنزيل الفيديوهات*

⚡ الآن بسرعة فائقة جداً!

أرسل رابط الفيديو من:
• YouTube
• Facebook
• Instagram
• TikTok
• و منصات أخرى

📌 *طريقة الإرسال:*
ألصق الرابط مباشرة وسأقوم بتحميله بأسرع وقت! ⏱️

*مثال:*
`https://www.youtube.com/watch?v=...`
        """
        await query.edit_message_text(
            text=video_text,
            reply_markup=get_back_menu(),
            parse_mode='Markdown'
        )
        return VIDEO_DOWNLOAD
    
    # قائمة الموسيقى
    elif query.data == 'music_menu':
        context.user_data['download_mode'] = MUSIC_MODE
        music_text = """
🎵 *تنزيل الموسيقى بصيغة MP3*

⚡ تحميل سريع جداً!

أرسل رابط الأغنية من:
• YouTube
• Spotify
• SoundCloud
• و منصات أخرى

📌 *طريقة الإرسال:*
ألصق الرابط مباشرة وسيتم التحميل فوراً! ⏱️

✨ سيتم تحويل الصوت إلى MP3 تلقائياً

*مثال:*
`https://www.youtube.com/watch?v=...`
        """
        await query.edit_message_text(
            text=music_text,
            reply_markup=get_back_menu(),
            parse_mode='Markdown'
        )
        return VIDEO_DOWNLOAD
    
    # تحويل النص إلى صوت
    elif query.data == 'text_speech':
        speech_text = """
🎤 *تحويل النص إلى صوت*

أرسل النص الذي تريد تحويله إلى صوت واضح واحترافي.

✨ المميزات:
• صوت عربي احترافي
• وضوح صوتي 100%
• معالجة فورية
• لهجة مصرية طبيعية

📌 فقط أرسل النص مباشرة:
        """
        await query.edit_message_text(
            text=speech_text,
            reply_markup=get_back_menu(),
            parse_mode='Markdown'
        )
        return TEXT_SPEECH
    
    # تحويل الصوت إلى نص
    elif query.data == 'audio_text':
        audio_text = """
🎙️ *تحويل الصوت إلى نص*

أرسل الملف الصوتي أو استخدم خيار الرسالة الصوتية.

✨ المميزات:
• تحويل دقيق وسريع
• دعم الحروف العربية
• نتائج واضحة

📌 أرسل الملف الصوتي مباشرة:
        """
        await query.edit_message_text(
            text=audio_text,
            reply_markup=get_back_menu(),
            parse_mode='Markdown'
        )
        return AUDIO_TEXT
    
    # الكورسات
    elif query.data == 'courses':
        courses_text = """
📚 *كورسات التداول المدفوعة*

🥇 *كورسات متخصصة في التحليل الفني*

1️⃣ كورس إسماعيل الشكري
   📖 التحليل الفني المتقدم

2️⃣ كورس محمد مهدي
   📖 استراتيجيات التداول المربحة

3️⃣ كورس محمود سعد
   📖 أساسيات التداول الاحترافي

4️⃣ دورة إيهاب المصري الأولى
   📖 تدريب شامل للمبتدئين

5️⃣ دورة إيهاب المصري الثانية
   📖 مستويات متقدمة

💳 *لطلب أي كورس:*
تواصل معنا عبر WhatsApp
        """
        await query.edit_message_text(
            text=courses_text,
            reply_markup=get_back_menu(),
            parse_mode='Markdown'
        )
        return START
    
    # طرق الدفع
    elif query.data == 'payment':
        payment_text = f"""
💳 *طرق الدفع الآمنة والموثوقة*

📱 *فودافون كاش*
━━━━━━━━━━━━━━━━━━━━━━━
🔢 رقم التحويل: `{VODAFONE_CASH}`
📞 واتساب للتأكيد: `{WHATSAPP_NUMBER}`

✨ *خطوات الدفع:*
1️⃣ احول المبلغ عبر فودافون كاش
2️⃣ أرسل صورة التحويل على WhatsApp
3️⃣ سيتم تفعيل الخدمة فوراً ✅

🚀 *المميزات:*
• آمن وموثوق 100%
• تأكيد فوري
• دعم عملاء متميز
        """
        await query.edit_message_text(
            text=payment_text,
            reply_markup=get_back_menu(),
            parse_mode='Markdown'
        )
        return START
    
    # التواصل
    elif query.data == 'contact':
        contact_text = f"""
📞 *تواصل معنا مباشرة*

━━━━━━━━━━━━━━━━━━━━━━━

📱 *واتساب (الوسيلة الأسرع)*
🔗 الرابط المباشر:
https://wa.me/{WHATSAPP_NUMBER.replace('+', '')}

📞 الرقم: {WHATSAPP_NUMBER}

⏰ *أوقات العمل:*
• السبت - الخميس: 10 صباحاً - 10 مساءً
• الجمعة: 2 ظهراً - 10 مساءً

💬 *الخدمات:*
✅ الرد على الاستفسارات
✅ دعم فني سريع
✅ استقبال الطلبات الجديدة
✅ حل المشاكل فوراً

شكراً لاختيارك خدماتنا! 🙏
        """
        await query.edit_message_text(
            text=contact_text,
            reply_markup=get_back_menu(),
            parse_mode='Markdown'
        )
        return START

# ========================
# معالجات الرسائل
# ========================

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالج الرسائل النصية"""
    user_text = update.message.text
    
    # تحميل الفيديو أو الموسيقى - التحقق من الروابط
    is_video_link = (
        user_text.lower().startswith('http://') or 
        user_text.lower().startswith('https://') or
        'youtube' in user_text.lower() or 
        'youtu.be' in user_text.lower() or 
        'tiktok' in user_text.lower() or 
        'instagram' in user_text.lower() or
        'facebook' in user_text.lower() or
        'soundcloud' in user_text.lower() or
        'spotify' in user_text.lower()
    )
    
    if is_video_link:
        download_mode = context.user_data.get('download_mode', VIDEO_MODE)
        
        status_msg = await update.message.reply_text(
            "⏳ جاري التحميل السريع...\n\n"
            "🔄 يرجى الانتظار (قد يستغرق حتى دقيقة)",
            parse_mode='Markdown'
        )
        
        try:
            # إنشاء مجلد التحميل
            os.makedirs("downloads", exist_ok=True)
            
            # حذف الملفات القديمة بعناية
            try:
                for old_file in glob.glob("downloads/*"):
                    os.remove(old_file)
            except:
                pass
            
            output_path = "downloads/video.%(ext)s"
            url_lower = user_text.lower()
            
            # الخيارات الأساسية المشتركة
            base_command = [
                'yt-dlp',
                '--socket-timeout', '45',
                '--retries', '15',
                '--fragment-retries', '15',
                '--http-chunk-size', '1048576',
                '--add-header', 'User-Agent:Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                '--add-header', 'Accept-Language:en-US,en;q=0.9',
                '--add-header', 'Accept-Charset:utf-8',
                '--no-warnings',
                '-q',
            ]
            
            # معالجة خاصة لـ YouTube
            if 'youtube' in url_lower or 'youtu.be' in url_lower:
                if download_mode == MUSIC_MODE:
                    command = base_command + [
                        '--extractor-args', 'youtube:player_client=web',
                        '-f', 'bestaudio/best',
                        '-x', '--audio-format', 'mp3',
                        '--audio-quality', '192',
                        '-o', output_path,
                        user_text
                    ]
                else:
                    command = base_command + [
                        '--extractor-args', 'youtube:player_client=web',
                        '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo[ext=mp4]+bestaudio/best[ext=mp4]/best',
                        '--merge-output-format', 'mp4',
                        '-o', output_path,
                        user_text
                    ]
            
            # معالجة خاصة لـ Instagram
            elif 'instagram' in url_lower or 'ig' in url_lower:
                command = base_command + [
                    '-f', 'best[ext=mp4]/best/best[ext=webm]',
                    '--compat-opts', 'no-youtube-unavailable-videos',
                    '-o', output_path,
                    user_text
                ]
            
            # معالجة الموسيقى العامة
            elif download_mode == MUSIC_MODE:
                command = base_command + [
                    '-f', 'bestaudio/best',
                    '-x',
                    '--audio-format', 'mp3',
                    '--audio-quality', '192',
                    '-o', output_path,
                    user_text
                ]
            
            # معالجة الفيديو العامة (TikTok, Facebook, إلخ)
            else:
                command = base_command + [
                    '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo[ext=mp4]+bestaudio/best[ext=mp4]/best',
                    '--merge-output-format', 'mp4',
                    '-o', output_path,
                    user_text
                ]
            
            # تنفيذ الأمر
            result = subprocess.run(command, capture_output=True, timeout=90, text=True)
            
            if result.returncode == 0:
                # البحث عن الملف المحمل
                files = glob.glob("downloads/*")
                
                if files:
                    file_path = files[0]
                    file_size = os.path.getsize(file_path) / (1024 * 1024)
                    file_name = os.path.basename(file_path)
                    
                    logger.info(f"✅ تم التحميل: {file_name} ({file_size:.1f} MB)")
                    
                    await status_msg.edit_text(
                        f"✅ تم التحميل بنجاح! 🎉\n\n"
                        f"📊 حجم الملف: {file_size:.1f} MB\n"
                        f"🚀 جاري الإرسال...",
                        parse_mode='Markdown'
                    )
                    
                    # إرسال الملف
                    try:
                        with open(file_path, 'rb') as f:
                            if download_mode == MUSIC_MODE:
                                await update.message.reply_audio(
                                    audio=f,
                                    caption="🎵 تم تحميل الأغنية بنجاح! ✅"
                                )
                            else:
                                await update.message.reply_video(
                                    video=f,
                                    caption="🎬 تم تحميل الفيديو بنجاح! ✅"
                                )
                        
                        await update.message.reply_text(
                            "✅ اكتمل الإرسال بنجاح!\n\n"
                            "هل تريد تحميل ملف آخر؟",
                            reply_markup=get_back_menu()
                        )
                        
                    except Exception as e:
                        logger.error(f"❌ خطأ في الإرسال: {str(e)}")
                        await update.message.reply_text(
                            f"❌ خطأ في الإرسال\n\n{str(e)[:100]}",
                            reply_markup=get_back_menu()
                        )
                else:
                    logger.warning("لم يتم العثور على الملف المحمل")
                    await status_msg.edit_text(
                        "❌ لم يتم العثور على الملف\n\nحاول مرة أخرى",
                        reply_markup=get_back_menu()
                    )
            else:
                error = result.stderr[-300:] if result.stderr else 'خطأ غير معروف'
                logger.error(f"❌ فشل التحميل: {error}")
                await status_msg.edit_text(
                    f"❌ فشل التحميل\n\n{error[:200]}",
                    reply_markup=get_back_menu()
                )
                
        except subprocess.TimeoutExpired:
            logger.error("انتهت مهلة التحميل")
            await status_msg.edit_text(
                "❌ انتهت مهلة التحميل\n\nحاول مرة أخرى",
                reply_markup=get_back_menu()
            )
        except Exception as e:
            logger.error(f"❌ خطأ: {str(e)}")
            await status_msg.edit_text(
                f"❌ خطأ: {str(e)[:100]}",
                reply_markup=get_back_menu()
            )
        
        return VIDEO_DOWNLOAD
    
    # تحويل النص إلى صوت
    else:
        try:
            status_msg = await update.message.reply_text("⏳ جاري التحويل...")
            
            tts = gTTS(
                text=user_text,
                lang='ar',
                slow=False,
                tld='com.eg'
            )
            
            audio_path = 'output_voice.mp3'
            tts.save(audio_path)
            
            with open(audio_path, 'rb') as f:
                await update.message.reply_audio(
                    audio=f,
                    caption="🎤 تم التحويل بنجاح! ✅"
                )
            
            await update.message.reply_text(
                "✅ تم التحويل!\n\nاختر خدمة أخرى",
                reply_markup=get_back_menu()
            )
            
            os.remove(audio_path)
            
        except Exception as e:
            logger.error(f"❌ خطأ في التحويل: {str(e)}")
            await update.message.reply_text(
                f"❌ خطأ: {str(e)[:100]}",
                reply_markup=get_back_menu()
            )
        
        return TEXT_SPEECH

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """معالج الملفات الصوتية"""
    await update.message.reply_text(
        "🎙️ هذه الخدمة قريباً جداً 🔜",
        reply_markup=get_back_menu()
    )
    return AUDIO_TEXT

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالج الملفات"""
    await update.message.reply_text(
        "📁 استخدم الأزرار لاختيار الخدمة",
        reply_markup=get_back_menu()
    )

# ========================
# الدالة الرئيسية
# ========================

async def set_commands(app: Application):
    """إضافة قائمة الأوامر"""
    commands = [
        BotCommand("start", "🏠 القائمة الرئيسية"),
        BotCommand("video", "📹 الفيديوهات"),
        BotCommand("music", "🎵 الموسيقى"),
    ]
    await app.bot.set_my_commands(commands)

def main() -> None:
    """بدء البوت"""
    app = Application.builder().token(TOKEN).build()
    app.post_init = set_commands
    
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message),
            MessageHandler(filters.VOICE, handle_voice),
            MessageHandler(filters.Document.ALL, handle_document),
        ],
        states={
            START: [CallbackQueryHandler(button_handler)],
            VIDEO_DOWNLOAD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message),
                CallbackQueryHandler(button_handler),
            ],
            TEXT_SPEECH: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message),
                CallbackQueryHandler(button_handler),
            ],
            AUDIO_TEXT: [
                MessageHandler(filters.VOICE, handle_voice),
                CallbackQueryHandler(button_handler),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
        per_message=False,
    )
    
    app.add_handler(conv_handler)
    
    logger.info("✅ البوت الاحترافي جاهز للعمل! 🚀")
    print("\n" + "="*50)
    print("🤖 البوت العربي الاحترافي يعمل الآن")
    print("="*50)
    print(f"📱 WhatsApp: {WHATSAPP_NUMBER}")
    print(f"💰 فودافون كاش: {VODAFONE_CASH}")
    print("✅ جميع الميزات جاهزة!")
    print("⏹️  اضغط Ctrl+C للإيقاف\n")
    
    app.run_polling(allowed_updates=['message', 'callback_query'], drop_pending_updates=True)

if __name__ == '__main__':
    main()
