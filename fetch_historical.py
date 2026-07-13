#!/usr/bin/env python3
"""
fetch_historical.py
===================
أداة تحضير بيانات — جلب XAUUSD M5 التاريخية من Twelve Data API.
تُشغَّل يدوياً فقط، ليست جزءاً من التشغيل الحي (لا تُضاف إلى start_all.sh).

الاستخدام:
    python fetch_historical.py [--days 90] [--output backtest_data/xauusd_m5.csv] [--append]

المتطلبات:
    • TWELVE_DATA_API_KEY مُعيَّن في البيئة (Replit Secrets أو export)

حدود الخطة المجانية — Basic (Twelve Data):
    • 8  API credits / minute  → تأخير 8 ثوانٍ بين الطلبات (≤ 7.5 طلب/دقيقة)
    • 800 API credits / day
    • outputsize أقصاه 5000 شمعة / طلب ≈ 17 يوم تداول لـ XAU/USD
    • كل طلب time_series = 1 credit
    • XAU/USD (معدن ثمين) لا يُرسل حقل volume — يُعوَّض بـ "0" تلقائياً
"""

import argparse
import csv
import os
import sys
import time
from datetime import datetime, timedelta

import requests

# ──────────────────────────────────────────────────────────────
# الثوابت
# ──────────────────────────────────────────────────────────────
API_BASE       = "https://api.twelvedata.com/time_series"
SYMBOL         = "XAU/USD"
INTERVAL       = "5min"
OUTPUTSIZE     = 5000          # أقصى عدد شموع / طلب (Basic plan)
SLEEP_BETWEEN  = 8             # ثوانٍ بين الطلبات — آمن تحت حد 8 req/min
CANDLE_MINUTES = 5
DEFAULT_DAYS   = 90
DATETIME_FMT   = "%Y-%m-%d %H:%M:%S"
MAX_DAILY_REQUESTS = 700       # حد احتياطي دون 800 اليومي


# ──────────────────────────────────────────────────────────────
# المساعدات
# ──────────────────────────────────────────────────────────────

def get_api_key() -> str:
    key = os.getenv("TWELVE_DATA_API_KEY", "").strip()
    if not key:
        sys.exit(
            "\n[خطأ] المتغير TWELVE_DATA_API_KEY غير مُعيَّن.\n"
            "أضفه في Replit Secrets أو نفّذ:  export TWELVE_DATA_API_KEY=مفتاحك\n"
        )
    return key


