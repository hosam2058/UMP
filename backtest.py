#!/usr/bin/env python3
"""
backtest.py
===========
اختبار model_1_statistical بمعزل تام عن باقي النماذج.
تُشغَّل يدوياً فقط — ليست جزءاً من التشغيل الحي (لا تُضاف إلى start_all.sh).

الاستخدام:
    python backtest.py [--input backtest_data/xauusd_m5.csv]
                       [--quarter-months 3]
                       [--min-resolved 30]

ضمانات Lookahead Bias:
    • النافذة المرئية عند الشمعة i = candles[0:i+1] فقط (slice صارم)
    • Entry = opens[i+1] × معامل انزلاق (لا closes[i] — Execution Fill Fix)
    • تقييم النتيجة يبدأ من i+1، وعند تعارض TP+SL في نفس الشمعة: SL أولاً
"""

import argparse
import csv
import math
import sys
from datetime import datetime

# ── الثوابت (مطابقة للكود الحي في trading_bot.py) ──────────────────────────
DATETIME_FMT  = "%Y-%m-%d %H:%M:%S"
WARMUP_BARS   = 30     # الحد الأدنى لـ model_1 (prices[-20] + prices[-10] + هامش)
COOLDOWN_BARS = 6      # 30 دقيقة ÷ 5 دقائق/شمعة = 6 شموع  (signal_cooldown الحي)
ATR_PERIOD    = 14     # نفس الافتراضي في TechnicalAnalyzer.atr()

# مضاعفات TP/SL (مطابقة لـ generate_signal في trading_bot.py)
TP1_MULT = 1.0
TP2_MULT = 1.8
TP3_MULT = 2.8
SL_MULT  = 1.2

# انزلاق التنفيذ (مطابق للكود الحي)
BUY_SLIP  = 1.0002
SELL_SLIP = 0.9998


# ══════════════════════════════════════════════════════════════════════════════
#  تحميل البيانات
# ══════════════════════════════════════════════════════════════════════════════

def load_csv(path: str) -> list:
    """
    يقرأ CSV ويُعيد قائمة شموع مُرتَّبة تصاعدياً بالوقت.
    كل عنصر: {"dt", "open", "high", "low", "close"}
    """
    rows = []
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                rows.append({
                    "dt":    datetime.strptime(row["datetime"], DATETIME_FMT),
                    "open":  float(row["open"]),
                    "high":  float(row["high"]),
                    "low":   float(row["low"]),
                    "close": float(row["close"]),
                })
    except FileNotFoundError:
        sys.exit(
            f"\n[خطأ] الملف غير موجود: {path}\n"
            f"شغّل أولاً:  python fetch_historical.py --days 730\n"
        )
    except Exception as exc:
        sys.exit(f"\n[خطأ] فشل قراءة CSV: {exc}")

    rows.sort(key=lambda r: r["dt"])   # ترتيب تصاعدي: ضمان أساسي ضد Lookahead
    return rows


# ══════════════════════════════════════════════════════════════════════════════
#  النموذج والمؤشرات — نُسخ مستقلة مطابقة للكود الحي
# ══════════════════════════════════════════════════════════════════════════════

def model_1_statistical(prices: list) -> str:
    """
    نسخة مستقلة من _model_1_statistical() في trading_bot.py.
    تستقبل slice ينتهي عند الشمعة الحالية فقط — لا تعرف ما بعدها.

    المنطق (commit f650177 — العتبات المُعايَرة لشموع 5 دقائق):
      z-score < -1.5 → buy   |  z-score > 1.5 → sell
      fallback: trend ±0.3% على 10 شموع (50 دقيقة)
    """
    if len(prices) < 30:
        return "neutral"

    mean     = sum(prices[-20:]) / 20
    variance = sum((p - mean) ** 2 for p in prices[-20:]) / 20
    std      = math.sqrt(variance)
    current  = prices[-1]

    z = (current - mean) / std if std > 0 else 0.0
    if z < -1.5:
        return "buy"
    if z > 1.5:
        return "sell"

    # fallback: trend على 10 شموع
    trend = (prices[-1] - prices[-10]) / prices[-10] * 100
    return "buy" if trend > 0.3 else ("sell" if trend < -0.3 else "neutral")


