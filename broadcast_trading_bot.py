#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
سكريبت إرسال رسالة جماعية لمستخدمي trading bot
يقرأ ملفات JSON ويرسل رسالة لكل مستخدم فعّال (غير محظور وغير مغادر)
"""

import json
import time
import requests
import os

# ==================== CONFIG ====================
TRADING_BOT_TOKEN = "8481729578:AAGCOp3OxblMDHP7Zvb_DKsoCtz1Crn8V9k"

MESSAGE = """🟢 *البوت عاد للعمل!*

السلام عليكم ورحمة الله وبركاته 👋

نُعلمكم بأن بوت التداول الذهبي عاد للعمل بشكل كامل ✅

🔹 جميع الخدمات متاحة الآن
🔹 إشارات الذهب XAUUSD تعمل بشكل طبيعي
🔹 تحديثات الأسعار مباشرة

اكتب /start للبدء 🚀"""

# ملفات JSON الخاصة بـ trading bot (التوكن: 8481729578...)
JSON_FILES = [
    "attached_assets/export_trading_bot_2026-06-20_1782508501701.json",
    "attached_assets/export_trading_bot_2026-06-20_1782508501852.json",
]

DELAY_BETWEEN_MESSAGES = 0.1  # ثانية بين كل رسالة (تجنب حد الإرسال)

# ==================== FUNCTIONS ====================

def load_users_from_file(filepath):
    """تحميل المستخدمين من ملف JSON"""
    users = {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        raw_users = data.get('users', [])
        for u in raw_users:
            tg_id = str(u.get('tg_id', '')).strip()
            if not tg_id:
                continue
            
            is_banned = u.get('is_banned', False)
            blocked = u.get('blocked_or_left', False)
            is_frozen = u.get('is_frozen', False)
            
            # تحويل من int إلى bool
            if isinstance(is_banned, int):
                is_banned = bool(is_banned)
            if isinstance(blocked, int):
                blocked = bool(blocked)
            if isinstance(is_frozen, int):
                is_frozen = bool(is_frozen)
            
            # فلترة: فقط المستخدمون الفعّالون
            if is_banned or blocked or is_frozen:
                continue
            
            name = u.get('name') or u.get('username') or u.get('first_name') or 'مستخدم'
            users[tg_id] = name
        
        print(f"  ✅ {filepath}: {len(raw_users)} مستخدم إجمالي، {len(users)} مؤهل")
    except Exception as e:
        print(f"  ❌ خطأ في قراءة {filepath}: {e}")
    
    return users


def send_message(bot_token, chat_id, text):
    """إرسال رسالة واحدة"""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        data = resp.json()
        if data.get('ok'):
            return True, None
        else:
            return False, data.get('description', 'Unknown error')
    except Exception as e:
        return False, str(e)


def broadcast(bot_token, users_dict, message):
    """إرسال رسالة جماعية"""
    total = len(users_dict)
    sent = 0
    failed = 0
    blocked_users = []
    
    print(f"\n📤 بدء الإرسال لـ {total} مستخدم...")
    print("=" * 50)
    
    for i, (tg_id, name) in enumerate(users_dict.items(), 1):
        ok, error = send_message(bot_token, tg_id, message)
        
        if ok:
            sent += 1
            print(f"  [{i}/{total}] ✅ {name} ({tg_id})")
        else:
            failed += 1
            blocked_users.append((tg_id, name, error))
            print(f"  [{i}/{total}] ❌ {name} ({tg_id}) — {error}")
        
        # تحقق من حد التيليجرام (30 رسالة/ثانية)
        time.sleep(DELAY_BETWEEN_MESSAGES)
        
        # طباعة تقدم كل 50 رسالة
        if i % 50 == 0:
            print(f"\n  📊 تقدم: {i}/{total} | ✅ {sent} | ❌ {failed}\n")
    
    return sent, failed, blocked_users


def main():
    print("=" * 60)
    print("🚀 سكريبت البث الجماعي — Trading Bot")
    print("=" * 60)
    
    # تحميل المستخدمين من جميع الملفات
    print("\n📂 تحميل المستخدمين من الملفات...")
    all_users = {}
    
    for filepath in JSON_FILES:
        if os.path.exists(filepath):
            users = load_users_from_file(filepath)
            all_users.update(users)  # دمج (يزيل التكرار تلقائياً بالـ tg_id)
        else:
            print(f"  ⚠️ الملف غير موجود: {filepath}")
    
    print(f"\n👥 إجمالي المستخدمين الفريدين المؤهلين: {len(all_users)}")
    
    if not all_users:
        print("❌ لا يوجد مستخدمون للإرسال.")
        return
    
    # تأكيد قبل الإرسال
    print(f"\n📝 الرسالة التي ستُرسل:")
    print("-" * 40)
    print(MESSAGE)
    print("-" * 40)
    
    confirm = input(f"\n⚠️  هل تريد إرسال الرسالة لـ {len(all_users)} مستخدم؟ (اكتب 'نعم' أو 'yes'): ").strip().lower()
    if confirm not in ('نعم', 'yes', 'y'):
        print("❌ تم الإلغاء.")
        return
    
    # إرسال
    sent, failed, blocked = broadcast(TRADING_BOT_TOKEN, all_users, MESSAGE)
    
    # ملخص
    print("\n" + "=" * 60)
    print("📊 ملخص النتائج:")
    print("=" * 60)
    print(f"  ✅ تم الإرسال بنجاح : {sent}")
    print(f"  ❌ فشل الإرسال      : {failed}")
    print(f"  📊 الإجمالي         : {sent + failed}")
    
    if blocked:
        print(f"\n⚠️  المستخدمون الذين لم تصل إليهم الرسالة ({len(blocked)}):")
        for tg_id, name, error in blocked[:20]:  # أول 20 فقط
            print(f"    • {name} ({tg_id}): {error}")
        if len(blocked) > 20:
            print(f"    ... و {len(blocked) - 20} آخرين")
    
    print("\n✅ انتهى البث الجماعي!")


if __name__ == "__main__":
    main()
