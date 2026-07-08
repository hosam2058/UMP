import os
import json
import zipfile
import requests
from datetime import datetime
from flask import Flask, render_template_string, jsonify, send_file, abort, Response
from threading import Thread
import time
import io

app = Flask(__name__)

WHATSAPP_LINK = "https://wa.me/201500236188"
SIGNAL_FILE   = "data/latest_signal.json"
STATS_FILE    = "data/website_stats.json"
FREE_SIGNALS  = 3

_cached_price = {
    "price": None, "prev": None, "change": 0.0,
    "pct": 0.0, "updated": "", "high": None, "low": None
}
_price_history = []

def _parse_yahoo(r):
    d = r.json()
    return float(d["chart"]["result"][0]["meta"]["regularMarketPrice"])

def _parse_stooq(r):
    # stooq returns CSV: Date,Time,Open,High,Low,Close,Volume
    lines = r.text.strip().splitlines()
    if len(lines) < 2:
        raise ValueError("no data")
    return float(lines[1].split(",")[5])

def _fetch_gold_price():
    sources = [
        ("https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=1m&range=1d",
         _parse_yahoo),
        ("https://query2.finance.yahoo.com/v8/finance/chart/GC=F?interval=1m&range=1d",
         _parse_yahoo),
        ("https://stooq.com/q/d/l/?s=xauusd&i=d",
         _parse_stooq),
    ]
    while True:
        fetched = False
        for url, parser in sources:
            try:
                r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}, timeout=8)
                if r.status_code == 200:
                    price = parser(r)
                    if price and price > 100:
                        old = _cached_price["price"] or price
                        chg = round(price - old, 2)
                        pct = round((chg / old) * 100, 3) if old else 0.0
                        _cached_price.update({
                            "price": round(price, 2), "prev": old,
                            "change": chg, "pct": pct,
                            "updated": datetime.now().strftime("%H:%M:%S"),
                        })
                        if _cached_price["high"] is None or price > _cached_price["high"]:
                            _cached_price["high"] = round(price, 2)
                        if _cached_price["low"] is None or price < _cached_price["low"]:
                            _cached_price["low"] = round(price, 2)
                        _price_history.append({"t": int(time.time()), "p": round(price, 2)})
                        if len(_price_history) > 288:
                            _price_history.pop(0)
                        fetched = True
                        break
            except Exception:
                pass
        time.sleep(8)

Thread(target=_fetch_gold_price, daemon=True).start()

COURSES = [
    {"icon": "📚", "title": "التحليل الكلاسيكي",    "count": 29},
    {"icon": "🎯", "title": "كورسات SMC",            "count": 22},
    {"icon": "💡", "title": "كورسات ICT",            "count": 20},
    {"icon": "🌊", "title": "موجات إليوت",           "count": 7},
    {"icon": "🔑", "title": "SK سيستم",              "count": 9},
    {"icon": "📊", "title": "التحليل الحجمي",        "count": 11},
    {"icon": "🔮", "title": "الهارمونيك",            "count": 5},
    {"icon": "₿",  "title": "كورسات الكريبتو",      "count": 10},
    {"icon": "⚔️", "title": "استراتيجيات متنوعة",   "count": 38},
    {"icon": "👑", "title": "استراتيجيات القبطان",   "count": 3},
    {"icon": "⚡", "title": "الخيارات الثنائية",     "count": 18},
    {"icon": "🧠", "title": "علم النفس التداولي",    "count": 2},
]

BOT_FILES = [
    {"name": ".env",          "desc": "🔑 جميع المفاتيح — Gemini (15 مفتاح)، التوكنات، Gold API"},
    {"name": "trading_bot.py","desc": "بوت التداول الذكي — إشارات XAUUSD، 12 مصدر تأكيد، AI"},
    {"name": "bot.py",        "desc": "البوت العربي — ذكاء اصطناعي، تحميل فيديو، تحويل صوت"},
    {"name": "dashboard.py",  "desc": "لوحة التحكم الإدارية (port 3000)"},
    {"name": "website.py",    "desc": "موقع الهبوط الاحترافي (port 5000)"},
    {"name": "auto_trader.py","desc": "التداول الآلي — MetaApi MT5"},
    {"name": "config.py",     "desc": "ملف الإعدادات المشتركة"},
    {"name": "requirements.txt","desc": "جميع المكتبات المطلوبة"},
]

# ─────────────────────────────────────────────
#  API ROUTES
# ─────────────────────────────────────────────
@app.route("/api/price")
def api_price():
    return jsonify(_cached_price)

@app.route("/api/history")
def api_history():
    return jsonify(_price_history[-60:])

@app.route("/api/signal")
def api_signal():
    try:
        with open(SIGNAL_FILE, encoding="utf-8") as f:
            return jsonify(json.load(f))
    except Exception:
        return jsonify({})

@app.route("/api/stats")
def api_stats():
    try:
        with open(STATS_FILE, encoding="utf-8") as f:
            return jsonify(json.load(f))
    except Exception:
        return jsonify({"users": 0, "signals": 0})

@app.route("/download/<filename>")
def download_file(filename):
    allowed = [f["name"] for f in BOT_FILES]
    if filename not in allowed:
        abort(404)
    path = os.path.join(os.getcwd(), filename)
    if not os.path.exists(path):
        abort(404)
    return send_file(path, as_attachment=True, download_name=filename)

@app.route("/download-zip")
def download_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in BOT_FILES:
            p = os.path.join(os.getcwd(), f["name"])
            if os.path.exists(p):
                zf.write(p, f["name"])
    buf.seek(0)
    return send_file(buf, as_attachment=True,
                     download_name="trading_bot_system.zip",
                     mimetype="application/zip")

@app.route("/files")
def files_page():
    rows = ""
    for f in BOT_FILES:
        path = os.path.join(os.getcwd(), f["name"])
        size = f"{os.path.getsize(path)/1024:.1f} KB" if os.path.exists(path) else "—"
        rows += f"""<tr>
<td class="fn">{f['name']}</td>
<td class="fd">{f['desc']}</td>
<td class="fs">{size}</td>
<td><a href="/download/{f['name']}" class="btn-dl">⬇ تحميل</a></td>
</tr>"""
    return render_template_string(FILES_HTML, rows=rows)

# ─────────────────────────────────────────────
#  MAIN PAGE
# ─────────────────────────────────────────────
@app.route("/")
def index():
    courses_html = ""
    for c in COURSES:
        courses_html += f"""
<div class="course-card">
  <div class="cc-icon">{c['icon']}</div>
  <div class="cc-title">{c['title']}</div>
  <div class="cc-meta">{c['count']} كورس</div>
  <a href="{WHATSAPP_LINK}" class="cc-btn" target="_blank">تواصل معنا</a>
</div>"""
    return render_template_string(MAIN_HTML,
                                  whatsapp=WHATSAPP_LINK,
                                  courses_html=courses_html,
                                  free_signals=FREE_SIGNALS)

