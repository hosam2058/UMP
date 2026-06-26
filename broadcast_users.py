#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
سكريبت إرسال رسالة جماعية لمستخدمي trading bot
يقرأ التوكن والمستخدمين مباشرة من قاعدة البيانات
"""

import sqlite3
import time
import requests
import os
import sys

# ==================== الرسالة ====================
MESSAGE = """🟢 *البوت عاد للعمل!*

السلام عليكم ورحمة الله وبركاته 👋

نُعلمكم بأن بوت التداول الذهبي عاد للعمل بشكل كامل ✅

🔹 جميع الخدمات متاحة الآن
🔹 إشارات الذهب XAUUSD تعمل بشكل طبيعي
🔹 تحديثات الأسعار مباشرة

اكتب /start للبدء 🚀"""

# ==================== إعدادات ====================
# مسار قاعدة البيانات
DB_PATH = os.getenv("DB_PATH", "data/bot.db")

# توكن البوت — يُقرأ من متغير البيئة أو من trading_bot.py تلقائياً
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

DELAY = 0.05  # ثانية بين كل رسالة

# ==================== دوال ====================

def find_token_from_bot():
    """استخراج التوكن من trading_bot.py إذا لم يكن محدداً"""
    for fname in ["trading_bot.py", "bot.py"]:
        if os.path.exists(fname):
            with open(fname, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "TOKEN" in line.upper() and "=" in line and ":" in line:
                        # استخراج التوكن من السطر
                        for part in line.split('"'):
                            if len(part) > 30 and ":" in part and part.count(":") == 1:
                                return part.strip()
                        for part in line.split("'"):
                            if len(part) > 30 and ":" in part and part.count(":") == 1:
                                return part.strip()
    return None


def get_users_from_db(db_path):
    """جلب المستخدمين الفعّالين من قاعدة البيانات"""
    if not os.path.exists(db_path):
        print(f"❌ قاعدة البيانات غير موجودة: {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # جرّب عدة أعمدة ممكنة
    try:
        cursor.execute("""
            SELECT tg_id, name FROM users
            WHERE (is_banned = 0 OR is_banned IS NULL)
              AND (blocked_or_left = 0 OR blocked_or_left IS NULL)
              AND (is_frozen = 0 OR is_frozen IS NULL)
        """)
    except Exception:
        try:
            cursor.execute("SELECT tg_id, name FROM users")
        except Exception as e:
            print(f"❌ خطأ في قراءة الجدول: {e}")
            conn.close()
            sys.exit(1)

    rows = cursor.fetchall()
    conn.close()

    users = {}
    for row in rows:
        tg_id = str(row[0]).strip()
        name = str(row[1]).strip() if row[1] else "مستخدم"
        if tg_id:
            users[tg_id] = name

    return users


def send_message(token, chat_id, text):
    """إرسال رسالة واحدة"""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }, timeout=10)
        d = r.json()
        if d.get("ok"):
            return True, None
        return False, d.get("description", "?")
    except Exception as e:
        return False, str(e)


def broadcast(token, users, message):
    """إرسال جماعي"""
    total = len(users)
    sent = failed = 0

    print(f"\n📤 بدء الإرسال لـ {total} مستخدم...")
    print("=" * 50)

    for i, (tg_id, name) in enumerate(users.items(), 1):
        ok, err = send_message(token, tg_id, message)
        if ok:
            sent += 1
            print(f"[{i}/{total}] ✅ {name} ({tg_id})")
        else:
            failed += 1
            print(f"[{i}/{total}] ❌ {name} ({tg_id}) — {err}")
        time.sleep(DELAY)

        if i % 50 == 0:
            print(f"\n  📊 تقدم: {i}/{total} | ✅ {sent} | ❌ {failed}\n")

    return sent, failed


# ==================== تشغيل ====================
if __name__ == "__main__":
    print("=" * 60)
    print("🚀 بث جماعي — Trading Bot")
    print("=" * 60)

    # 1. التوكن
    token = BOT_TOKEN
    if not token:
        token = find_token_from_bot()
    if not token:
        token = input("🔑 أدخل توكن البوت: ").strip()
    if not token:
        print("❌ لم يتم تحديد التوكن.")
        sys.exit(1)

    print(f"✅ التوكن: {token[:15]}...")

    # 2. تحقق من التوكن
    r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
    info = r.json()
    if not info.get("ok"):
        print(f"❌ التوكن غير صالح: {info.get('description')}")
        sys.exit(1)
    bot_name = info["result"].get("username", "?")
    print(f"✅ البوت: @{bot_name}")

    # 3. المستخدمون
    users = get_users_from_db(DB_PATH)
    print(f"👥 المستخدمون المؤهلون: {len(users)}")

    if not users:
        print("❌ لا يوجد مستخدمون.")
        sys.exit(0)

    # 4. تأكيد
    print(f"\n📝 الرسالة:\n{'-'*40}\n{MESSAGE}\n{'-'*40}")
    confirm = input(f"\n⚠️  إرسال لـ {len(users)} مستخدم؟ (نعم/yes): ").strip().lower()
    if confirm not in ("نعم", "yes", "y"):
        print("❌ إلغاء.")
        sys.exit(0)

    # 5. إرسال
    sent, failed = broadcast(token, users, MESSAGE)

    # 6. ملخص
    print("\n" + "=" * 60)
    print(f"✅ تم الإرسال : {sent}")
    print(f"❌ فشل        : {failed}")
    print(f"📊 الإجمالي   : {sent + failed}")