def calc_atr(highs: list, lows: list, closes: list,
             period: int = ATR_PERIOD) -> float:
    """
    ATR مطابق لـ TechnicalAnalyzer.atr() في trading_bot.py.
    متوسط بسيط للـ True Range على آخر `period` شموع.
    تستقبل slices تنتهي عند الشمعة الحالية فقط.
    """
    if len(closes) < 2:
        return 0.0

    trs = []
    for k in range(1, len(closes)):
        tr = max(
            highs[k]  - lows[k],
            abs(highs[k]  - closes[k - 1]),
            abs(lows[k]   - closes[k - 1]),
        )
        trs.append(tr)

    if not trs:
        return 0.0
    window = trs[-period:] if len(trs) >= period else trs
    return round(sum(window) / len(window), 4)


# ══════════════════════════════════════════════════════════════════════════════
#  تقييم نتيجة الصفقة
# ══════════════════════════════════════════════════════════════════════════════

def resolve_trade(candles: list, entry_idx: int,
                  entry: float, sl: float,
                  tp1: float, tp2: float, tp3: float,
                  direction: str) -> dict:
    """
    يمشي للأمام شمعة بشمعة من entry_idx ويُحدد أول نتيجة تتحقق.

    entry_idx: رقم الشمعة التي تمّ فيها الدخول (= i+1 في الحلقة الرئيسية).
               يُتحقق منها مباشرة لأن السعر يتحرك بعد الافتتاح.

    قاعدة التعارض (TP+SL في نفس الشمعة): SL يُحسب أولاً — الأكثر تحفظاً.

    يعيد: {"outcome", "candles_to_result", "exit_dt"}
    """
    is_buy = direction == "buy"

    for j in range(entry_idx, len(candles)):
        h = candles[j]["high"]
        l = candles[j]["low"]

        if is_buy:
            # SL أسفل entry, TPs أعلاه
            hit_sl  = l <= sl
            hit_tp1 = h >= tp1
            hit_tp2 = h >= tp2   # tp2 > tp1 → hit_tp2 ⊂ hit_tp1 (ضمناً)
            hit_tp3 = h >= tp3   # tp3 > tp2 → hit_tp3 ⊂ hit_tp2 (ضمناً)
        else:
            # SELL: SL أعلى entry, TPs أدناه
            # tp1 > tp2 > tp3 (كلها أسفل entry، tp3 الأبعد)
            hit_sl  = h >= sl
            hit_tp1 = l <= tp1
            hit_tp2 = l <= tp2   # tp2 < tp1 → hit_tp2 ⊂ hit_tp1 (ضمناً)
            hit_tp3 = l <= tp3   # tp3 < tp2 → hit_tp3 ⊂ hit_tp2 (ضمناً)

        # ── تعارض TP + SL في نفس الشمعة → SL أولاً (محافظ) ──────────────
        if hit_sl and (hit_tp1 or hit_tp2 or hit_tp3):
            return {"outcome": "SL",
                    "candles_to_result": j - entry_idx + 1,
                    "exit_dt": candles[j]["dt"]}

        if hit_sl:
            return {"outcome": "SL",
                    "candles_to_result": j - entry_idx + 1,
                    "exit_dt": candles[j]["dt"]}

        # ── أعلى هدف تحقّق (hit_tp3 ⊂ hit_tp2 ⊂ hit_tp1 دائماً) ──────────
        if hit_tp3:
            outcome = "TP3"
        elif hit_tp2:
            outcome = "TP2"
        elif hit_tp1:
            outcome = "TP1"
        else:
            continue   # لا شيء تحقق بعد — تابع

        return {"outcome": outcome,
                "candles_to_result": j - entry_idx + 1,
                "exit_dt": candles[j]["dt"]}

    # وصلنا لنهاية البيانات قبل أي نتيجة
    return {"outcome": "UNRESOLVED",
            "candles_to_result": len(candles) - entry_idx,
            "exit_dt": None}