# ─────────────────────────────────────────────
#  FILES PAGE HTML
# ─────────────────────────────────────────────
FILES_HTML = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ملفات النظام | بوت التداول الذكي</title>
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700&display=swap" rel="stylesheet">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#070710;color:#e2e8f0;font-family:Cairo,sans-serif;padding:2rem}
h1{color:#f5c518;text-align:center;margin-bottom:.5rem;font-size:1.8rem}
.sub{text-align:center;color:#8892a4;margin-bottom:2rem}
.zip-btn{display:block;width:fit-content;margin:0 auto 2rem;background:#f5c518;color:#000;padding:.8rem 2rem;border-radius:12px;font-weight:700;text-decoration:none;font-size:1.1rem}
table{width:100%;border-collapse:collapse;background:#12121e;border-radius:16px;overflow:hidden}
th{background:#1a1a2e;padding:1rem;color:#f5c518;font-size:.9rem}
td{padding:.9rem 1rem;border-top:1px solid rgba(245,197,24,.1);font-size:.9rem}
.fn{color:#f5c518;font-family:monospace;font-weight:600}
.fs{color:#8892a4;font-size:.8rem}
.fd{color:#a0aec0}
.btn-dl{background:rgba(245,197,24,.15);color:#f5c518;border:1px solid rgba(245,197,24,.3);padding:.4rem 1rem;border-radius:8px;text-decoration:none;font-size:.85rem;white-space:nowrap}
.btn-dl:hover{background:rgba(245,197,24,.3)}
.back{display:inline-block;margin-top:1.5rem;color:#f5c518;text-decoration:none}
</style></head>
<body>
<h1>📁 ملفات نظام التداول</h1>
<p class="sub">جميع أكواد البوت جاهزة للتشغيل على Termux أو أي خادم Linux</p>
<a href="/download-zip" class="zip-btn">⬇ تحميل جميع الملفات (ZIP)</a>
<table>
<thead><tr><th>الملف</th><th>الوصف</th><th>الحجم</th><th>تحميل</th></tr></thead>
<tbody>{{ rows }}</tbody>
</table>
<a href="/" class="back">← العودة للموقع</a>
</body></html>"""

# ─────────────────────────────────────────────
#  MAIN HTML - Complete Professional Redesign
# ─────────────────────────────────────────────
MAIN_HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>بوت التداول الذكي | إشارات XAUUSD لحظية مع ذكاء اصطناعي</title>
<meta name="description" content="نظام إشارات ذهب XAUUSD احترافي بـ12 مصدر تأكيد وذكاء اصطناعي Gemini. RSI، MACD، Bollinger، Fibonacci. خطط من 10$ شهرياً.">
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@300;400;600;700;900&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
/* ══ RESET & VARS ══ */
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --gold:#f5c518;--gold2:#c99a00;--gold3:rgba(245,197,24,.12);--gold4:rgba(245,197,24,.06);
  --bg:#07070f;--bg2:#0c0c1a;--bg3:#0f0f1e;
  --card:#111120;--card2:#161628;
  --border:rgba(245,197,24,.14);--border2:rgba(245,197,24,.28);
  --green:#22c55e;--red:#ef4444;--blue:#60a5fa;--purple:#a78bfa;
  --text:#e2e8f0;--muted:#8892a4;--muted2:#5a6478;
  --radius:18px;--radius2:12px;
  --shadow:0 8px 40px rgba(0,0,0,.7);
  --glow:0 0 30px rgba(245,197,24,.15);
}
html{scroll-behavior:smooth}
body{background:var(--bg);color:var(--text);font-family:Cairo,sans-serif;overflow-x:hidden;line-height:1.6}
a{text-decoration:none;color:inherit}
::-webkit-scrollbar{width:5px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--gold2);border-radius:3px}

/* ══ NAVBAR ══ */
.navbar{
  position:fixed;top:0;right:0;left:0;z-index:1000;
  background:rgba(7,7,15,.95);backdrop-filter:blur(24px);
  border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between;
  padding:.85rem 2rem;
}
.nav-logo{display:flex;align-items:center;gap:.7rem;font-size:1.1rem;font-weight:900;color:var(--gold)}
.nav-logo-icon{width:36px;height:36px;background:var(--gold);border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:1.1rem;color:#000;font-weight:900;flex-shrink:0}
.nav-links{display:flex;align-items:center;gap:1.8rem}
.nav-links a{color:var(--muted);font-size:.87rem;transition:color .2s;font-weight:600}
.nav-links a:hover{color:var(--gold)}
.nav-right{display:flex;align-items:center;gap:.8rem}
.nav-price{
  background:var(--gold3);border:1px solid var(--border);
  border-radius:8px;padding:.35rem .9rem;font-size:.87rem;font-weight:700;
  color:var(--gold);cursor:default;display:flex;align-items:center;gap:.4rem
}
.nav-live-dot{width:7px;height:7px;border-radius:50%;background:var(--green);animation:pulse 1.5s infinite}
.nav-cta{
  background:var(--gold);color:#000;padding:.45rem 1.3rem;
  border-radius:8px;font-weight:700;font-size:.87rem;transition:all .2s;white-space:nowrap
}
.nav-cta:hover{background:#fff;transform:translateY(-1px)}
@media(max-width:768px){.nav-links{display:none}.nav-price{display:none}}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}

/* ══ HERO ══ */
.hero{
  min-height:100vh;display:flex;align-items:center;justify-content:center;
  padding:8rem 2rem 5rem;position:relative;overflow:hidden;
}
.hero-bg{
  position:absolute;inset:0;
  background:
    radial-gradient(ellipse at 30% 0%, rgba(245,197,24,.07) 0%, transparent 55%),
    radial-gradient(ellipse at 70% 80%, rgba(96,165,250,.04) 0%, transparent 45%);
  pointer-events:none;
}
.hero-grid{display:grid;grid-template-columns:1fr 1fr;gap:4rem;align-items:center;max-width:1200px;width:100%;position:relative}
@media(max-width:900px){.hero-grid{grid-template-columns:1fr;text-align:center}}
.badge-live{
  display:inline-flex;align-items:center;gap:.5rem;
  background:var(--gold3);border:1px solid var(--border2);
  border-radius:50px;padding:.38rem 1rem;font-size:.78rem;color:var(--gold);
  font-weight:700;margin-bottom:1.4rem
}
.hero-title{font-size:clamp(1.9rem,4.5vw,3rem);font-weight:900;line-height:1.22;margin-bottom:1.2rem}
.hero-title .hl{color:var(--gold)}
.hero-title .hl2{color:var(--blue)}
.hero-sub{font-size:1rem;color:var(--muted);margin-bottom:2rem;max-width:470px;line-height:1.75}
@media(max-width:900px){.hero-sub{margin:0 auto 2rem}}
.hero-btns{display:flex;gap:.9rem;flex-wrap:wrap}
@media(max-width:900px){.hero-btns{justify-content:center}}
.btn-primary{
  background:var(--gold);color:#000;padding:.85rem 1.9rem;
  border-radius:var(--radius2);font-weight:700;font-size:.95rem;
  display:inline-flex;align-items:center;gap:.5rem;transition:all .25s;
  box-shadow:0 4px 24px rgba(245,197,24,.35)
}
.btn-primary:hover{background:#fff;transform:translateY(-2px);box-shadow:0 8px 32px rgba(245,197,24,.4)}
.btn-outline{
  background:transparent;color:var(--gold);padding:.85rem 1.9rem;
  border:2px solid var(--border2);border-radius:var(--radius2);
  font-weight:700;font-size:.95rem;display:inline-flex;align-items:center;gap:.5rem;transition:all .25s
}
.btn-outline:hover{background:var(--gold3);border-color:var(--gold);transform:translateY(-2px)}
.hero-stats{display:flex;gap:2.5rem;margin-top:2.5rem;flex-wrap:wrap}
@media(max-width:900px){.hero-stats{justify-content:center}}
.hstat{text-align:center}
.hstat-num{font-size:2rem;font-weight:900;color:var(--gold);line-height:1}
.hstat-lbl{font-size:.72rem;color:var(--muted);margin-top:.2rem}

/* ══ LIVE PRICE CARD ══ */
.price-card{
  background:var(--card);border:1px solid var(--border2);border-radius:var(--radius);
  padding:1.8rem;box-shadow:var(--shadow),var(--glow);position:relative;overflow:hidden
}
.price-card::before{
  content:"";position:absolute;inset:0;
  background:radial-gradient(circle at top right, rgba(245,197,24,.07), transparent 55%);
  pointer-events:none
}
.pc-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:1.2rem}
.pc-pair{font-size:1rem;font-weight:700;color:var(--gold);display:flex;align-items:center;gap:.4rem}
.pc-badge{font-size:.72rem;background:rgba(34,197,94,.15);color:var(--green);border:1px solid rgba(34,197,94,.3);border-radius:50px;padding:.2rem .6rem}
.pc-price{font-size:2.8rem;font-weight:900;color:var(--gold);font-variant-numeric:tabular-nums;line-height:1;text-align:center;margin:.5rem 0}
.pc-change{text-align:center;font-size:.9rem;font-weight:700;margin-bottom:1rem}
.pc-change.up{color:var(--green)}.pc-change.dn{color:var(--red)}
.pc-meta{display:flex;justify-content:space-around;padding:.8rem 0;border-top:1px solid var(--border);border-bottom:1px solid var(--border);margin-bottom:1rem}
.pcm-item{text-align:center}
.pcm-val{font-size:.92rem;font-weight:700}
.pcm-lbl{font-size:.68rem;color:var(--muted);margin-top:.15rem}
.pc-chart-wrap{height:90px;position:relative}
.pc-indicators{display:grid;grid-template-columns:repeat(3,1fr);gap:.45rem;margin-top:.9rem}
.pci{background:var(--bg2);border-radius:8px;padding:.55rem;text-align:center}
.pci .n{font-size:.68rem;color:var(--muted);margin-bottom:.2rem}
.pci .v{font-size:.82rem;font-weight:700}
.pci.buy .v{color:var(--green)}.pci.sell .v{color:var(--red)}.pci.neu .v{color:var(--muted)}
.pc-updated{text-align:center;font-size:.7rem;color:var(--muted2);margin-top:.7rem}
.session-info{
  display:flex;align-items:center;justify-content:center;gap:.5rem;
  background:var(--bg2);border-radius:8px;padding:.5rem;margin-top:.8rem;font-size:.8rem
}
.session-dot{width:8px;height:8px;border-radius:50%;background:var(--green);animation:pulse 1.5s infinite}

/* ══ TICKER ══ */
.ticker{
  background:rgba(245,197,24,.07);border-top:1px solid var(--border);border-bottom:1px solid var(--border);
  padding:.55rem 0;overflow:hidden;white-space:nowrap
}
.ticker-inner{display:inline-flex;gap:4rem;animation:scroll 35s linear infinite}
@keyframes scroll{0%{transform:translateX(0)}100%{transform:translateX(-50%)}}
.ticker-item{display:inline-flex;align-items:center;gap:.5rem;font-size:.82rem;font-weight:600}
.ticker-item .t{color:var(--muted)}
.ticker-dot{width:6px;height:6px;border-radius:50%;background:var(--gold);opacity:.6}

/* ══ SECTIONS ══ */
section{padding:5rem 2rem}
.container{max-width:1200px;margin:0 auto}
.sec-badge{display:inline-block;background:var(--gold3);border:1px solid var(--border);border-radius:50px;padding:.3rem .95rem;font-size:.76rem;color:var(--gold);font-weight:700;margin-bottom:.9rem}
.sec-title{font-size:clamp(1.6rem,3.5vw,2.3rem);font-weight:900;margin-bottom:.8rem}
.sec-title .hl{color:var(--gold)}
.sec-sub{font-size:.95rem;color:var(--muted);max-width:580px;line-height:1.75}
.sec-header{margin-bottom:3rem}
.sec-header.center{text-align:center}.sec-header.center .sec-sub{margin:0 auto}

/* ══ STATS BAR ══ */
.stats-bar{background:var(--card);border-top:1px solid var(--border);border-bottom:1px solid var(--border);padding:2rem}
.stats-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:1.5rem}
@media(max-width:700px){.stats-grid{grid-template-columns:repeat(2,1fr)}}
.stat-item{text-align:center}
.stat-num{font-size:2.1rem;font-weight:900;color:var(--gold);line-height:1}
.stat-lbl{font-size:.78rem;color:var(--muted);margin-top:.3rem}

/* ══ SIGNAL SECTION ══ */
.signal-section{background:var(--bg2)}
.signal-grid{display:grid;grid-template-columns:1fr 1fr;gap:2rem;align-items:start}
@media(max-width:900px){.signal-grid{grid-template-columns:1fr}}
.signal-card{background:var(--card);border:1px solid var(--border2);border-radius:var(--radius);padding:1.8rem;position:relative;overflow:hidden}
.signal-card::before{content:"";position:absolute;inset:0;background:radial-gradient(circle at top left, rgba(245,197,24,.05), transparent 55%);pointer-events:none}
.sig-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:1.4rem}
.sig-pair{font-size:1.05rem;font-weight:700;color:var(--gold)}
.sig-dir{padding:.3rem .85rem;border-radius:7px;font-weight:700;font-size:.83rem}
.sig-dir.BUY{background:rgba(34,197,94,.15);color:var(--green);border:1px solid rgba(34,197,94,.3)}
.sig-dir.SELL{background:rgba(239,68,68,.15);color:var(--red);border:1px solid rgba(239,68,68,.3)}
.sig-row{display:flex;justify-content:space-between;align-items:center;padding:.6rem 0;border-bottom:1px solid var(--border);font-size:.88rem}
.sig-row:last-child{border-bottom:none}
.sig-lbl{color:var(--muted)}
.sig-val{font-weight:700;font-family:monospace;font-size:.9rem}
.sig-val.blur{filter:blur(5px);user-select:none}
.sig-conf{display:flex;align-items:center;gap:.6rem;margin-top:1rem}
.conf-bar{flex:1;height:7px;background:var(--bg);border-radius:4px;overflow:hidden}
.conf-fill{height:100%;background:linear-gradient(90deg,var(--gold2),var(--gold));border-radius:4px;transition:width 1s}
.conf-pct{font-size:.83rem;font-weight:700;color:var(--gold);white-space:nowrap}
.sig-sources{display:grid;grid-template-columns:1fr 1fr;gap:.4rem;margin-top:.9rem}
.src-badge{background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:.32rem .65rem;font-size:.73rem;display:flex;align-items:center;gap:.4rem}
.src-badge.ok{border-color:rgba(34,197,94,.3);color:var(--green)}
.src-badge.ng{border-color:rgba(239,68,68,.2);color:var(--red)}
.src-badge.na{color:var(--muted)}
.trial-box{background:linear-gradient(135deg,rgba(245,197,24,.1),rgba(245,197,24,.03));border:2px dashed var(--border2);border-radius:var(--radius);padding:2rem;text-align:center}
.trial-num{font-size:4.5rem;font-weight:900;color:var(--gold);line-height:1}
.trial-label{font-size:.95rem;color:var(--muted);margin:.5rem 0 1.4rem}
.trial-features{list-style:none;text-align:right;margin-bottom:1.4rem}
.trial-features li{display:flex;align-items:center;gap:.5rem;padding:.38rem 0;font-size:.88rem;color:var(--muted)}
.trial-features li::before{content:"✅";flex-shrink:0}
.cta-free{background:var(--gold);color:#000;display:block;width:100%;padding:.95rem;border-radius:var(--radius2);font-weight:900;font-size:1rem;text-align:center;transition:all .2s;box-shadow:0 4px 20px rgba(245,197,24,.3)}
.cta-free:hover{background:#fff;transform:translateY(-2px)}
.no-signal{text-align:center;padding:2rem;color:var(--muted)}
.no-signal .ns-icon{font-size:3rem;margin-bottom:.8rem}

/* ══ FEATURES ══ */
.features-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:1.5rem}
@media(max-width:900px){.features-grid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:540px){.features-grid{grid-template-columns:1fr}}
.feat-card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:1.6rem;transition:all .25s;position:relative;overflow:hidden}
.feat-card::before{content:"";position:absolute;top:0;right:0;left:0;height:2px;background:linear-gradient(90deg,transparent,var(--gold3),transparent)}
.feat-card:hover{border-color:var(--border2);transform:translateY(-4px);box-shadow:0 12px 40px rgba(245,197,24,.1)}
.feat-icon{font-size:2.1rem;margin-bottom:.8rem}
.feat-title{font-size:.98rem;font-weight:700;color:var(--gold);margin-bottom:.4rem}
.feat-desc{font-size:.82rem;color:var(--muted);line-height:1.7}

/* ══ INDICATORS ══ */
.indicators-section{background:var(--bg2)}
.ind-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:.8rem}
@media(max-width:900px){.ind-grid{grid-template-columns:repeat(3,1fr)}}
@media(max-width:540px){.ind-grid{grid-template-columns:repeat(2,1fr)}}
.ind-chip{
  background:var(--card);border:1px solid var(--border);border-radius:10px;
  padding:.85rem;text-align:center;transition:all .2s;cursor:default
}
.ind-chip:hover{border-color:var(--border2);background:var(--gold3)}
.ind-chip .ic-icon{font-size:1.3rem;margin-bottom:.3rem}
.ind-chip .ic-name{font-size:.8rem;font-weight:700;color:var(--gold);margin-bottom:.2rem}
.ind-chip .ic-desc{font-size:.68rem;color:var(--muted)}

/* ══ PLANS ══ */
.plans-section{background:var(--bg3)}
.plans-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:1.5rem}
@media(max-width:900px){.plans-grid{grid-template-columns:1fr;max-width:420px;margin:0 auto}}
.plan-card{
  background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
  padding:2rem;position:relative;transition:all .3s;overflow:hidden
}
.plan-card.popular{border-color:var(--gold);box-shadow:0 0 40px rgba(245,197,24,.15)}
.plan-card:hover{transform:translateY(-6px);box-shadow:var(--shadow)}
.plan-popular-badge{
  position:absolute;top:1.2rem;left:1.2rem;
  background:var(--gold);color:#000;font-size:.7rem;font-weight:900;
  padding:.25rem .7rem;border-radius:50px
}
.plan-icon{font-size:2.5rem;margin-bottom:.8rem}
.plan-name{font-size:1.1rem;font-weight:900;margin-bottom:.3rem}
.plan-name.silver{color:#a8b0be}
.plan-name.gold{color:var(--gold)}
.plan-name.diamond{color:#60a5fa}
.plan-price{margin:1rem 0 1.4rem}
.plan-price .amount{font-size:2.8rem;font-weight:900;color:var(--gold);line-height:1}
.plan-price .period{font-size:.82rem;color:var(--muted)}
.plan-features{list-style:none;margin-bottom:1.5rem}
.plan-features li{display:flex;align-items:flex-start;gap:.5rem;padding:.38rem 0;font-size:.84rem;line-height:1.5}
.plan-features li .pf-icon{flex-shrink:0;margin-top:.1rem}
.plan-features li.has{color:var(--text)}
.plan-features li.no{color:var(--muted2)}
.plan-note{font-size:.75rem;color:var(--muted2);margin-bottom:1.2rem;padding:.5rem;background:rgba(255,255,255,.03);border-radius:6px;border:1px solid var(--border)}
.plan-btn{
  display:block;width:100%;text-align:center;padding:.9rem;border-radius:var(--radius2);
  font-weight:700;font-size:.92rem;transition:all .2s
}
.plan-btn.primary{background:var(--gold);color:#000;box-shadow:0 4px 20px rgba(245,197,24,.3)}
.plan-btn.primary:hover{background:#fff}
.plan-btn.outline{background:transparent;border:2px solid var(--border2);color:var(--gold)}
.plan-btn.outline:hover{background:var(--gold3);border-color:var(--gold)}
.plans-note{text-align:center;margin-top:2rem;font-size:.85rem;color:var(--muted);background:var(--gold3);border:1px solid var(--border);border-radius:10px;padding:.8rem 1.5rem;max-width:560px;margin-left:auto;margin-right:auto}

/* ══ COURSES ══ */
.courses-section{background:var(--bg2)}
.courses-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:1.2rem}
@media(max-width:900px){.courses-grid{grid-template-columns:repeat(3,1fr)}}
@media(max-width:600px){.courses-grid{grid-template-columns:repeat(2,1fr)}}
.course-card{
  background:var(--card);border:1px solid var(--border);border-radius:var(--radius2);
  padding:1.4rem;text-align:center;transition:all .25s;display:flex;flex-direction:column;align-items:center
}
.course-card:hover{border-color:var(--border2);transform:translateY(-3px);box-shadow:0 8px 32px rgba(245,197,24,.08)}
.cc-icon{font-size:2rem;margin-bottom:.6rem}
.cc-title{font-size:.88rem;font-weight:700;color:var(--text);margin-bottom:.3rem}
.cc-meta{font-size:.75rem;color:var(--muted);margin-bottom:1rem}
.cc-btn{
  display:block;width:100%;text-align:center;padding:.5rem;border-radius:8px;
  font-size:.8rem;font-weight:700;background:var(--gold3);border:1px solid var(--border2);
  color:var(--gold);transition:all .2s;margin-top:auto
}
.cc-btn:hover{background:var(--gold);color:#000}
.courses-cta{text-align:center;margin-top:2.5rem}

/* ══ AI CHART SECTION ══ */
.ai-section{background:var(--bg)}
.ai-card{
  background:linear-gradient(135deg,rgba(167,139,250,.08),rgba(245,197,24,.05));
  border:1px solid rgba(167,139,250,.25);border-radius:var(--radius);
  padding:3rem;display:grid;grid-template-columns:1fr 1fr;gap:3rem;align-items:center
}
@media(max-width:900px){.ai-card{grid-template-columns:1fr}}
.ai-title{font-size:1.9rem;font-weight:900;margin-bottom:1rem}
.ai-title .hl{color:var(--purple)}
.ai-desc{color:var(--muted);margin-bottom:1.5rem;font-size:.92rem;line-height:1.8}
.ai-features{list-style:none;margin-bottom:2rem}
.ai-features li{display:flex;align-items:center;gap:.5rem;padding:.4rem 0;font-size:.88rem;color:var(--muted)}
.ai-features li::before{content:"🔮";flex-shrink:0}
.ai-demo{background:var(--card);border:1px solid rgba(167,139,250,.2);border-radius:var(--radius2);padding:1.5rem}
.ai-demo-title{color:var(--purple);font-size:.85rem;font-weight:700;margin-bottom:1rem;display:flex;align-items:center;gap:.4rem}
.ai-demo-item{display:flex;justify-content:space-between;align-items:center;padding:.5rem 0;border-bottom:1px solid var(--border);font-size:.83rem}
.ai-demo-item:last-child{border-bottom:none}
.ai-demo-lbl{color:var(--muted)}
.ai-demo-val{font-weight:700}
.ai-demo-val.up{color:var(--green)}.ai-demo-val.dn{color:var(--red)}.ai-demo-val.pu{color:var(--purple)}

/* ══ PAYMENT SECTION ══ */
.payment-section{background:var(--bg2)}
.payment-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:1.2rem}
@media(max-width:900px){.payment-grid{grid-template-columns:repeat(3,1fr)}}
@media(max-width:600px){.payment-grid{grid-template-columns:repeat(2,1fr)}}
.pay-card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius2);padding:1.5rem;text-align:center;transition:all .2s}
.pay-card:hover{border-color:var(--border2);transform:translateY(-3px)}
.pay-card.crypto{border-color:rgba(247,147,26,.2)}
.pay-card.crypto:hover{border-color:rgba(247,147,26,.5)}
.pay-card.pp{border-color:rgba(0,112,243,.2)}
.pay-card.pp:hover{border-color:rgba(0,112,243,.5)}
.pay-other{
  background:transparent;border:2px dashed var(--border2);border-radius:var(--radius2);
  padding:1.5rem;text-align:center;cursor:pointer;transition:all .2s;text-decoration:none;display:block
}
.pay-other:hover{background:var(--gold3);border-color:var(--gold);transform:translateY(-3px)}
.pay-icon{font-size:2.2rem;margin-bottom:.6rem}
.pay-name{font-size:.9rem;font-weight:700;color:var(--gold);margin-bottom:.3rem}
.pay-desc{font-size:.76rem;color:var(--muted)}

/* ══ ABOUT SECTION ══ */
.about-section{background:var(--bg3)}
.about-grid{display:grid;grid-template-columns:1fr 1fr;gap:3rem;align-items:start}
@media(max-width:900px){.about-grid{grid-template-columns:1fr}}
.about-card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:2rem}
.about-stat-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:1rem;margin-top:1.5rem}
.astat{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius2);padding:1.2rem;text-align:center}
.astat-num{font-size:1.8rem;font-weight:900;color:var(--gold);line-height:1}
.astat-lbl{font-size:.72rem;color:var(--muted);margin-top:.2rem}
.about-list{list-style:none;margin-top:1.2rem}
.about-list li{display:flex;align-items:flex-start;gap:.7rem;padding:.55rem 0;border-bottom:1px solid var(--border);font-size:.86rem}
.about-list li:last-child{border-bottom:none}
.about-list li .al-icon{flex-shrink:0;font-size:1.1rem;margin-top:.05rem}
.about-list li .al-text{color:var(--muted);line-height:1.6}
.about-list li .al-text strong{color:var(--text)}
.tech-stack{display:flex;flex-wrap:wrap;gap:.5rem;margin-top:1rem}
.tech-chip{background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:.3rem .75rem;font-size:.76rem;font-weight:600;color:var(--muted)}
.tech-chip.active{border-color:var(--border2);color:var(--gold);background:var(--gold3)}

/* ══ LIVE INDICATOR ══ */
.live-badge{
  display:inline-flex;align-items:center;gap:.4rem;
  background:rgba(34,197,94,.1);border:1px solid rgba(34,197,94,.3);
  border-radius:50px;padding:.25rem .7rem;font-size:.72rem;color:var(--green);font-weight:700
}
.ws-status{font-size:.68rem;color:var(--muted2);text-align:center;margin-top:.4rem}

/* ══ FOOTER ══ */
.footer{background:#050508;border-top:1px solid var(--border);padding:3rem 2rem 2rem}
.footer-grid{display:grid;grid-template-columns:2fr 1fr 1fr;gap:3rem;max-width:1200px;margin:0 auto}
@media(max-width:768px){.footer-grid{grid-template-columns:1fr}}
.footer-brand .fb-logo{font-size:1.2rem;font-weight:900;color:var(--gold);margin-bottom:.8rem;display:flex;align-items:center;gap:.5rem}
.footer-brand .fb-desc{font-size:.83rem;color:var(--muted);line-height:1.7;max-width:280px}
.footer-links h4{font-size:.88rem;font-weight:700;color:var(--gold);margin-bottom:1rem}
.footer-links a{display:block;font-size:.82rem;color:var(--muted);padding:.25rem 0;transition:color .2s}
.footer-links a:hover{color:var(--gold)}
.footer-bottom{max-width:1200px;margin:2rem auto 0;padding-top:1.5rem;border-top:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:1rem}
.footer-bottom p{font-size:.78rem;color:var(--muted2)}
.footer-wa{background:var(--gold);color:#000;padding:.45rem 1.1rem;border-radius:8px;font-size:.82rem;font-weight:700;display:flex;align-items:center;gap:.4rem;transition:all .2s}
.footer-wa:hover{background:#fff}

/* ══ WHATSAPP FAB ══ */
.wa-fab{
  position:fixed;bottom:1.8rem;left:1.8rem;z-index:999;
  background:#25d366;color:#fff;width:58px;height:58px;border-radius:50%;
  display:flex;align-items:center;justify-content:center;font-size:1.6rem;
  box-shadow:0 4px 20px rgba(37,211,102,.4);transition:all .3s;text-decoration:none
}
.wa-fab:hover{transform:scale(1.1);box-shadow:0 6px 28px rgba(37,211,102,.5)}

/* ══ SEPARATOR ══ */
.sep{height:1px;background:linear-gradient(90deg,transparent,var(--border2),transparent);margin:0 2rem}

/* ══ UTILS ══ */
.text-gold{color:var(--gold)}
.text-green{color:var(--green)}
.text-red{color:var(--red)}
.text-muted{color:var(--muted)}
.d-flex{display:flex}
.align-center{align-items:center}
.gap-1{gap:.5rem}

/* ══ CHART SECTION ══ */
.chart-section{background:var(--bg2);padding:4rem 2rem}
.chart-wrap{background:var(--card);border:1px solid var(--border2);border-radius:var(--radius);overflow:hidden}
.chart-header{display:flex;align-items:center;justify-content:space-between;padding:1.2rem 1.5rem;border-bottom:1px solid var(--border)}
.chart-title{font-size:1rem;font-weight:700;color:var(--gold)}
.chart-meta{font-size:.78rem;color:var(--muted)}
.tv-chart{height:420px;background:var(--card)}
@media(max-width:768px){.tv-chart{height:280px}}
</style>
</head>
<body>

<!-- NAVBAR -->
<nav class="navbar">
  <div class="nav-logo">
    <div class="nav-logo-icon">⚡</div>
    <span>بوت التداول الذكي</span>
  </div>
  <div class="nav-links">
    <a href="#signal">الإشارات</a>
    <a href="#features">المميزات</a>
    <a href="#plans">الخطط</a>
    <a href="#courses">الكورسات</a>
    <a href="#payment">الدفع</a>
    <a href="#about">عن النظام</a>
  </div>
  <div class="nav-right">
    <div class="nav-price">
      <div class="nav-live-dot"></div>
      <span id="nav-price-val">جاري التحميل...</span>
    </div>
    <a href="{{ whatsapp }}" class="nav-cta" target="_blank">اشترك الآن</a>
  </div>
</nav>

<!-- HERO -->
<section class="hero">
  <div class="hero-bg"></div>
  <div class="hero-grid">
    <div>
      <div class="badge-live">
        <div class="nav-live-dot"></div>
        نظام إشارات XAUUSD لحظي مباشر
      </div>
      <h1 class="hero-title">
        إشارات تداول <span class="hl">الذهب</span><br>
        بـ <span class="hl2">12 مصدر تأكيد</span><br>
        وذكاء اصطناعي
      </h1>
      <p class="hero-sub">
        نظام محترف يجمع RSI، MACD، Bollinger، Fibonacci، ATR، Stochastic وغيرها في إشارة واحدة دقيقة — مدعومة بـ Gemini Vision لتحليل الشارت.
      </p>
      <div class="hero-btns">
        <a href="{{ whatsapp }}" class="btn-primary" target="_blank">💬 ابدأ مجاناً</a>
        <a href="#plans" class="btn-outline">🎯 عرض الخطط</a>
      </div>
      <div class="hero-stats">
        <div class="hstat">
          <div class="hstat-num" id="h-users">—</div>
          <div class="hstat-lbl">مستخدم نشط</div>
        </div>
        <div class="hstat">
          <div class="hstat-num" id="h-signals">—</div>
          <div class="hstat-lbl">إشارة أُرسلت</div>
        </div>
        <div class="hstat">
          <div class="hstat-num">12</div>
          <div class="hstat-lbl">مصدر تأكيد</div>
        </div>
        <div class="hstat">
          <div class="hstat-num">{{ free_signals }}</div>
          <div class="hstat-lbl">إشارات مجانية</div>
        </div>
      </div>
    </div>

    <!-- LIVE PRICE CARD -->
    <div class="price-card">
      <div class="pc-header">
        <div class="pc-pair">
          <div class="nav-live-dot"></div>
          XAUUSD — الذهب مقابل الدولار
        </div>
        <div class="pc-badge">LIVE</div>
      </div>
      <div class="pc-price" id="pc-price">—</div>
      <div class="pc-change" id="pc-change">—</div>
      <div class="pc-meta">
        <div class="pcm-item">
          <div class="pcm-val text-green" id="pc-high">—</div>
          <div class="pcm-lbl">أعلى اليوم</div>
        </div>
        <div class="pcm-item">
          <div class="pcm-val text-red" id="pc-low">—</div>
          <div class="pcm-lbl">أدنى اليوم</div>
        </div>
        <div class="pcm-item">
          <div class="pcm-val" id="pc-updated" style="color:var(--muted);font-size:.8rem">—</div>
          <div class="pcm-lbl">آخر تحديث</div>
        </div>
      </div>
      <div class="pc-chart-wrap">
        <canvas id="miniChart"></canvas>
      </div>
      <div class="pc-indicators" id="pc-indicators">
        <div class="pci neu"><div class="n">RSI</div><div class="v">—</div></div>
        <div class="pci neu"><div class="n">MACD</div><div class="v">—</div></div>
        <div class="pci neu"><div class="n">الاتجاه</div><div class="v">—</div></div>
      </div>
      <div class="session-info">
        <div class="session-dot"></div>
        <span id="session-name">السوق مفتوح — جلسة نيويورك</span>
      </div>
      <div class="pc-updated" id="pc-updated-time">البيانات من Finnhub WebSocket + GoldPrice API</div>
    </div>
  </div>
</section>

<!-- TICKER -->
<div class="ticker">
  <div class="ticker-inner" id="ticker-inner">
    <span class="ticker-item"><span class="t">XAUUSD</span><span id="tk-price">—</span></span>
    <div class="ticker-dot"></div>
    <span class="ticker-item"><span class="t">RSI(14)</span><span id="tk-rsi">—</span></span>
    <div class="ticker-dot"></div>
    <span class="ticker-item"><span class="t">اتجاه السوق</span><span id="tk-trend">—</span></span>
    <div class="ticker-dot"></div>
    <span class="ticker-item"><span class="t">جلسة</span><span id="tk-session">—</span></span>
    <div class="ticker-dot"></div>
    <span class="ticker-item"><span class="t">تحليل AI</span><span style="color:var(--purple)">Gemini Vision ✓</span></span>
    <div class="ticker-dot"></div>
    <span class="ticker-item"><span class="t">مصادر التأكيد</span><span style="color:var(--gold)">12 مصدر</span></span>
    <div class="ticker-dot"></div>
    <!-- DUPLICATE -->
    <span class="ticker-item"><span class="t">XAUUSD</span><span id="tk-price2">—</span></span>
    <div class="ticker-dot"></div>
    <span class="ticker-item"><span class="t">RSI(14)</span><span id="tk-rsi2">—</span></span>
    <div class="ticker-dot"></div>
    <span class="ticker-item"><span class="t">اتجاه السوق</span><span id="tk-trend2">—</span></span>
    <div class="ticker-dot"></div>
    <span class="ticker-item"><span class="t">جلسة</span><span id="tk-session2">—</span></span>
    <div class="ticker-dot"></div>
    <span class="ticker-item"><span class="t">تحليل AI</span><span style="color:var(--purple)">Gemini Vision ✓</span></span>
    <div class="ticker-dot"></div>
    <span class="ticker-item"><span class="t">مصادر التأكيد</span><span style="color:var(--gold)">12 مصدر</span></span>
  </div>
</div>

<!-- STATS BAR -->
<div class="stats-bar">
  <div class="container">
    <div class="stats-grid">
      <div class="stat-item">
        <div class="stat-num" id="st-users">—</div>
        <div class="stat-lbl">مستخدم مسجّل في البوت</div>
      </div>
      <div class="stat-item">
        <div class="stat-num" id="st-signals">—</div>
        <div class="stat-lbl">إشارة أُرسلت عبر Telegram</div>
      </div>
      <div class="stat-item">
        <div class="stat-num">12</div>
        <div class="stat-lbl">مصدر تأكيد لكل إشارة</div>
      </div>
      <div class="stat-item">
        <div class="stat-num">24/7</div>
        <div class="stat-lbl">مراقبة السوق بلا توقف</div>
      </div>
    </div>
  </div>
</div>

<!-- SIGNAL SECTION -->
<section class="signal-section" id="signal">
  <div class="container">
    <div class="sec-header">
      <div class="sec-badge">⚡ آخر إشارة</div>
      <h2 class="sec-title">إشارة <span class="hl">XAUUSD</span> الحقيقية</h2>
      <p class="sec-sub">الإشارات تُولَّد من 12 مصدر تأكيد فني حقيقي وتُرسل مباشرة عبر Telegram</p>
    </div>
    <div class="signal-grid">
      <!-- Latest Signal Card -->
      <div class="signal-card" id="signal-card">
        <div class="no-signal" id="signal-loading">
          <div class="ns-icon">⏳</div>
          <p>جاري تحميل آخر إشارة...</p>
        </div>
        <div id="signal-content" style="display:none">
          <div class="sig-header">
            <div class="sig-pair">XAUUSD • الذهب</div>
            <div class="sig-dir" id="sig-dir">—</div>
          </div>
          <div class="sig-row">
            <div class="sig-lbl">نقطة الدخول</div>
            <div class="sig-val" id="sig-entry">—</div>
          </div>
          <div class="sig-row">
            <div class="sig-lbl">هدف 1 (TP1)</div>
            <div class="sig-val text-green" id="sig-tp1">—</div>
          </div>
          <div class="sig-row">
            <div class="sig-lbl">هدف 2 (TP2)</div>
            <div class="sig-val text-green" id="sig-tp2">—</div>
          </div>
          <div class="sig-row">
            <div class="sig-lbl">هدف 3 (TP3)</div>
            <div class="sig-val text-green sig-val blur" id="sig-tp3">—</div>
          </div>
          <div class="sig-row">
            <div class="sig-lbl">وقف الخسارة</div>
            <div class="sig-val text-red" id="sig-sl">—</div>
          </div>
          <div class="sig-row">
            <div class="sig-lbl">الإطار الزمني</div>
            <div class="sig-val" id="sig-tf">—</div>
          </div>
          <div class="sig-conf">
            <div class="conf-bar"><div class="conf-fill" id="sig-conf-bar" style="width:0%"></div></div>
            <div class="conf-pct" id="sig-conf-pct">—</div>
          </div>
          <div class="sig-sources" id="sig-sources"></div>
          <div class="sig-row" style="margin-top:.5rem">
            <div class="sig-lbl" style="font-size:.75rem">🕐 وقت الإشارة</div>
            <div class="sig-val" id="sig-time" style="font-size:.78rem;font-family:Cairo">—</div>
          </div>
        </div>
      </div>

      <!-- Free Trial Box -->
      <div class="trial-box">
        <div class="trial-num">{{ free_signals }}</div>
        <div class="trial-label">إشارات مجانية حقيقية</div>
        <ul class="trial-features">
          <li>الدخول + TP1 + وقف الخسارة كاملة</li>
          <li>نسبة الثقة من 12 مصدر تأكيد</li>
          <li>مؤشرات RSI و MACD المباشرة</li>
          <li>تنبيه فوري عبر Telegram</li>
          <li>بيانات Finnhub لحظية</li>
        </ul>
        <a href="{{ whatsapp }}" class="cta-free" target="_blank">💬 ابدأ التجربة المجانية الآن</a>
        <p style="font-size:.75rem;color:var(--muted2);margin-top:.8rem">بدون رسوم • لا تتطلب بطاقة</p>
      </div>
    </div>
  </div>
</section>

<div class="sep"></div>

<!-- FEATURES -->
<section id="features">
  <div class="container">
    <div class="sec-header center">
      <div class="sec-badge">🔬 المميزات الحقيقية</div>
      <h2 class="sec-title">كل شيء <span class="hl">فعلي وحي</span> — لا بيانات وهمية</h2>
      <p class="sec-sub">كل ميزة مبنية على بيانات حقيقية من Finnhub WebSocket وخوارزميات تحليل فني مُطوَّرة</p>
    </div>
    <div class="features-grid">
      <div class="feat-card">
        <div class="feat-icon">📡</div>
        <div class="feat-title">بيانات لحظية Finnhub</div>
        <div class="feat-desc">WebSocket مباشر مع Finnhub لأسعار XAUUSD لحظة بلحظة، مع Fallback من GoldPrice API لضمان الاستمرارية 24/7</div>
      </div>
      <div class="feat-card">
        <div class="feat-icon">🧠</div>
        <div class="feat-title">Gemini Vision للشارت</div>
        <div class="feat-desc">15 مفتاح Gemini AI مع تدوير تلقائي — ترسل صورة الشارت ويعطيك تحليل فني كامل: اتجاه، دعم، مقاومة، دخول، هدف، وقف</div>
      </div>
      <div class="feat-card">
        <div class="feat-icon">📊</div>
        <div class="feat-title">12 مصدر تأكيد</div>
        <div class="feat-desc">RSI + MACD + Bollinger Bands + ATR + Stochastic + Fibonacci + EMA + دعم/مقاومة + جلسة السوق + الحجم + الزخم + الاتجاه</div>
      </div>
      <div class="feat-card">
        <div class="feat-icon">⚡</div>
        <div class="feat-title">إرسال تلقائي Telegram</div>
        <div class="feat-desc">الإشارات تُرسل تلقائياً لجميع المشتركين فور توليدها، مع TP1 + TP2 + TP3 + وقف الخسارة ونسبة الثقة</div>
      </div>
      <div class="feat-card">
        <div class="feat-icon">🛡️</div>
        <div class="feat-title">حماية رأس المال</div>
        <div class="feat-desc">النظام لا يُصدر إشارة إلا عندما تتوافق الأغلبية من مصادر التأكيد — يرفض الإشارات الضعيفة لحماية المتداول</div>
      </div>
      <div class="feat-card">
        <div class="feat-icon">🌍</div>
        <div class="feat-title">مراقبة جلسات السوق</div>
        <div class="feat-desc">يتتبع تلقائياً جلسات لندن ونيويورك وآسيا — يُرسل تنبيهاً عند فتح السوق وعند الفترات الأكثر سيولة</div>
      </div>
    </div>
  </div>
</section>

<!-- INDICATORS SECTION -->
<section class="indicators-section" id="indicators">
  <div class="container">
    <div class="sec-header center">
      <div class="sec-badge">📐 المؤشرات الفنية</div>
      <h2 class="sec-title">كل المؤشرات <span class="hl">محسوبة فعلياً</span></h2>
      <p class="sec-sub">لا قيم وهمية — كل مؤشر يُحسَب من بيانات الأسعار الحقيقية لحظة بلحظة</p>
    </div>
    <div class="ind-grid">
      <div class="ind-chip">
        <div class="ic-icon">📈</div>
        <div class="ic-name">RSI (14)</div>
        <div class="ic-desc">مؤشر القوة النسبية</div>
      </div>
      <div class="ind-chip">
        <div class="ic-icon">📉</div>
        <div class="ic-name">MACD (12/26/9)</div>
        <div class="ic-desc">تقارب/تباعد المتوسطات</div>
      </div>
      <div class="ind-chip">
        <div class="ic-icon">🎯</div>
        <div class="ic-name">Bollinger Bands</div>
        <div class="ic-desc">نطاقات بولينجر (20 فترة)</div>
      </div>
      <div class="ind-chip">
        <div class="ic-icon">🌡️</div>
        <div class="ic-name">ATR (14)</div>
        <div class="ic-desc">متوسط المدى الحقيقي</div>
      </div>
      <div class="ind-chip">
        <div class="ic-icon">🔄</div>
        <div class="ic-name">Stochastic (14)</div>
        <div class="ic-desc">المذبذب الاستوكاستيكي</div>
      </div>
      <div class="ind-chip">
        <div class="ic-icon">🌀</div>
        <div class="ic-name">Fibonacci</div>
        <div class="ic-desc">مستويات إيباچي 61.8%</div>
      </div>
      <div class="ind-chip">
        <div class="ic-icon">〰️</div>
        <div class="ic-name">EMA (9/21/50)</div>
        <div class="ic-desc">المتوسط المتحرك الأسي</div>
      </div>
      <div class="ind-chip">
        <div class="ic-icon">🧱</div>
        <div class="ic-name">دعم / مقاومة</div>
        <div class="ic-desc">مستويات S/R الديناميكية</div>
      </div>
      <div class="ind-chip">
        <div class="ic-icon">🕐</div>
        <div class="ic-name">جلسة السوق</div>
        <div class="ic-desc">لندن / نيويورك / آسيا</div>
      </div>
      <div class="ind-chip">
        <div class="ic-icon">📦</div>
        <div class="ic-name">الزخم السعري</div>
        <div class="ic-desc">Rate of Change (ROC)</div>
      </div>
      <div class="ind-chip">
        <div class="ic-icon">🏔️</div>
        <div class="ic-name">القمم والقيعان</div>
        <div class="ic-desc">Higher High / Lower Low</div>
      </div>
      <div class="ind-chip">
        <div class="ic-icon">🧮</div>
        <div class="ic-name">تأكيد الاتجاه</div>
        <div class="ic-desc">Trend Confirmation Score</div>
      </div>
    </div>
  </div>
</section>

<!-- AI CHART SECTION -->
<section class="ai-section">
  <div class="container">
    <div class="ai-card">
      <div>
        <div class="sec-badge">🔮 ذكاء اصطناعي</div>
        <h2 class="ai-title">تحليل <span class="hl">الشارت</span> بـ Gemini Vision</h2>
        <p class="ai-desc">أرسل صورة شارتك وسيُحللها نظام Gemini AI الحقيقي من Google — يُحدد الاتجاه، النماذج الفنية، الدعم والمقاومة، ويُعطيك نقطة دخول + هدف + وقف خسارة.</p>
        <ul class="ai-features">
          <li>كشف تلقائي للنماذج (رأس وأكتاف، مثلثات، أعلام)</li>
          <li>تحديد مستويات الدعم والمقاومة البصرية</li>
          <li>نقطة دخول + TP1 + TP2 + وقف خسارة</li>
          <li>نسبة ثقة وتقييم المخاطرة من 1-10</li>
          <li>15 مفتاح Gemini مع تدوير تلقائي</li>
        </ul>
        <a href="{{ whatsapp }}" class="btn-primary" target="_blank" style="display:inline-flex">💬 جرّب الآن</a>
      </div>
      <div class="ai-demo">
        <div class="ai-demo-title">🧠 نموذج تحليل شارت</div>
        <div class="ai-demo-item">
          <div class="ai-demo-lbl">الاتجاه العام</div>
          <div class="ai-demo-val up">صاعد قوي ↗</div>
        </div>
        <div class="ai-demo-item">
          <div class="ai-demo-lbl">النموذج المكتشف</div>
          <div class="ai-demo-val pu">مثلث صاعد</div>
        </div>
        <div class="ai-demo-item">
          <div class="ai-demo-lbl">أقوى دعم</div>
          <div class="ai-demo-val">3,284</div>
        </div>
        <div class="ai-demo-item">
          <div class="ai-demo-lbl">أقوى مقاومة</div>
          <div class="ai-demo-val">3,321</div>
        </div>
        <div class="ai-demo-item">
          <div class="ai-demo-lbl">نقطة الدخول</div>
          <div class="ai-demo-val text-gold">3,291</div>
        </div>
        <div class="ai-demo-item">
          <div class="ai-demo-lbl">تقييم المخاطرة</div>
          <div class="ai-demo-val up">3 / 10 ✅</div>
        </div>
        <div style="margin-top:1rem;padding:.6rem;background:rgba(167,139,250,.08);border-radius:8px;border:1px solid rgba(167,139,250,.2);font-size:.75rem;color:var(--muted)">
          ⚠️ هذا مثال توضيحي. التحليل الحقيقي يُولَّد من Gemini Vision بناءً على صورة الشارت الفعلية.
        </div>
      </div>
    </div>
  </div>
</section>

<div class="sep"></div>

<!-- PLANS -->
<section class="plans-section" id="plans">
  <div class="container">
    <div class="sec-header center">
      <div class="sec-badge">💎 الخطط</div>
      <h2 class="sec-title">اختر <span class="hl">الخطة</span> المناسبة لك</h2>
      <p class="sec-sub">جميع الخطط تحتوي على بيانات حقيقية وإشارات فعلية من نفس النظام</p>
    </div>
    <div class="plans-grid">

      <!-- SILVER -->
      <div class="plan-card">
        <div class="plan-icon">🥉</div>
        <div class="plan-name silver">الفضية</div>
        <div class="plan-price">
          <div class="amount">9.99$</div>
          <div class="period">/ شهرياً</div>
        </div>
        <ul class="plan-features">
          <li class="has"><span class="pf-icon">✅</span> سعر الذهب الحي (XAUUSD)</li>
          <li class="has"><span class="pf-icon">✅</span> 15 إشارة يومياً كاملة</li>
          <li class="has"><span class="pf-icon">✅</span> دخول + TP1 + وقف الخسارة</li>
          <li class="has"><span class="pf-icon">✅</span> RSI (14) + MACD (12/26/9)</li>
          <li class="has"><span class="pf-icon">✅</span> معلومة الجلسة التداولية</li>
          <li class="has"><span class="pf-icon">✅</span> دعم واتساب</li>
          <li class="no"><span class="pf-icon">❌</span> تحليل شارت AI</li>
          <li class="no"><span class="pf-icon">❌</span> مؤشرات متقدمة (BB/ATR/Fib)</li>
          <li class="no"><span class="pf-icon">❌</span> إشارات تلقائية 24/7</li>
        </ul>
        <div class="plan-note">⚠️ الكورسات مدفوعة بشكل منفصل</div>
        <a href="{{ whatsapp }}" class="plan-btn outline" target="_blank">💬 اشترك الفضية</a>
      </div>

      <!-- GOLD (popular) -->
      <div class="plan-card popular">
        <div class="plan-popular-badge">🔥 الأكثر مبيعاً</div>
        <div class="plan-icon">🥈</div>
        <div class="plan-name gold">الذهبية</div>
        <div class="plan-price">
          <div class="amount">17.99$</div>
          <div class="period">/ شهرياً</div>
        </div>
        <ul class="plan-features">
          <li class="has"><span class="pf-icon">✅</span> سعر الذهب الحي (XAUUSD)</li>
          <li class="has"><span class="pf-icon">✅</span> 20 إشارة يومياً كاملة</li>
          <li class="has"><span class="pf-icon">✅</span> TP1 + TP2 + TP3 + وقف الخسارة</li>
          <li class="has"><span class="pf-icon">✅</span> جميع المؤشرات الـ12</li>
          <li class="has"><span class="pf-icon">✅</span> 3 تحليلات شارت AI يومياً</li>
          <li class="has"><span class="pf-icon">✅</span> نسبة الثقة + عدد مصادر التأكيد</li>
          <li class="has"><span class="pf-icon">✅</span> دعم واتساب أولوية</li>
          <li class="no"><span class="pf-icon">❌</span> إشارات تلقائية غير محدودة</li>
        </ul>
        <div class="plan-note">⚠️ الكورسات مدفوعة بشكل منفصل</div>
        <a href="{{ whatsapp }}" class="plan-btn primary" target="_blank">💬 اشترك الذهبية</a>
      </div>

      <!-- DIAMOND -->
      <div class="plan-card">
        <div class="plan-icon">💎</div>
        <div class="plan-name diamond">الماسية VIP</div>
        <div class="plan-price">
          <div class="amount">34.99$</div>
          <div class="period">/ شهرياً</div>
        </div>
        <ul class="plan-features">
          <li class="has"><span class="pf-icon">✅</span> سعر الذهب الحي (XAUUSD)</li>
          <li class="has"><span class="pf-icon">✅</span> إشارات غير محدودة 24/7</li>
          <li class="has"><span class="pf-icon">✅</span> TP1 + TP2 + TP3 + وقف الخسارة</li>
          <li class="has"><span class="pf-icon">✅</span> جميع المؤشرات الـ12</li>
          <li class="has"><span class="pf-icon">✅</span> تحليل شارت AI غير محدود</li>
          <li class="has"><span class="pf-icon">✅</span> إشعار فوري >80% ثقة</li>
          <li class="has"><span class="pf-icon">✅</span> تحديث Finnhub WebSocket</li>
          <li class="has"><span class="pf-icon">✅</span> دعم VIP مباشر 24/7</li>
        </ul>
        <div class="plan-note">⚠️ الكورسات مدفوعة بشكل منفصل</div>
        <a href="{{ whatsapp }}" class="plan-btn outline" target="_blank">💬 اشترك الماسية</a>
      </div>
    </div>
    <div class="plans-note">
      ⚠️ <strong>ملاحظة:</strong> الكورسات التعليمية مدفوعة بشكل منفصل وغير مشمولة في أي خطة اشتراك — تواصل معنا للاستفسار عن أسعار الكورسات
    </div>
  </div>
</section>

<!-- COURSES SECTION -->
<section class="courses-section" id="courses">
  <div class="container">
    <div class="sec-header center">
      <div class="sec-badge">📚 الكورسات</div>
      <h2 class="sec-title">مكتبة <span class="hl">الكورسات</span> التعليمية</h2>
      <p class="sec-sub">أكثر من 170+ كورس في التداول — تُشترى بشكل منفصل غير مرتبط بخطط الاشتراك</p>
    </div>
    <div class="courses-grid">
      {{ courses_html }}
    </div>
    <div class="courses-cta">
      <p style="color:var(--muted);margin-bottom:1rem;font-size:.88rem">
        💡 الكورسات مدفوعة بشكل منفصل — تواصل معنا لمعرفة الأسعار والتفاصيل
      </p>
      <a href="{{ whatsapp }}" class="btn-primary" target="_blank" style="display:inline-flex">
        💬 استفسر عن الكورسات
      </a>
    </div>
  </div>
</section>

<!-- ABOUT SECTION -->
<section class="about-section" id="about">
  <div class="container">
    <div class="sec-header center">
      <div class="sec-badge">ℹ️ عن النظام</div>
      <h2 class="sec-title">نظام <span class="hl">متكامل ومتطور</span> للتداول الذكي</h2>
      <p class="sec-sub">ليس مجرد بوت — منظومة كاملة مبنية على أحدث تقنيات الذكاء الاصطناعي وتحليل البيانات اللحظية</p>
    </div>
    <div class="about-grid">
      <div>
        <div class="about-card" style="margin-bottom:1.5rem">
          <div style="font-size:.85rem;font-weight:700;color:var(--gold);margin-bottom:1rem;display:flex;align-items:center;gap:.4rem">
            🏗️ مكوّنات النظام
          </div>
          <ul class="about-list">
            <li>
              <span class="al-icon">📡</span>
              <div class="al-text"><strong>Finnhub WebSocket (لحظي)</strong> — اتصال مباشر بخوادم Finnhub لجلب أسعار XAUUSD tick-by-tick بأقل من ثانية، مع Fallback تلقائي عبر Yahoo Finance</div>
            </li>
            <li>
              <span class="al-icon">🧠</span>
              <div class="al-text"><strong>Gemini Vision AI (15 مفتاح)</strong> — تحليل صور الشارت بنماذج gemini-1.5-flash/pro مع تدوير تلقائي ذكي بين المفاتيح عند نفاد الحصة</div>
            </li>
            <li>
              <span class="al-icon">📊</span>
              <div class="al-text"><strong>محرك التحليل الفني</strong> — يحسب 12 مؤشر في الوقت الفعلي (RSI، MACD، Bollinger، ATR، Stochastic، Fibonacci، EMA، دعم/مقاومة...) من بيانات الأسعار الحية</div>
            </li>
            <li>
              <span class="al-icon">⚡</span>
              <div class="al-text"><strong>محرك توليد الإشارات</strong> — لا يُصدر إشارة إلا عند توافق أغلبية المصادر، يرفض الإشارات الضعيفة لحماية رأس المال تلقائياً</div>
            </li>
            <li>
              <span class="al-icon">🤖</span>
              <div class="al-text"><strong>Telegram Bot API (python-telegram-bot)</strong> — إرسال فوري لآلاف المشتركين مع دعم الصور والاستبيانات والبث الجماعي من لوحة التحكم</div>
            </li>
            <li>
              <span class="al-icon">🗄️</span>
              <div class="al-text"><strong>SQLite + SQLAlchemy ORM</strong> — قاعدة بيانات محلية لإدارة المستخدمين والإشارات والإحصاءات مع APScheduler للمهام المجدوَلة</div>
            </li>
          </ul>
        </div>
        <div class="about-card">
          <div style="font-size:.85rem;font-weight:700;color:var(--gold);margin-bottom:.8rem">⚙️ التقنيات المستخدمة</div>
          <div class="tech-stack">
            <div class="tech-chip active">Python 3.11</div>
            <div class="tech-chip active">Flask</div>
            <div class="tech-chip active">python-telegram-bot 20</div>
            <div class="tech-chip active">Google Gemini AI</div>
            <div class="tech-chip active">Finnhub WebSocket</div>
            <div class="tech-chip active">Yahoo Finance API</div>
            <div class="tech-chip active">SQLAlchemy ORM</div>
            <div class="tech-chip active">APScheduler</div>
            <div class="tech-chip">MetaApi MT5</div>
            <div class="tech-chip">Pillow (Image)</div>
            <div class="tech-chip">NumPy</div>
            <div class="tech-chip">Chart.js</div>
          </div>
        </div>
      </div>
      <div>
        <div class="about-card" style="margin-bottom:1.5rem">
          <div style="font-size:.85rem;font-weight:700;color:var(--gold);margin-bottom:1rem">📈 ماذا يفعل النظام؟</div>
          <ul class="about-list">
            <li><span class="al-icon">🔄</span><div class="al-text"><strong>يراقب السوق 24/7</strong> — يتابع أسعار الذهب XAUUSD لحظة بلحظة ويراقب التغيرات الكبيرة ويُنبّه المتداولين فوراً</div></li>
            <li><span class="al-icon">📐</span><div class="al-text"><strong>يحلّل فنياً بدقة</strong> — يُشغّل 12 خوارزمية تحليل فني في وقت واحد ويجمع نتائجها في "نقطة ثقة" واحدة من 100%</div></li>
            <li><span class="al-icon">🎯</span><div class="al-text"><strong>يُصدر إشارات دقيقة</strong> — يُرسل إشارة BUY أو SELL مع نقطة دخول + TP1+TP2+TP3 + وقف خسارة محسوب بدقة</div></li>
            <li><span class="al-icon">🧠</span><div class="al-text"><strong>يحلّل الشارت بصرياً</strong> — يقبل صورة الشارت من المستخدم ويُحللها بـ Gemini Vision ويُعطي تحليلاً مفصلاً باللغة العربية</div></li>
            <li><span class="al-icon">📊</span><div class="al-text"><strong>يُدير المجتمع</strong> — يضم قاعدة بيانات المشتركين، يُرسل تذكيرات يومية، يدير الاشتراكات والصلاحيات</div></li>
            <li><span class="al-icon">🕐</span><div class="al-text"><strong>يراقب جلسات السوق</strong> — يُتابع جلسات لندن / نيويورك / آسيا ويُنبّه عند أوقات السيولة العالية</div></li>
          </ul>
        </div>
        <div class="about-card">
          <div style="font-size:.85rem;font-weight:700;color:var(--gold);margin-bottom:1rem">🏆 أرقام حقيقية</div>
          <div class="about-stat-grid">
            <div class="astat">
              <div class="astat-num" id="ab-users">—</div>
              <div class="astat-lbl">مستخدم مسجّل</div>
            </div>
            <div class="astat">
              <div class="astat-num" id="ab-signals">—</div>
              <div class="astat-lbl">إشارة أُرسلت</div>
            </div>
            <div class="astat">
              <div class="astat-num">12</div>
              <div class="astat-lbl">مصدر تأكيد</div>
            </div>
            <div class="astat">
              <div class="astat-num">15</div>
              <div class="astat-lbl">مفتاح Gemini AI</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</section>

<div class="sep"></div>

<!-- PAYMENT SECTION -->
<section class="payment-section" id="payment">
  <div class="container">
    <div class="sec-header center">
      <div class="sec-badge">💳 طرق الدفع</div>
      <h2 class="sec-title">ادفع بـ <span class="hl">الطريقة</span> الأسهل لك</h2>
      <p class="sec-sub">7 طرق دفع متاحة — بعد الدفع تواصل معنا عبر واتساب مع إيصال الدفع لتفعيل حسابك فوراً</p>
    </div>
    <div class="payment-grid">
      <div class="pay-card">
        <div class="pay-icon">💙</div>
        <div class="pay-name">بي باب</div>
        <div class="pay-desc">تحويل إلكتروني سريع وآمن</div>
      </div>
      <div class="pay-card">
        <div class="pay-icon">💛</div>
        <div class="pay-name">بابني</div>
        <div class="pay-desc">محفظة رقمية مباشرة</div>
      </div>
      <div class="pay-card">
        <div class="pay-icon">❤️</div>
        <div class="pay-name">فودافون كاش</div>
        <div class="pay-desc">تحويل فوري</div>
      </div>
      <div class="pay-card">
        <div class="pay-icon">💳</div>
        <div class="pay-name">Visa / MasterCard</div>
        <div class="pay-desc">بطاقة الفيزا الدولية</div>
      </div>
      <div class="pay-card crypto">
        <div class="pay-icon">🟡</div>
        <div class="pay-name">Binance Pay</div>
        <div class="pay-desc">USDT / BTC / BNB</div>
      </div>
      <div class="pay-card pp">
        <div class="pay-icon">🔵</div>
        <div class="pay-name">PayPal</div>
        <div class="pay-desc">دفع دولي آمن</div>
      </div>
      <div class="pay-card">
        <div class="pay-icon">🟢</div>
        <div class="pay-name">إنستاباي</div>
        <div class="pay-desc">تحويل بنكي مباشر</div>
      </div>
      <a href="{{ whatsapp }}" class="pay-other" target="_blank">
        <div class="pay-icon">❓</div>
        <div class="pay-name" style="color:var(--gold)">لديك طريقة أخرى؟</div>
        <div class="pay-desc">تواصل معنا ونُرتّب لك</div>
      </a>
    </div>
    <div style="text-align:center;margin-top:2.5rem">
      <a href="{{ whatsapp }}" class="btn-primary" target="_blank" style="display:inline-flex">
        💬 أرسل إيصال الدفع عبر واتساب
      </a>
    </div>
  </div>
</section>

<!-- FOOTER -->
<footer class="footer">
  <div class="footer-grid">
    <div class="footer-brand">
      <div class="fb-logo">⚡ بوت التداول الذكي</div>
      <p class="fb-desc">منظومة تداول ذكية متكاملة — إشارات XAUUSD لحظية بـ12 مصدر تأكيد، Gemini Vision AI، Finnhub WebSocket، وبيانات حية أقل من ثانية. مبنية على Python 3.11 + Flask + Telegram Bot.</p>
    </div>
    <div class="footer-links">
      <h4>الروابط</h4>
      <a href="#signal">آخر إشارة</a>
      <a href="#features">المميزات</a>
      <a href="#indicators">المؤشرات</a>
      <a href="#plans">الخطط</a>
      <a href="#courses">الكورسات</a>
      <a href="#about">عن النظام</a>
      <a href="#payment">الدفع</a>
      <a href="/files">تحميل النظام</a>
    </div>
    <div class="footer-links">
      <h4>تواصل معنا</h4>
      <a href="{{ whatsapp }}" target="_blank">💬 واتساب مباشر</a>
      <a href="{{ whatsapp }}" target="_blank">📲 اشتراك الخطط</a>
      <a href="{{ whatsapp }}" target="_blank">📚 استفسار الكورسات</a>
      <a href="{{ whatsapp }}" target="_blank">💳 إيصالات الدفع</a>
    </div>
  </div>
  <div class="footer-bottom">
    <p>© 2026 بوت التداول الذكي — جميع الحقوق محفوظة</p>
    <a href="{{ whatsapp }}" class="footer-wa" target="_blank">💬 واتساب</a>
  </div>
</footer>

<!-- WhatsApp FAB -->
<a href="{{ whatsapp }}" class="wa-fab" target="_blank" title="تواصل عبر واتساب">💬</a>

<!-- JAVASCRIPT -->
<script>
let priceHistory = [];
let miniChartInstance = null;

function formatNum(n) {
  if (!n && n !== 0) return '—';
  return Number(n).toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2});
}

function getSession() {
  const h = new Date().getUTCHours();
  if (h >= 7 && h < 12) return 'جلسة لندن 🇬🇧';
  if (h >= 12 && h < 20) return 'جلسة نيويورك 🇺🇸';
  if (h >= 20 || h < 7) return 'جلسة آسيا 🌏';
  return 'جلسة مفتوحة';
}

function estimateRSI(hist) {
  if (hist.length < 5) return null;
  const prices = hist.map(h => h.p);
  const deltas = prices.slice(1).map((p,i) => p - prices[i]);
  const gains = deltas.map(d => d > 0 ? d : 0);
  const losses = deltas.map(d => d < 0 ? Math.abs(d) : 0);
  const ag = gains.reduce((a,b) => a+b, 0) / gains.length;
  const al = losses.reduce((a,b) => a+b, 0) / losses.length;
  if (!al) return 100;
  return Math.round(100 - (100 / (1 + ag/al)));
}

function estimateTrend(hist) {
  if (hist.length < 6) return '—';
  const recent = hist.slice(-6).map(h => h.p);
  const first = recent.slice(0, 3).reduce((a,b) => a+b) / 3;
  const last  = recent.slice(3).reduce((a,b) => a+b) / 3;
  if (last > first * 1.0005) return '📈 صاعد';
  if (last < first * 0.9995) return '📉 هابط';
  return '↔️ متذبذب';
}

function buildMiniChart(hist) {
  const canvas = document.getElementById('miniChart');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const labels = hist.map(() => '');
  const data   = hist.map(h => h.p);
  if (!data.length) return;

  const isUp = data[data.length-1] >= data[0];
  const color = isUp ? '#22c55e' : '#ef4444';

  if (miniChartInstance) miniChartInstance.destroy();
  miniChartInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        data,
        borderColor: color,
        borderWidth: 2,
        pointRadius: 0,
        fill: true,
        backgroundColor: ctx => {
          const g = ctx.chart.ctx.createLinearGradient(0, 0, 0, 90);
          g.addColorStop(0, isUp ? 'rgba(34,197,94,.25)' : 'rgba(239,68,68,.25)');
          g.addColorStop(1, 'rgba(0,0,0,0)');
          return g;
        },
        tension: 0.4
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {legend:{display:false},tooltip:{enabled:false}},
      scales: {x:{display:false}, y:{display:false}},
      animation: {duration:500}
    }
  });
}

// ─── Real-time price updater (shared by WS + polling) ───
let _lastPrice = null;
let _sessionHigh = null;
let _sessionLow  = null;

function applyPrice(price, chg, pct, high, low, source) {
  if (!price || price < 100) return;
  const isUp = chg >= 0;
  const sign = isUp ? '+' : '';

  document.getElementById('nav-price-val').textContent = formatNum(price);
  const priceEl = document.getElementById('pc-price');
  if (priceEl) {
    priceEl.textContent = formatNum(price);
    priceEl.style.color = isUp ? 'var(--green)' : 'var(--red)';
    setTimeout(() => { if(priceEl) priceEl.style.color = 'var(--gold)'; }, 600);
  }

  const chgEl = document.getElementById('pc-change');
  if (chgEl) {
    chgEl.textContent = `${sign}${formatNum(Math.abs(chg))} (${sign}${Math.abs(pct).toFixed(3)}%)`;
    chgEl.className = 'pc-change ' + (isUp ? 'up' : 'dn');
  }

  if (high) { const el = document.getElementById('pc-high'); if(el) el.textContent = formatNum(high); }
  if (low)  { const el = document.getElementById('pc-low');  if(el) el.textContent = formatNum(low); }

  const now = new Date();
  const timeStr = now.toLocaleTimeString('ar-EG');
  const updEl = document.getElementById('pc-updated');
  if (updEl) updEl.textContent = timeStr;

  const sess = getSession();
  const sessEl = document.getElementById('session-name');
  if (sessEl) sessEl.textContent = sess;

  ['tk-price','tk-price2'].forEach(id => { const el = document.getElementById(id); if(el) el.textContent = formatNum(price); });
  ['tk-session','tk-session2'].forEach(id => { const el = document.getElementById(id); if(el) el.textContent = sess; });

  const srcEl = document.getElementById('pc-updated-time');
  if (srcEl) srcEl.textContent = `بيانات لحظية من ${source} — تحديث آخر: ${timeStr}`;

  _lastPrice = price;
  priceHistory.push({ t: Math.floor(Date.now()/1000), p: price });
  if (priceHistory.length > 60) priceHistory.shift();
  buildMiniChart(priceHistory);
}

// ─── Binance WebSocket (sub-second real-time for XAUUSDT) ───
let binanceWS = null;
let wsConnected = false;
let wsReconnectTimer = null;

function startBinanceWS() {
  if (binanceWS) { try { binanceWS.close(); } catch(e){} }
  try {
    binanceWS = new WebSocket('wss://stream.binance.com:9443/ws/xauusdt@ticker');

    binanceWS.onopen = () => {
      wsConnected = true;
      const srcEl = document.getElementById('pc-updated-time');
      if(srcEl) srcEl.textContent = '🟢 Binance WebSocket متصل — بيانات لحظية أقل من ثانية';
    };

    binanceWS.onmessage = (event) => {
      try {
        const d = JSON.parse(event.data);
        const price = parseFloat(d.c);
        const open  = parseFloat(d.o);
        const chg   = price - open;
        const pct   = (chg / open) * 100;
        const high  = parseFloat(d.h);
        const low   = parseFloat(d.l);
        applyPrice(price, chg, pct, high, low, 'Binance WebSocket ⚡');
      } catch(e) {}
    };

    binanceWS.onerror = () => { wsConnected = false; };
    binanceWS.onclose = () => {
      wsConnected = false;
      const srcEl = document.getElementById('pc-updated-time');
      if(srcEl) srcEl.textContent = '🔴 WS انقطع — إعادة الاتصال...';
      if (wsReconnectTimer) clearTimeout(wsReconnectTimer);
      wsReconnectTimer = setTimeout(startBinanceWS, 4000);
    };
  } catch(e) {
    setTimeout(startBinanceWS, 5000);
  }
}

// ─── HTTP polling fallback (every 5s when WS active, 3s when not) ───
async function loadPrice() {
  try {
    const r = await fetch('/api/price');
    const d = await r.json();
    if (!d.price || wsConnected) return; // WS takes priority
    applyPrice(d.price, d.change||0, d.pct||0, d.high, d.low, 'Yahoo Finance (HTTP polling)');
  } catch(e) {}
}

async function loadHistory() {
  try {
    const r = await fetch('/api/history');
    const d = await r.json();
    if (!d || !d.length) return;
    priceHistory = d;
    buildMiniChart(d);

    // RSI
    const rsi  = estimateRSI(d);
    const trend = estimateTrend(d);

    const pciEls = document.querySelectorAll('.pci');
    if (pciEls[0]) {
      const v = pciEls[0].querySelector('.v');
      const rsiVal = rsi || 50;
      v.textContent = rsi ? `${rsi}` : '—';
      const cls = rsiVal < 30 ? 'buy' : (rsiVal > 70 ? 'sell' : 'neu');
      pciEls[0].className = `pci ${cls}`;
    }
    if (pciEls[2] && trend) {
      const v = pciEls[2].querySelector('.v');
      v.textContent = trend;
    }

    ['tk-rsi','tk-rsi2'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.textContent = rsi ? `${rsi}` : '—';
    });
    ['tk-trend','tk-trend2'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.textContent = trend;
    });
  } catch(e) {}
}

async function loadStats() {
  try {
    const r = await fetch('/api/stats');
    const d = await r.json();
    ['h-users','st-users','ab-users'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.textContent = (d.users || 0).toLocaleString();
    });
    ['h-signals','st-signals','ab-signals'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.textContent = (d.signals || 0).toLocaleString();
    });
  } catch(e) {}
}

async function loadSignal() {
  try {
    const r  = await fetch('/api/signal');
    const d  = await r.json();
    const loading = document.getElementById('signal-loading');
    const content = document.getElementById('signal-content');

    if (!d || !d.direction) {
      loading.innerHTML = '<div class="ns-icon">📭</div><p>لا توجد إشارة حديثة. الإشارات تُرسل خلال ساعات التداول.</p>';
      return;
    }
    loading.style.display = 'none';
    content.style.display = 'block';

    const dir = d.direction || '—';
    const dirEl = document.getElementById('sig-dir');
    dirEl.textContent = dir === 'BUY' ? '📈 شراء' : (dir === 'SELL' ? '📉 بيع' : dir);
    dirEl.className = `sig-dir ${dir}`;

    document.getElementById('sig-entry').textContent = formatNum(d.entry);
    document.getElementById('sig-tp1').textContent   = formatNum(d.tp1);
    document.getElementById('sig-tp2').textContent   = formatNum(d.tp2);
    document.getElementById('sig-tp3').textContent   = formatNum(d.tp3) || '—';
    document.getElementById('sig-sl').textContent    = formatNum(d.sl);
    document.getElementById('sig-tf').textContent    = d.timeframe || 'M15';

    const conf = d.confidence || 0;
    document.getElementById('sig-conf-bar').style.width = `${conf}%`;
    document.getElementById('sig-conf-pct').textContent = `${conf}% ثقة`;

    if (d.time) {
      const dt = new Date(d.time * 1000);
      document.getElementById('sig-time').textContent = dt.toLocaleString('ar-EG');
    }

    const sourcesEl = document.getElementById('sig-sources');
    const allSources = [
      'RSI','MACD','Bollinger','ATR','Stochastic',
      'Fibonacci','EMA','S/R','جلسة','الزخم','القمم','الاتجاه'
    ];
    const confirmed = d.confirmed_sources || [];
    sourcesEl.innerHTML = allSources.map(s => {
      const ok = confirmed.includes(s);
      return `<div class="src-badge ${ok ? 'ok' : 'na'}">${ok ? '✅' : '◯'} ${s}</div>`;
    }).join('');
  } catch(e) {
    document.getElementById('signal-loading').innerHTML = '<div class="ns-icon">📭</div><p>جاري انتظار الإشارة التالية...</p>';
  }
}

async function refreshAll() {
  await Promise.all([loadHistory(), loadStats(), loadSignal()]);
  loadPrice(); // also kick off HTTP price poll
}

// Start Binance WebSocket for sub-second real-time price
startBinanceWS();

// Initial data load
refreshAll();

// Auto-refresh intervals
setInterval(loadPrice, 5000);      // HTTP fallback every 5s
setInterval(loadHistory, 45000);   // chart history every 45s
setInterval(loadStats, 90000);     // stats every 90s
setInterval(loadSignal, 60000);    // signal every 60s

// Keep WebSocket alive check
setInterval(() => {
  if (!wsConnected && !wsReconnectTimer) startBinanceWS();
}, 10000);
</script>
</body>
</html>"""

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
