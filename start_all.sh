#!/data/data/com.termux/files/usr/bin/bash
# ═══════════════════════════════════════
#  UMP Trading Bots - تشغيل البوتات الثلاثة
# ═══════════════════════════════════════
cd ~/UMP

# ── تحميل المتغيرات من .env ──────────────
if [ ! -f .env ]; then
  echo "❌ ملف .env غير موجود! أنشئه أولاً: nano ~/UMP/.env"
  exit 1
fi
set -a
source .env
set +a

# ── إنشاء مجلد السجلات ───────────────────
mkdir -p logs

# ── إيقاف أي نسخة قديمة شغّالة ──────────
pkill -f trading_bot.py 2>/dev/null
sleep 1

# ── تشغيل البوتات الثلاثة ────────────────
echo "🚀 تشغيل بوت الذهب XAUUSD..."
TRADING_PAIR=XAUUSD nohup python trading_bot.py > logs/xauusd.log 2>&1 &
echo "  PID: $!"

sleep 2

echo "🚀 تشغيل بوت البيتكوين BTCUSD..."
TRADING_PAIR=BTCUSD nohup python trading_bot.py > logs/btcusd.log 2>&1 &
echo "  PID: $!"

sleep 2

echo "🚀 تشغيل بوت اليورو EURUSD..."
TRADING_PAIR=EURUSD nohup python trading_bot.py > logs/eurusd.log 2>&1 &
echo "  PID: $!"

echo ""
echo "✅ البوتات الثلاثة تعمل في الخلفية"
echo ""
echo "📋 لمراقبة السجلات:"
echo "  tail -f ~/UMP/logs/xauusd.log"
echo "  tail -f ~/UMP/logs/btcusd.log"
echo "  tail -f ~/UMP/logs/eurusd.log"
echo ""
echo "🔴 لإيقاف الكل: pkill -f trading_bot.py"