def fetch_batch(api_key: str, end_date: str = None) -> list:
    """
    يجلب دفعة واحدة بترتيب تنازلي (أحدث → أقدم).
    end_date: إذا حُدِّد، يجلب الشموع التي تسبقه (للتصفح للخلف).
    يعيد قائمة قواميس [{datetime, open, high, low, close, ...}].
    """
    params = {
        "symbol":     SYMBOL,
        "interval":   INTERVAL,
        "outputsize": OUTPUTSIZE,
        "order":      "desc",
        "apikey":     api_key,
    }
    if end_date:
        params["end_date"] = end_date

    for attempt in range(3):
        try:
            r = requests.get(API_BASE, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
            break
        except requests.RequestException as exc:
            print(f"  [شبكة] محاولة {attempt+1}/3 فشلت: {exc}", file=sys.stderr)
            if attempt < 2:
                time.sleep(15)
    else:
        return []

    status = data.get("status")
    if status != "ok":
        code = data.get("code", "?")
        msg  = data.get("message", str(data))
        if str(code) == "429":
            print("  [429] تجاوز Rate Limit — انتظار 65 ثانية...", file=sys.stderr)
            time.sleep(65)
            return fetch_batch(api_key, end_date)   # إعادة محاولة واحدة
        print(f"  [خطأ API] {code}: {msg}", file=sys.stderr)
        return []

    return data.get("values", [])


def is_weekend_gap(dt_from: datetime, dt_to: datetime) -> bool:
    """
    هل الفجوة بين شمعتين تشمل فترة عطلة نهاية الأسبوع؟
    الذهب يتوقف: جمعة ~22:00 UTC → أحد ~22:00 UTC
    """
    cur = dt_from
    while cur < dt_to:
        wd = cur.weekday()
        if wd == 5:                              # Saturday
            return True
        if wd == 4 and cur.hour >= 22:           # Friday after 22:00
            return True
        if wd == 6 and cur.hour < 22:            # Sunday before 22:00
            return True
        cur += timedelta(hours=1)
    return False


def load_existing_csv(path: str) -> dict:
    """يقرأ CSV موجود → {datetime_str: row_dict}."""
    rows = {}
    if not os.path.exists(path):
        return rows
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows[row["datetime"]] = row
    print(f"[تحميل] وُجدت {len(rows):,} شمعة في {path}")
    return rows


def save_csv(path: str, rows: dict) -> None:
    """يحفظ الشموع في CSV مرتبة تصاعدياً (أقدم أولاً)."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    sorted_rows = sorted(rows.values(), key=lambda r: r["datetime"])
    fieldnames  = ["datetime", "open", "high", "low", "close", "volume"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(sorted_rows)


def quality_report(rows: dict) -> None:
    """يطبع تقرير جودة البيانات على stdout."""
    if not rows:
        print("\n[تقرير] لا توجد بيانات.")
        return

    dts = sorted(datetime.strptime(k, DATETIME_FMT) for k in rows)
    total    = len(dts)
    start_dt = dts[0]
    end_dt   = dts[-1]
    span_days = (end_dt - start_dt).days

    # فجوات مشبوهة (> 15 دقيقة خارج عطل نهاية الأسبوع)
    GAP_THRESHOLD = 15   # دقيقة
    suspicious_gaps = []
    for i in range(1, total):
        gap_min = (dts[i] - dts[i-1]).total_seconds() / 60
        if gap_min > GAP_THRESHOLD:
            if not is_weekend_gap(dts[i-1], dts[i]):
                suspicious_gaps.append((dts[i-1], dts[i], int(gap_min)))

    print()
    print("═" * 62)
    print("   تقرير جودة البيانات — XAUUSD M5")
    print("═" * 62)
    print(f"   إجمالي الشموع المحفوظة : {total:>8,}")
    print(f"   أقدم شمعة              : {start_dt}")
    print(f"   أحدث شمعة              : {end_dt}")
    print(f"   الفترة المُغطاة        : {span_days} يوم تقويمي")
    print(f"   فجوات مشبوهة (خارج عطل): {len(suspicious_gaps)}")
    if suspicious_gaps:
        print()
        print("   تفاصيل الفجوات المشبوهة (أكبر 20 فجوة):")
        top = sorted(suspicious_gaps, key=lambda g: -g[2])[:20]
        for g_from, g_to, g_min in top:
            hrs = g_min // 60
            mins = g_min % 60
            label = f"{hrs}س {mins}د" if hrs else f"{mins}د"
            print(f"     {g_from}  →  {g_to}  ({label})")
    print("═" * 62)
    print()


# ──────────────────────────────────────────────────────────────
# الدالة الرئيسية
# ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="جلب XAUUSD M5 من Twelve Data وحفظها في CSV"
    )
    parser.add_argument("--days",   type=int, default=DEFAULT_DAYS,
                        help=f"أيام التقويم المراد جلبها (افتراضي: {DEFAULT_DAYS})")
    parser.add_argument("--output", default="backtest_data/xauusd_m5.csv",
                        help="مسار ملف CSV الناتج")
    parser.add_argument("--append", action="store_true",
                        help="دمج مع CSV موجود بدل الكتابة من الصفر")
    args = parser.parse_args()

    api_key      = get_api_key()
    target_end   = datetime.utcnow()
    target_start = target_end - timedelta(days=args.days)

    print(f"\n[بدء] جلب {SYMBOL} M5")
    print(f"      الهدف : {target_start.strftime('%Y-%m-%d')} → {target_end.strftime('%Y-%m-%d')} ({args.days} يوم)")
    print(f"      الإخراج: {args.output}")
    print(f"      التأخير: {SLEEP_BETWEEN}s بين الطلبات (خطة Basic: 8 req/min)\n")

    # تحقق من حالة الحساب والاستخدام اليومي
    try:
        usage_r = requests.get(
            "https://api.twelvedata.com/api_usage",
            params={"apikey": api_key}, timeout=10
        )
        u = usage_r.json()
        daily_used  = u.get("daily_usage", "?")
        daily_limit = u.get("plan_daily_limit", 800)
        plan        = u.get("plan_category", "?")
        print(f"[حساب] خطة: {plan} | الاستخدام اليومي: {daily_used}/{daily_limit} credits")
        remaining_credits = daily_limit - (daily_used if isinstance(daily_used, int) else 0)
        if isinstance(daily_used, int) and remaining_credits < 5:
            sys.exit(f"\n[توقف] لا يكفي رصيد اليوم ({remaining_credits} credits متبقية).")
    except Exception as exc:
        print(f"[تحذير] تعذّر جلب بيانات الاستخدام: {exc}")

    # تحميل بيانات موجودة إن طُلب --append
    all_rows = load_existing_csv(args.output) if args.append else {}

    request_count  = 0
    end_date_param = None    # None = ابدأ من الآن

    while True:
        request_count += 1
        label = end_date_param or "الآن"
        print(f"[طلب #{request_count}] حتى: {label}", end=" ... ", flush=True)

        batch = fetch_batch(api_key, end_date=end_date_param)

        if not batch:
            print("لا بيانات — توقف.")
            break

        # إضافة الشموع الجديدة (الـ API لا يُرسل volume للمعادن — نعوّضها بـ "0")
        added        = 0
        batch_oldest = None
        for row in batch:
            dt_str = row["datetime"]
            row.setdefault("volume", "0")
            if dt_str not in all_rows:
                all_rows[dt_str] = row
                added += 1
            dt = datetime.strptime(dt_str, DATETIME_FMT)
            if batch_oldest is None or dt < batch_oldest:
                batch_oldest = dt

        print(f"{len(batch):,} شمعة مُستلمة | {added:,} جديدة | المجموع: {len(all_rows):,}")

        # هل وصلنا للهدف؟
        if batch_oldest is None or batch_oldest <= target_start:
            print(f"[اكتمل] وصلنا إلى {batch_oldest} ← قبل الهدف {target_start.date()}")
            break

        # الـ API أعادت أقل من نصف المطلوب → انتهاء البيانات المتاحة
        if len(batch) < OUTPUTSIZE * 0.5:
            print(f"[نهاية] الـ API أعادت {len(batch)} شمعة فقط — وصلنا لأقدم بيانات متاحة")
            break

        # حد الطلبات اليومية الاحتياطي
        if request_count >= MAX_DAILY_REQUESTS:
            print(f"[توقف] وصلنا للحد الاحتياطي ({MAX_DAILY_REQUESTS} طلباً)")
            break

        # اضبط نهاية الطلب التالي = أقدم datetime مستلمة - 1 دقيقة
        next_end       = batch_oldest - timedelta(minutes=1)
        end_date_param = next_end.strftime(DATETIME_FMT)

        print(f"[انتظار] {SLEEP_BETWEEN}s ...")
        time.sleep(SLEEP_BETWEEN)

    # ── حفظ وتقرير ──
    if not all_rows:
        print("\n[خطأ] لم تُجمع أي بيانات. تحقق من صحة TWELVE_DATA_API_KEY.")
        sys.exit(1)

    print(f"\n[حفظ] {len(all_rows):,} شمعة → {args.output}")
    save_csv(args.output, all_rows)
    print("[حفظ] اكتمل ✓")

    quality_report(all_rows)


if __name__ == "__main__":
    main()
