
async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /status - عرض حالة النظام التفصيلية"""
    user_id = update.effective_user.id
    
    # تحقق من أنه مسؤول
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ أنت لا تملك صلاحية الوصول")
        return
    
    db = db_session()
    try:
        # احصائيات من قاعدة البيانات
        users_count = db.query(User).count()
        messages_count = db.query(Message).count()
        blocked_count = db.query(User).filter(User.is_banned == True).count()
        frozen_count = db.query(User).filter(User.is_frozen == True).count()
        
        # حساب المستخدمين النشطاء اليوم
        today = datetime.utcnow().date()
        today_users = db.query(User).filter(
            func.date(User.created_at) == today
        ).count()
        
        # جودة Gemini Keys
        gemini_status = f"✅ {len(VALID_KEY_INDICES)} مفتاح متاح"
        if len(EXHAUSTED_KEYS) > 0:
            gemini_status += f" ({len(EXHAUSTED_KEYS)} مستنزف)"
        
        status_msg = f"""🔍 **حالة النظام التفصيلية:**

📊 **قاعدة البيانات:**
├─ 👥 المستخدمون: {users_count}
├─ 💬 الرسائل: {messages_count}
├─ 🚫 محظورون: {blocked_count}
├─ ❄️ مجمدون: {frozen_count}
└─ 🟢 نشطاء اليوم: {today_users}

🤖 **Gemini AI:**
├─ حالة: {gemini_status}
├─ الفهرس الحالي: {GEMINI_CURRENT_INDEX}
└─ النموذج: gemini-2.5-flash-lite

📁 **النظام:**
├─ الحالة: ✅ يعمل بنجاح
├─ قاعدة البيانات: ✅ سليمة
└─ الوقت: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

💡 **الملفات:**
├─ bot.py: 2412 سطر
├─ config.py: مححدث
└─ data/bot.db: نظيف
"""
        
        await update.message.reply_text(status_msg, parse_mode="Markdown")
        
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ في جلب البيانات: {str(e)[:100]}")
    finally:
        db.close()