# ══════════════════════════════════════════════════════════════════════════════
#  الحلقة الرئيسية — Walk-Forward
# ══════════════════════════════════════════════════════════════════════════════

def run_backtest(candles: list, quarter_months: int = 3) -> list:
    """
    يمشي على الشموع بالترتيب الزمني التصاعدي.
    عند كل شمعة i، لا يرى إلا candles[0:i+1].
    يعيد قائمة الإشارات مع نتائجها.
    """
    n = len(candles)

    # استخراج مصفوفات scalar (أسرع من dict lookup في الحلقة الداخلية)
    all_opens  = [c["open"]  for c in candles]
    all_highs  = [c["high"]  for c in candles]
    all_lows   = [c["low"]   for c in candles]
    all_closes = [c["close"] for c in candles]

    signals          = []
    next_signal_bar  = WARMUP_BARS   # لا إشارة قبل انتهاء الإحماء

    # n-1: نحتاج شمعة i+1 للدخول، لذا نتوقف عند n-2
    for i in range(WARMUP_BARS, n - 1):

        # ── Cooldown: تخطّ ما لم يمضِ وقت كافٍ ──────────────────────────
        if i < next_signal_bar:
            continue

        # ── النافذة المرئية: candles[0:i+1] فقط ─────────────────────────
        # Slice صارم — أي بيانات بعد i غير موجودة في هذه المتغيرات
        prices_w = all_closes[: i + 1]
        highs_w  = all_highs [:  i + 1]
        lows_w   = all_lows  [:  i + 1]

        # ── توليد الإشارة ────────────────────────────────────────────────
        signal = model_1_statistical(prices_w)
        if signal == "neutral":
            continue

        # ── ATR من نفس النافذة [0:i+1] ──────────────────────────────────
        atr = calc_atr(highs_w, lows_w, prices_w)
        if atr == 0:
            continue   # سعر ثابت — تجاهل

        # ── Entry: افتتاح i+1 + انزلاق (Execution Fill Fix) ─────────────
        # opens[i+1] معروف بعد القرار، يُمثّل أول سعر ممكن للتنفيذ
        entry_idx  = i + 1
        raw_open   = all_opens[entry_idx]

        if signal == "buy":
            entry = round(raw_open * BUY_SLIP,  4)
            tp1   = round(entry + atr * TP1_MULT, 4)
            tp2   = round(entry + atr * TP2_MULT, 4)
            tp3   = round(entry + atr * TP3_MULT, 4)
            sl    = round(entry - atr * SL_MULT,  4)
        else:   # sell
            entry = round(raw_open * SELL_SLIP, 4)
            tp1   = round(entry - atr * TP1_MULT, 4)
            tp2   = round(entry - atr * TP2_MULT, 4)
            tp3   = round(entry - atr * TP3_MULT, 4)
            sl    = round(entry + atr * SL_MULT,  4)

        # ── تقييم النتيجة (يبدأ من i+1 — الشمعة ذاتها التي تمّ فيها الدخول)
        result = resolve_trade(
            candles=candles, entry_idx=entry_idx,
            entry=entry, sl=sl,
            tp1=tp1, tp2=tp2, tp3=tp3,
            direction=signal,
        )

        # تصنيف الفترة الزمنية
        sig_dt = candles[i]["dt"]
        q_num  = (sig_dt.month - 1) // quarter_months + 1
        quarter = f"{sig_dt.year}-Q{q_num}"

        signals.append({
            "signal_dt":         sig_dt,
            "entry_dt":          candles[entry_idx]["dt"],
            "direction":         signal,
            "entry":             entry,
            "tp1": tp1, "tp2": tp2, "tp3": tp3, "sl": sl,
            "atr":               atr,
            "quarter":           quarter,
            "outcome":           result["outcome"],
            "candles_to_result": result["candles_to_result"],
            "exit_dt":           result["exit_dt"],
        })

        # ── Cooldown: لا إشارة جديدة للـ 6 شموع التالية ─────────────────
        next_signal_bar = i + COOLDOWN_BARS

    return signals


# ══════════════════════════════════════════════════════════════════════════════
#  التقرير
# ══════════════════════════════════════════════════════════════════════════════

def print_report(signals: list, min_resolved: int = 30) -> None:
    """يطبع التقرير الكامل على stdout."""

    resolved   = [s for s in signals if s["outcome"] != "UNRESOLVED"]
    unresolved = [s for s in signals if s["outcome"] == "UNRESOLVED"]
    n_res      = len(resolved)
    n_sig      = len(signals)

    SEP = "═" * 66

    print()
    print(SEP)
    print("   Backtest Report — model_1_statistical  |  XAUUSD M5")
    print(SEP)

    # ── إجمالي الإشارات ───────────────────────────────────────────────────
    buys  = sum(1 for s in signals if s["direction"] == "buy")
    sells = sum(1 for s in signals if s["direction"] == "sell")

    print(f"\n  إجمالي الإشارات       : {n_sig:>5}  (buy: {buys}, sell: {sells})")
    print(f"  محسومة (TP أو SL)     : {n_res:>5}")
    print(f"  غير محسومة (مستبعدة)  : {len(unresolved):>5}")

    # ── تحذير إحصائي فوري ────────────────────────────────────────────────
    if n_res < min_resolved:
        print()
        print(f"  ⚠️  تحذير إحصائي: {n_res} صفقة محسومة فقط (الحد الأدنى الموصى: {min_resolved})")
        print(f"      النتائج أدناه غير موثوقة إحصائياً — جلب بيانات أكثر")
        print(f"      أو مراجعة عتبات النموذج إن كانت الإشارات نادرة جداً.")

    if n_res == 0:
        print(f"\n  لا توجد صفقات محسومة — لا يمكن حساب تقرير.")
        print(SEP)
        return

    # ── نسب النتائج ──────────────────────────────────────────────────────
    counts   = {"TP1": 0, "TP2": 0, "TP3": 0, "SL": 0}
    for s in resolved:
        counts[s["outcome"]] += 1

    winners  = counts["TP1"] + counts["TP2"] + counts["TP3"]
    win_rate = winners / n_res * 100

    print(f"\n  ── نسب النتائج (من {n_res} صفقة محسومة) ──")
    bar_scale = 40 / 100   # عرض شريط البيانات
    for label in ["TP1", "TP2", "TP3", "SL"]:
        pct = counts[label] / n_res * 100
        bar = "█" * round(pct * bar_scale)
        print(f"    {label}  {counts[label]:>4} ({pct:5.1f}%)  {bar}")

    rr_achieved = (counts["TP2"] * TP2_MULT + counts["TP3"] * TP3_MULT) / max(n_res, 1)

    print(f"\n    نسبة الربح الإجمالية   : {win_rate:>5.1f}%  ({winners}/{n_res})")
    print(f"    نسبة الخسارة            : {100 - win_rate:>5.1f}%  ({counts['SL']}/{n_res})")
    print(f"    نسبة TP1 فقط            : {counts['TP1']/n_res*100:>5.1f}%")
    print(f"    نسبة TP2+TP3            : {(counts['TP2']+counts['TP3'])/n_res*100:>5.1f}%")

    # ── توقيت الصفقات ────────────────────────────────────────────────────
    durs = [s["candles_to_result"] for s in resolved]
    avg_dur = sum(durs) / len(durs)
    min_dur = min(durs)
    max_dur = max(durs)
    min_s = next(s for s in resolved if s["candles_to_result"] == min_dur)
    max_s = next(s for s in resolved if s["candles_to_result"] == max_dur)

    print(f"\n  ── توقيت الصفقات ──")
    print(f"    متوسط الشموع للنتيجة   : {avg_dur:>6.1f}  (~{avg_dur * 5:.0f} دقيقة)")
    print(f"    أقصر صفقة              : {min_dur:>4} شمعة (~{min_dur*5} دق)"
          f"  [{min_s['signal_dt'].strftime('%Y-%m-%d')} | {min_s['outcome']}]")
    print(f"    أطول صفقة              : {max_dur:>4} شمعة (~{max_dur*5} دق)"
          f"  [{max_s['signal_dt'].strftime('%Y-%m-%d')} | {max_s['outcome']}]")

    # ── الأداء حسب الفترات الزمنية ───────────────────────────────────────
    print(f"\n  ── الأداء حسب الفترات الزمنية ──")

    # جمع الإشارات لكل فترة (محسومة + غير محسومة)
    q_data: dict = {}
    for s in signals:
        q = s["quarter"]
        if q not in q_data:
            q_data[q] = {"TP1": 0, "TP2": 0, "TP3": 0, "SL": 0,
                         "unresolved": 0, "total_res": 0}
        if s["outcome"] == "UNRESOLVED":
            q_data[q]["unresolved"] += 1
        else:
            q_data[q][s["outcome"]] += 1
            q_data[q]["total_res"] += 1

    hdr = f"    {'الفترة':<12} {'محسوم':>7} {'TP1':>4} {'TP2':>4} {'TP3':>4} {'SL':>4} {'غ.محسوم':>8} {'ربح%':>8}"
    print(hdr)
    print("    " + "-" * (len(hdr) - 4))

    quarter_win_rates = []
    for q in sorted(q_data.keys()):
        d  = q_data[q]
        t  = d["total_res"]
        w  = d["TP1"] + d["TP2"] + d["TP3"]
        wr_str = "—" if t == 0 else f"{w/t*100:.1f}%"
        flag   = " ⚠️" if t < 5 and t > 0 else ""
        print(f"    {q:<12} {t:>7} {d['TP1']:>4} {d['TP2']:>4} {d['TP3']:>4} "
              f"{d['SL']:>4} {d['unresolved']:>8} {wr_str + flag:>8}")
        if t >= 3:
            quarter_win_rates.append(w / t)

    # ── تحذير تركّز الأداء ───────────────────────────────────────────────
    if len(quarter_win_rates) >= 2:
        spread = max(quarter_win_rates) - min(quarter_win_rates)
        print()
        if spread > 0.30:
            print(f"  ⚠️  تحذير: تشتّت الأداء عبر الفترات = {spread*100:.0f}%  (> 30%)")
            print(f"      الأداء غير ثابت — قد تكون النتيجة الإجمالية")
            print(f"      نتاج فترة سوقية واحدة لا استراتيجية متسقة.")
        elif spread > 0.15:
            print(f"  ⚠️  ملاحظة: تشتّت الأداء = {spread*100:.0f}% (متوسط) — راقب الاتساق.")
        else:
            print(f"  ✅  الأداء ثابت نسبياً عبر الفترات (تشتّت = {spread*100:.0f}%).")

    print()
    print(SEP)
    print()


# ══════════════════════════════════════════════════════════════════════════════
#  نقطة الدخول
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Backtest لـ model_1_statistical على XAUUSD M5"
    )
    parser.add_argument("--input", default="backtest_data/xauusd_m5.csv",
                        help="مسار CSV (من fetch_historical.py)")
    parser.add_argument("--quarter-months", type=int, default=3,
                        help="أشهر لكل فترة في التقرير (افتراضي: 3 = ربع سنوي)")
    parser.add_argument("--min-resolved", type=int, default=30,
                        help="حد الإنذار لعدد الصفقات المحسومة (افتراضي: 30)")
    args = parser.parse_args()

    print(f"\n[تحميل] {args.input} ...", end=" ", flush=True)
    candles = load_csv(args.input)
    if len(candles) < WARMUP_BARS + 2:
        sys.exit(f"[خطأ] بيانات غير كافية ({len(candles)} شمعة).")
    print(f"{len(candles):,} شمعة  |  "
          f"{candles[0]['dt'].date()} → {candles[-1]['dt'].date()}")

    print(f"[تشغيل] walk-forward loop ...", end=" ", flush=True)
    signals = run_backtest(candles, quarter_months=args.quarter_months)
    print(f"اكتمل — {len(signals)} إشارة مُوَلَّدة")

    print_report(signals, min_resolved=args.min_resolved)


if __name__ == "__main__":
    main()
