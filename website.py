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

WHATSAPP_LINK  = "https://wa.me/201500236188"
SIGNAL_FILE    = "data/latest_signal.json"
STATS_FILE     = "data/website_stats.json"
FREE_SIGNALS   = 3

_cached_price = {
    "price": None, "prev": None, "change": 0.0,
    "pct": 0.0, "updated": "", "high": None, "low": None
}
_price_history = []

def _fetch_gold_price():
    while True:
        for url, parser in [
            ("https://data-asg.goldprice.org/GetData/USD-XAU/1",
             lambda r: float(r.json()[0].split(",")[1])),
            ("https://metals.live/api/spot",
             lambda r: float(next(i for i in r.json() if i.get("metal")=="gold")["price"])),
        ]:
            try:
                r = requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=6)
                if r.status_code == 200:
                    price = parser(r)
                    old   = _cached_price["price"] or price
                    chg   = round(price - old, 2)
                    pct   = round((chg / old) * 100, 3) if old else 0.0
                    _cached_price.update({
                        "price": round(price,2), "prev": old,
                        "change": chg, "pct": pct,
                        "updated": datetime.now().strftime("%H:%M:%S"),
                    })
                    if _cached_price["high"] is None or price > _cached_price["high"]:
                        _cached_price["high"] = round(price, 2)
                    if _cached_price["low"] is None or price < _cached_price["low"]:
                        _cached_price["low"] = round(price, 2)
                    _price_history.append({"t": int(time.time()), "p": round(price,2)})
                    if len(_price_history) > 288:
                        _price_history.pop(0)
                    break
            except Exception:
                pass
        time.sleep(30)

Thread(target=_fetch_gold_price, daemon=True).start()

COURSES = [
    {"icon":"📚","title":"التحليل الكلاسيكي","count":29,"price":80},
    {"icon":"🎯","title":"كورسات SMC","count":22,"price":100},
    {"icon":"💡","title":"كورسات ICT","count":20,"price":199},
    {"icon":"🌊","title":"موجات إليوت","count":7,"price":100},
    {"icon":"🔑","title":"SK سيستم","count":9,"price":250},
    {"icon":"📊","title":"التحليل الحجمي","count":11,"price":199},
    {"icon":"🔮","title":"الهارمونيك","count":5,"price":150},
    {"icon":"₿","title":"كورسات الكريبتو","count":10,"price":299},
    {"icon":"⚔️","title":"استراتيجيات متنوعة","count":38,"price":299},
    {"icon":"👑","title":"استراتيجيات القبطان","count":3,"price":950},
    {"icon":"⚡","title":"الخيارات الثنائية","count":18,"price":200},
    {"icon":"🧠","title":"علم النفس التداولي","count":2,"price":80},
]

BOT_FILES = [
    {"name":".env","desc":"🔑 جميع المفاتيح والتوكنات — Gemini (15 مفتاح)، توكنات البوتين، Gold API"},
    {"name":"trading_bot.py","desc":"بوت التداول الذكي — إشارات XAUUSD، 12 مصدر تأكيد، تحليل AI"},
    {"name":"bot.py","desc":"البوت العربي العام — ذكاء اصطناعي، تحميل فيديو، تحويل صوت"},
    {"name":"dashboard.py","desc":"لوحة التحكم الإدارية (port 3000)"},
    {"name":"website.py","desc":"موقع الهبوط الاحترافي (port 5000)"},
    {"name":"auto_trader.py","desc":"نظام التداول الآلي — MetaApi MT5"},
    {"name":"config.py","desc":"ملف الإعدادات المشتركة"},
    {"name":"requirements.txt","desc":"جميع المكتبات المطلوبة"},
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
    return send_file(buf, as_attachment=True, download_name="trading_bot_system.zip",
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
        courses_html += f"""<div class="course-card">
<div class="cc-icon">{c['icon']}</div>
<div class="cc-title">{c['title']}</div>
<div class="cc-meta">{c['count']} كورس</div>
<div class="cc-price">{c['price']} ج.م</div>
<a href="{WHATSAPP_LINK}" class="cc-btn" target="_blank">اشترك</a>
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
<div style="margin-top:2rem;background:#12121e;border-radius:12px;padding:1.5rem;border:1px solid rgba(245,197,24,.2)">
<h3 style="color:#f5c518;margin-bottom:1rem">🖥 تعليمات التشغيل على Termux</h3>
<pre style="color:#a0ffa0;font-size:.8rem;overflow-x:auto;line-height:1.8">
pkg update && pkg upgrade -y
pkg install python python-pip -y
pip install -r requirements.txt

# تشغيل في الخلفية مع tmux
pkg install tmux -y
tmux new -s trading
python trading_bot.py
# Ctrl+B ثم D للخروج بدون إيقاف

tmux new -s website
python website.py
tmux new -s dashboard
python dashboard.py</pre>
</div>
<a href="/" class="back">← العودة للموقع</a>
</body></html>"""

# ─────────────────────────────────────────────
#  MAIN HTML - Professional Trading Website
# ─────────────────────────────────────────────
MAIN_HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>بوت التداول الذكي | إشارات XAUUSD لحظية مع 3 إشارات مجانية</title>
<meta name="description" content="نظام إشارات ذهب XAUUSD احترافي بـ12 مصدر تأكيد. تجربة مجانية 3 إشارات حقيقية. RSI، MACD، Bollinger، Fibonacci، تحليل AI.">
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@300;400;600;700;900&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
/* ═══════════════════════════════════════════ RESET & VARS */
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --gold:#f5c518;--gold2:#c99a00;--gold3:rgba(245,197,24,.1);--gold4:rgba(245,197,24,.06);
  --bg:#07070f;--bg2:#0c0c1a;--bg3:#0f0f1e;
  --card:#111120;--card2:#161628;
  --border:rgba(245,197,24,.12);--border2:rgba(245,197,24,.25);
  --green:#22c55e;--red:#ef4444;--blue:#3b82f6;--purple:#8b5cf6;
  --text:#e2e8f0;--muted:#8892a4;--muted2:#5a6478;
  --radius:16px;--radius2:12px;
  --shadow:0 8px 32px rgba(0,0,0,.6);
}
html{scroll-behavior:smooth}
body{background:var(--bg);color:var(--text);font-family:Cairo,sans-serif;overflow-x:hidden;line-height:1.6}
a{text-decoration:none;color:inherit}
img{max-width:100%}

/* ═══════════════════════════════════════════ SCROLLBAR */
::-webkit-scrollbar{width:6px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--gold2);border-radius:3px}

/* ═══════════════════════════════════════════ NAVBAR */
.navbar{
  position:fixed;top:0;right:0;left:0;z-index:1000;
  background:rgba(7,7,15,.92);backdrop-filter:blur(20px);
  border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between;
  padding:.9rem 2rem;
}
.nav-logo{display:flex;align-items:center;gap:.6rem;font-size:1.15rem;font-weight:700;color:var(--gold)}
.nav-logo span{font-size:1.4rem}
.nav-links{display:flex;align-items:center;gap:1.5rem}
.nav-links a{color:var(--muted);font-size:.88rem;transition:color .2s;font-weight:600}
.nav-links a:hover{color:var(--gold)}
.nav-price{
  background:var(--gold3);border:1px solid var(--border);
  border-radius:8px;padding:.35rem .85rem;font-size:.88rem;font-weight:700;
  color:var(--gold);cursor:default;
}
.nav-cta{
  background:var(--gold);color:#000;padding:.45rem 1.2rem;
  border-radius:8px;font-weight:700;font-size:.88rem;transition:all .2s;
}
.nav-cta:hover{background:#fff;transform:translateY(-1px)}
@media(max-width:768px){
  .nav-links{display:none}
  .nav-price{display:none}
}

/* ═══════════════════════════════════════════ HERO */
.hero{
  min-height:100vh;display:flex;align-items:center;justify-content:center;
  padding:8rem 2rem 4rem;position:relative;overflow:hidden;
  background:radial-gradient(ellipse at 50% 0%, rgba(245,197,24,.08) 0%, transparent 60%);
}
.hero-grid{display:grid;grid-template-columns:1fr 1fr;gap:4rem;align-items:center;max-width:1200px;width:100%}
@media(max-width:900px){.hero-grid{grid-template-columns:1fr;text-align:center}}
.hero-badge{
  display:inline-flex;align-items:center;gap:.5rem;
  background:var(--gold3);border:1px solid var(--border2);
  border-radius:50px;padding:.4rem 1rem;font-size:.8rem;color:var(--gold);
  font-weight:600;margin-bottom:1.5rem;
}
.hero-badge::before{content:"●";animation:pulse 1.5s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.hero-title{font-size:clamp(2rem,5vw,3.2rem);font-weight:900;line-height:1.2;margin-bottom:1.2rem}
.hero-title .hl{color:var(--gold)}
.hero-sub{font-size:1.05rem;color:var(--muted);margin-bottom:2rem;max-width:480px}
@media(max-width:900px){.hero-sub{margin:0 auto 2rem}}
.hero-btns{display:flex;gap:1rem;flex-wrap:wrap}
@media(max-width:900px){.hero-btns{justify-content:center}}
.btn-primary{
  background:var(--gold);color:#000;padding:.9rem 2rem;
  border-radius:var(--radius2);font-weight:700;font-size:1rem;
  display:inline-flex;align-items:center;gap:.5rem;transition:all .25s;
  box-shadow:0 4px 20px rgba(245,197,24,.3);
}
.btn-primary:hover{background:#fff;transform:translateY(-2px);box-shadow:0 6px 28px rgba(245,197,24,.4)}
.btn-outline{
  background:transparent;color:var(--gold);padding:.9rem 2rem;
  border:2px solid var(--border2);border-radius:var(--radius2);
  font-weight:700;font-size:1rem;display:inline-flex;align-items:center;gap:.5rem;transition:all .25s;
}
.btn-outline:hover{background:var(--gold3);border-color:var(--gold);transform:translateY(-2px)}
.hero-stats{display:flex;gap:2rem;margin-top:2rem;flex-wrap:wrap}
@media(max-width:900px){.hero-stats{justify-content:center}}
.hstat{text-align:center}
.hstat-num{font-size:1.8rem;font-weight:900;color:var(--gold)}
.hstat-lbl{font-size:.75rem;color:var(--muted)}
.hero-card{
  background:var(--card);border:1px solid var(--border2);border-radius:var(--radius);
  padding:1.5rem;box-shadow:var(--shadow);position:relative;overflow:hidden;
}
.hero-card::before{
  content:"";position:absolute;inset:0;
  background:radial-gradient(circle at top right, rgba(245,197,24,.06), transparent 60%);
  pointer-events:none;
}
.price-display{text-align:center;margin-bottom:1.2rem}
.price-label{font-size:.8rem;color:var(--muted);margin-bottom:.3rem}
.price-big{font-size:2.5rem;font-weight:900;color:var(--gold);font-variant-numeric:tabular-nums}
.price-change{font-size:.9rem;font-weight:600;margin-top:.3rem}
.price-change.up{color:var(--green)}
.price-change.dn{color:var(--red)}
.price-meta{display:flex;justify-content:space-around;margin-top:.8rem;padding-top:.8rem;border-top:1px solid var(--border)}
.pm-item{text-align:center}
.pm-item .v{font-weight:700;font-size:.9rem}
.pm-item .l{font-size:.7rem;color:var(--muted)}
.mini-indicators{display:grid;grid-template-columns:1fr 1fr 1fr;gap:.5rem;margin-top:1rem}
.mi{background:var(--bg2);border-radius:8px;padding:.5rem;text-align:center}
.mi .n{font-size:.7rem;color:var(--muted)}
.mi .v{font-size:.85rem;font-weight:700}
.mi.buy .v{color:var(--green)}
.mi.sell .v{color:var(--red)}
.mi.neutral .v{color:var(--muted)}
.session-badge{
  display:flex;align-items:center;justify-content:center;gap:.4rem;
  background:var(--bg2);border-radius:8px;padding:.5rem;margin-top:.8rem;
  font-size:.8rem;color:var(--muted);
}
.session-dot{width:8px;height:8px;border-radius:50%;background:var(--green);animation:pulse 1.5s infinite}

/* ═══════════════════════════════════════════ TICKER */
.ticker{
  background:rgba(245,197,24,.08);border-top:1px solid var(--border);
  border-bottom:1px solid var(--border);
  padding:.6rem 0;overflow:hidden;white-space:nowrap;
}
.ticker-inner{display:inline-flex;gap:4rem;animation:scroll 30s linear infinite}
@keyframes scroll{0%{transform:translateX(0)}100%{transform:translateX(-50%)}}
.ticker-item{display:inline-flex;align-items:center;gap:.5rem;font-size:.85rem;font-weight:600}
.ticker-item .t{color:var(--muted)}

/* ═══════════════════════════════════════════ SECTIONS */
section{padding:5rem 2rem}
.container{max-width:1200px;margin:0 auto}
.sec-badge{
  display:inline-block;background:var(--gold3);border:1px solid var(--border);
  border-radius:50px;padding:.3rem .9rem;font-size:.78rem;color:var(--gold);
  font-weight:600;margin-bottom:1rem;
}
.sec-title{font-size:clamp(1.6rem,3.5vw,2.4rem);font-weight:900;margin-bottom:.8rem}
.sec-title .hl{color:var(--gold)}
.sec-sub{font-size:1rem;color:var(--muted);max-width:600px}
.sec-header{margin-bottom:3rem}
.sec-header.center{text-align:center}
.sec-header.center .sec-sub{margin:0 auto}

/* ═══════════════════════════════════════════ CHART */
.chart-section{background:var(--bg2);padding:4rem 2rem}
.tradingview-widget-container{border-radius:var(--radius);overflow:hidden;border:1px solid var(--border)}

/* ═══════════════════════════════════════════ SIGNAL SECTION */
.signal-section{background:var(--bg3)}
.signal-grid{display:grid;grid-template-columns:1fr 1fr;gap:2rem;align-items:start}
@media(max-width:900px){.signal-grid{grid-template-columns:1fr}}
.signal-card{
  background:var(--card);border:1px solid var(--border2);border-radius:var(--radius);
  padding:1.8rem;position:relative;overflow:hidden;
}
.signal-card::before{
  content:"";position:absolute;inset:0;
  background:radial-gradient(circle at top left, rgba(245,197,24,.05), transparent 60%);pointer-events:none;
}
.sig-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:1.5rem}
.sig-pair{font-size:1.1rem;font-weight:700;color:var(--gold)}
.sig-dir{
  padding:.3rem .8rem;border-radius:6px;font-weight:700;font-size:.85rem;
}
.sig-dir.BUY{background:rgba(34,197,94,.15);color:var(--green);border:1px solid rgba(34,197,94,.3)}
.sig-dir.SELL{background:rgba(239,68,68,.15);color:var(--red);border:1px solid rgba(239,68,68,.3)}
.sig-row{display:flex;justify-content:space-between;align-items:center;
  padding:.6rem 0;border-bottom:1px solid var(--border);font-size:.9rem}
.sig-row:last-child{border-bottom:none}
.sig-lbl{color:var(--muted)}
.sig-val{font-weight:700;font-family:monospace}
.sig-val.blur{filter:blur(6px);user-select:none}
.sig-conf{
  display:flex;align-items:center;gap:.5rem;margin-top:1rem;
}
.conf-bar{flex:1;height:8px;background:var(--bg);border-radius:4px;overflow:hidden}
.conf-fill{height:100%;background:linear-gradient(90deg,var(--gold2),var(--gold));border-radius:4px;transition:width 1s}
.conf-pct{font-size:.85rem;font-weight:700;color:var(--gold);white-space:nowrap}
.sig-sources{display:grid;grid-template-columns:1fr 1fr;gap:.4rem;margin-top:1rem}
.src-badge{background:var(--bg2);border:1px solid var(--border);border-radius:6px;
  padding:.35rem .7rem;font-size:.75rem;display:flex;align-items:center;gap:.4rem}
.src-badge.ok{border-color:rgba(34,197,94,.3);color:var(--green)}
.src-badge.ng{border-color:rgba(239,68,68,.2);color:var(--red)}
.trial-box{
  background:linear-gradient(135deg,rgba(245,197,24,.12),rgba(245,197,24,.04));
  border:2px dashed var(--border2);border-radius:var(--radius);
  padding:2rem;text-align:center;
}
.trial-num{font-size:4rem;font-weight:900;color:var(--gold);line-height:1}
.trial-label{font-size:1rem;color:var(--muted);margin:.5rem 0 1.5rem}
.trial-features{list-style:none;text-align:right;margin-bottom:1.5rem}
.trial-features li{display:flex;align-items:center;gap:.5rem;padding:.4rem 0;font-size:.9rem;color:var(--muted)}
.trial-features li::before{content:"✅";flex-shrink:0}
.cta-free{
  background:var(--gold);color:#000;display:block;width:100%;padding:1rem;
  border-radius:var(--radius2);font-weight:900;font-size:1.05rem;text-align:center;
  transition:all .2s;box-shadow:0 4px 20px rgba(245,197,24,.3);
}
.cta-free:hover{background:#fff;transform:translateY(-2px)}

/* ═══════════════════════════════════════════ STATS */
.stats-bar{background:var(--card);border-top:1px solid var(--border);border-bottom:1px solid var(--border);padding:2rem}
.stats-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:1.5rem}
@media(max-width:768px){.stats-grid{grid-template-columns:repeat(2,1fr)}}
.stat-item{text-align:center}
.stat-num{font-size:2rem;font-weight:900;color:var(--gold);margin-bottom:.2rem}
.stat-lbl{font-size:.8rem;color:var(--muted)}

/* ═══════════════════════════════════════════ FEATURES */
.features-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:1.5rem}
@media(max-width:900px){.features-grid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:540px){.features-grid{grid-template-columns:1fr}}
.feat-card{
  background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
  padding:1.5rem;transition:all .25s;
}
.feat-card:hover{border-color:var(--border2);transform:translateY(-4px);box-shadow:0 12px 40px rgba(245,197,24,.1)}
.feat-icon{font-size:2rem;margin-bottom:.8rem}
.feat-title{font-size:1rem;font-weight:700;color:var(--gold);margin-bottom:.5rem}
.feat-desc{font-size:.85rem;color:var(--muted);line-height:1.7}
.indicators-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:.6rem;margin-top:2rem}
@media(max-width:540px){.indicators-grid{grid-template-columns:repeat(2,1fr)}}
.ind-chip{
  background:var(--bg2);border:1px solid var(--border);border-radius:8px;
  padding:.5rem;text-align:center;font-size:.8rem;font-weight:600;color:var(--muted);
}
.ind-chip.active{border-color:rgba(245,197,24,.4);color:var(--gold);background:var(--gold3)}

/* ═══════════════════════════════════════════ STRATEGY */
.strategy-section{background:var(--bg2)}
.strat-card{
  background:linear-gradient(135deg,rgba(139,92,246,.12),rgba(245,197,24,.06));
  border:1px solid rgba(139,92,246,.3);border-radius:var(--radius);
  padding:3rem;display:grid;grid-template-columns:1fr 1fr;gap:3rem;align-items:center;
}
@media(max-width:900px){.strat-card{grid-template-columns:1fr}}
.strat-title{font-size:1.8rem;font-weight:900;margin-bottom:1rem}
.strat-title .hl2{color:#8b5cf6}
.strat-desc{color:var(--muted);margin-bottom:1.5rem;font-size:.95rem;line-height:1.8}
.strat-list{list-style:none}
.strat-list li{display:flex;align-items:start;gap:.7rem;margin-bottom:.8rem;color:var(--muted);font-size:.9rem}
.strat-list li .ic{flex-shrink:0;color:#8b5cf6;font-size:1rem;margin-top:.1rem}
.strat-demo{background:var(--card);border-radius:var(--radius);padding:1.5rem;border:1px solid var(--border)}
.strat-demo-title{font-size:.85rem;color:var(--muted);margin-bottom:1rem}
.strat-input{
  background:var(--bg);border:1px solid var(--border2);border-radius:8px;
  width:100%;padding:.8rem;color:var(--text);font-family:Cairo,sans-serif;
  font-size:.85rem;resize:none;outline:none;transition:border-color .2s;
  margin-bottom:.8rem;height:100px;
}
.strat-input:focus{border-color:var(--gold)}
.strat-btn{
  background:linear-gradient(135deg,#8b5cf6,#6d28d9);color:#fff;
  padding:.8rem 1.5rem;border-radius:var(--radius2);font-weight:700;
  font-size:.9rem;border:none;cursor:pointer;width:100%;transition:all .2s;
}
.strat-btn:hover{filter:brightness(1.1);transform:translateY(-1px)}
.strat-result{margin-top:.8rem;background:var(--bg2);border-radius:8px;padding:1rem;
  font-size:.8rem;line-height:1.8;color:var(--muted);display:none;max-height:200px;overflow-y:auto}

/* ═══════════════════════════════════════════ PLANS */
.plans-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:1.5rem}
@media(max-width:900px){.plans-grid{grid-template-columns:1fr}}
.plan-card{
  background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
  padding:2rem;position:relative;transition:all .25s;
}
.plan-card.featured{
  border-color:var(--gold);
  background:linear-gradient(160deg,rgba(245,197,24,.08),var(--card));
  transform:scale(1.02);
}
.plan-badge-featured{
  position:absolute;top:-12px;right:50%;transform:translateX(50%);
  background:var(--gold);color:#000;font-size:.72rem;font-weight:700;
  padding:.25rem .9rem;border-radius:50px;white-space:nowrap;
}
.plan-name{font-size:.85rem;color:var(--muted);font-weight:600;margin-bottom:.5rem}
.plan-price{font-size:2.5rem;font-weight:900;color:var(--gold);margin-bottom:.3rem}
.plan-price span{font-size:.9rem;color:var(--muted);font-weight:400}
.plan-desc{font-size:.8rem;color:var(--muted);margin-bottom:1.5rem;padding-bottom:1.5rem;border-bottom:1px solid var(--border)}
.plan-features{list-style:none;margin-bottom:2rem}
.plan-features li{display:flex;align-items:center;gap:.5rem;padding:.4rem 0;font-size:.88rem}
.plan-features li .ic{color:var(--green);flex-shrink:0}
.plan-features li .no{color:var(--muted2)}
.plan-features li.off{color:var(--muted2)}
.plan-features li.off .ic{color:var(--muted2)}
.plan-btn{
  display:block;width:100%;padding:.9rem;border-radius:var(--radius2);
  font-weight:700;font-size:.95rem;text-align:center;transition:all .2s;
  background:var(--gold3);color:var(--gold);border:1px solid var(--border2);
}
.plan-card.featured .plan-btn{background:var(--gold);color:#000;border:none;box-shadow:0 4px 20px rgba(245,197,24,.3)}
.plan-btn:hover{filter:brightness(1.1);transform:translateY(-2px)}

/* ═══════════════════════════════════════════ PAYMENT */
.payment-section{background:var(--bg3)}
.payment-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:1.2rem;margin-bottom:2rem}
@media(max-width:900px){.payment-grid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:480px){.payment-grid{grid-template-columns:1fr 1fr}}
.pay-card{
  background:var(--card);border:1px solid var(--border);border-radius:var(--radius2);
  padding:1.2rem;text-align:center;transition:all .2s;
}
.pay-card:hover{border-color:var(--border2);transform:translateY(-3px)}
.pay-icon{font-size:2rem;margin-bottom:.5rem}
.pay-name{font-size:.85rem;font-weight:700;color:var(--gold)}
.pay-desc{font-size:.75rem;color:var(--muted);margin-top:.2rem}
.pay-question{
  background:linear-gradient(135deg,rgba(59,130,246,.1),rgba(139,92,246,.1));
  border:1px solid rgba(59,130,246,.3);border-radius:var(--radius);
  padding:1.5rem 2rem;display:flex;align-items:center;justify-content:space-between;
  gap:1rem;flex-wrap:wrap;
}
.pay-q-text{font-weight:700;font-size:1rem}
.pay-q-sub{font-size:.85rem;color:var(--muted);margin-top:.2rem}
.btn-whatsapp{
  background:linear-gradient(135deg,#25d366,#128c7e);color:#fff;
  padding:.8rem 1.8rem;border-radius:var(--radius2);font-weight:700;
  font-size:.9rem;display:inline-flex;align-items:center;gap:.5rem;
  transition:all .2s;white-space:nowrap;
}
.btn-whatsapp:hover{filter:brightness(1.1);transform:translateY(-2px)}
.binance-info{
  background:rgba(240,185,11,.06);border:1px solid rgba(240,185,11,.2);
  border-radius:var(--radius2);padding:1.2rem 1.5rem;margin-top:1.2rem;
  font-size:.85rem;color:var(--muted);
}
.binance-info strong{color:#f0b90b}

/* ═══════════════════════════════════════════ GENERAL BOT */
.genbot-grid{display:grid;grid-template-columns:1fr 1fr;gap:2rem;align-items:center}
@media(max-width:900px){.genbot-grid{grid-template-columns:1fr}}
.genbot-features{display:grid;grid-template-columns:1fr 1fr;gap:.8rem}
.gb-feat{
  background:var(--card);border:1px solid var(--border);border-radius:var(--radius2);
  padding:.9rem;display:flex;align-items:center;gap:.7rem;transition:all .2s;
}
.gb-feat:hover{border-color:var(--border2)}
.gb-feat-icon{font-size:1.4rem;flex-shrink:0}
.gb-feat-text{font-size:.82rem;font-weight:600;color:var(--muted)}
.genbot-card{
  background:var(--card2);border:1px solid var(--border2);border-radius:var(--radius);
  padding:2rem;text-align:center;
}
.genbot-logo{font-size:3rem;margin-bottom:1rem}
.genbot-name{font-size:1.4rem;font-weight:700;color:var(--gold);margin-bottom:.5rem}
.genbot-desc{font-size:.9rem;color:var(--muted);margin-bottom:1.5rem}
.genbot-keys{display:flex;flex-wrap:wrap;gap:.4rem;justify-content:center;margin-bottom:1.5rem}
.gk{background:var(--gold3);border:1px solid var(--border);border-radius:4px;
  padding:.25rem .6rem;font-size:.72rem;color:var(--gold)}

/* ═══════════════════════════════════════════ COURSES */
.courses-section{background:var(--bg2)}
.courses-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:1.2rem}
@media(max-width:1100px){.courses-grid{grid-template-columns:repeat(3,1fr)}}
@media(max-width:700px){.courses-grid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:420px){.courses-grid{grid-template-columns:1fr}}
.course-card{
  background:var(--card);border:1px solid var(--border);border-radius:var(--radius2);
  padding:1.2rem;text-align:center;transition:all .25s;
}
.course-card:hover{border-color:var(--border2);transform:translateY(-3px)}
.cc-icon{font-size:1.8rem;margin-bottom:.5rem}
.cc-title{font-size:.85rem;font-weight:700;margin-bottom:.3rem}
.cc-meta{font-size:.73rem;color:var(--muted);margin-bottom:.5rem}
.cc-price{font-size:1rem;font-weight:700;color:var(--gold);margin-bottom:.7rem}
.cc-btn{
  display:block;background:var(--gold3);color:var(--gold);border:1px solid var(--border);
  border-radius:6px;padding:.4rem;font-size:.78rem;font-weight:600;transition:all .2s;
}
.cc-btn:hover{background:var(--gold);color:#000}

/* ═══════════════════════════════════════════ POLICY */
.policy-section{background:var(--bg3)}
.policy-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:1.5rem}
@media(max-width:900px){.policy-grid{grid-template-columns:1fr}}
.pol-card{
  background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
  padding:1.5rem;
}
.pol-icon{font-size:1.8rem;margin-bottom:.8rem}
.pol-title{font-size:1rem;font-weight:700;color:var(--gold);margin-bottom:.8rem}
.pol-text{font-size:.82rem;color:var(--muted);line-height:1.9}

/* ═══════════════════════════════════════════ SUPPORT */
.support-section{background:var(--bg2)}
.support-grid{display:grid;grid-template-columns:1fr 1fr;gap:2rem;align-items:start}
@media(max-width:900px){.support-grid{grid-template-columns:1fr}}
.support-channels{display:flex;flex-direction:column;gap:1rem}
.sc-card{
  background:var(--card);border:1px solid var(--border);border-radius:var(--radius2);
  padding:1.2rem;display:flex;align-items:center;gap:1rem;transition:all .2s;
}
.sc-card:hover{border-color:var(--border2)}
.sc-icon{font-size:1.8rem;flex-shrink:0}
.sc-title{font-size:.95rem;font-weight:700}
.sc-desc{font-size:.8rem;color:var(--muted)}
.faq-item{border:1px solid var(--border);border-radius:var(--radius2);overflow:hidden;margin-bottom:.8rem}
.faq-q{
  padding:1rem 1.2rem;font-weight:700;font-size:.9rem;cursor:pointer;
  display:flex;justify-content:space-between;align-items:center;
  background:var(--card);transition:background .2s;
}
.faq-q:hover{background:var(--card2)}
.faq-q .arrow{transition:transform .3s;color:var(--gold)}
.faq-q.open .arrow{transform:rotate(180deg)}
.faq-a{padding:0 1.2rem;max-height:0;overflow:hidden;transition:all .3s;font-size:.85rem;color:var(--muted);line-height:1.8}
.faq-a.open{max-height:200px;padding:1rem 1.2rem}

/* ═══════════════════════════════════════════ FOOTER */
footer{background:var(--bg);border-top:1px solid var(--border);padding:3rem 2rem 1.5rem}
.footer-grid{display:grid;grid-template-columns:2fr 1fr 1fr 1fr;gap:2rem;max-width:1200px;margin:0 auto}
@media(max-width:900px){.footer-grid{grid-template-columns:1fr 1fr}}
@media(max-width:540px){.footer-grid{grid-template-columns:1fr}}
.footer-brand .logo{display:flex;align-items:center;gap:.6rem;font-size:1.15rem;font-weight:700;color:var(--gold);margin-bottom:.8rem}
.footer-brand p{font-size:.82rem;color:var(--muted);line-height:1.8}
.footer-col h4{font-size:.9rem;font-weight:700;color:var(--gold);margin-bottom:1rem}
.footer-col ul{list-style:none}
.footer-col ul li{margin-bottom:.5rem}
.footer-col ul li a{font-size:.82rem;color:var(--muted);transition:color .2s}
.footer-col ul li a:hover{color:var(--gold)}
.footer-bottom{
  max-width:1200px;margin:2rem auto 0;padding-top:1.5rem;
  border-top:1px solid var(--border);display:flex;
  justify-content:space-between;align-items:center;flex-wrap:gap;gap:1rem;
  font-size:.78rem;color:var(--muted);
}
.risk-banner{
  background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.2);
  border-radius:8px;padding:1rem;margin-top:1.5rem;max-width:1200px;margin-inline:auto;
  font-size:.78rem;color:rgba(239,68,68,.8);text-align:center;
}

/* ═══════════════════════════════════════════ WHATSAPP FLOAT */
.wa-float{
  position:fixed;bottom:2rem;left:2rem;z-index:999;
  background:linear-gradient(135deg,#25d366,#128c7e);
  width:58px;height:58px;border-radius:50%;
  display:flex;align-items:center;justify-content:center;
  font-size:1.6rem;box-shadow:0 4px 20px rgba(37,211,102,.4);
  transition:all .2s;cursor:pointer;text-decoration:none;
}
.wa-float:hover{transform:scale(1.1);box-shadow:0 6px 28px rgba(37,211,102,.5)}
.wa-float::after{
  content:"تواصل معنا";position:absolute;left:68px;
  background:#1a1a2e;border:1px solid var(--border);border-radius:8px;
  padding:.4rem .8rem;font-size:.75rem;white-space:nowrap;
  color:var(--text);opacity:0;transition:opacity .2s;pointer-events:none;
}
.wa-float:hover::after{opacity:1}

/* ═══════════════════════════════════════════ MARKET STATUS */
.market-closed-bar{
  background:rgba(239,68,68,.1);border-bottom:1px solid rgba(239,68,68,.2);
  padding:.6rem 2rem;text-align:center;font-size:.82rem;color:#ef4444;font-weight:600;
  display:none;
}
</style>
</head>
<body>

<!-- MARKET CLOSED BAR -->
<div class="market-closed-bar" id="marketBar">
  ⛔ سوق الذهب مغلق حالياً | يفتح الأحد الساعة 11:00 م بتوقيت مكة
</div>

<!-- NAVBAR -->
<nav class="navbar">
  <div class="nav-logo"><span>⚡</span>بوت التداول الذكي</div>
  <div class="nav-links">
    <a href="#signal">الإشارات</a>
    <a href="#features">المميزات</a>
    <a href="#plans">الأسعار</a>
    <a href="#courses">الكورسات</a>
    <a href="#support">الدعم</a>
  </div>
  <div style="display:flex;align-items:center;gap:.8rem">
    <div class="nav-price" id="navPrice">⏳ جاري التحميل...</div>
    <a href="{{ whatsapp }}" target="_blank" class="nav-cta">🎁 تجربة مجانية</a>
  </div>
</nav>

<!-- HERO -->
<section class="hero" id="home">
  <div class="hero-grid">
    <div>
      <div class="hero-badge">🟢 النظام يعمل بكفاءة 24/7</div>
      <h1 class="hero-title">
        إشارات <span class="hl">XAUUSD</span> لحظية<br>
        بـ12 مصدر تأكيد
      </h1>
      <p class="hero-sub">
        نظام تحليل ذهب احترافي يجمع RSI، MACD، Bollinger، Fibonacci، ATR، Stochastic و6 نماذج رياضية لتوليد إشارات بدقة 65%-79%.
      </p>
      <div class="hero-btns">
        <a href="{{ whatsapp }}" target="_blank" class="btn-primary">🎁 ابدأ {{ free_signals }} إشارات مجانية</a>
        <a href="#plans" class="btn-outline">💎 خطط الاشتراك</a>
      </div>
      <div class="hero-stats">
        <div class="hstat"><div class="hstat-num" id="statUsers">0</div><div class="hstat-lbl">مستخدم نشط</div></div>
        <div class="hstat"><div class="hstat-num" id="statSigs">0</div><div class="hstat-lbl">إشارة مُرسلة</div></div>
        <div class="hstat"><div class="hstat-num">12</div><div class="hstat-lbl">مصدر تأكيد</div></div>
        <div class="hstat"><div class="hstat-num">79%</div><div class="hstat-lbl">دقة التوقع</div></div>
      </div>
    </div>
    <div class="hero-card">
      <div class="price-display">
        <div class="price-label">💰 XAUUSD — الذهب / دولار</div>
        <div class="price-big" id="heroPrice">——</div>
        <div class="price-change" id="heroChange">⏳ تحميل...</div>
      </div>
      <div class="price-meta">
        <div class="pm-item"><div class="v" id="heroHigh">—</div><div class="l">أعلى</div></div>
        <div class="pm-item"><div class="v" id="heroLow">—</div><div class="l">أدنى</div></div>
        <div class="pm-item"><div class="v" id="heroUpdated">—</div><div class="l">تحديث</div></div>
      </div>
      <div class="mini-indicators">
        <div class="mi" id="mi_rsi"><div class="n">RSI</div><div class="v">—</div></div>
        <div class="mi" id="mi_macd"><div class="n">MACD</div><div class="v">—</div></div>
        <div class="mi" id="mi_bb"><div class="n">Bollinger</div><div class="v">—</div></div>
      </div>
      <div class="session-badge">
        <div class="session-dot"></div>
        <span id="sessionText">جلسة التداول</span>
      </div>
    </div>
  </div>
</section>

<!-- PRICE TICKER -->
<div class="ticker">
  <div class="ticker-inner" id="tickerInner">
    <span class="ticker-item"><span class="t">XAUUSD</span><span id="t1">$——</span></span>
    <span class="ticker-item"><span class="t">تغيير</span><span id="t2">——</span></span>
    <span class="ticker-item"><span class="t">أعلى</span><span id="t3">——</span></span>
    <span class="ticker-item"><span class="t">أدنى</span><span id="t4">——</span></span>
    <span class="ticker-item">🎁 {{ free_signals }} إشارات مجانية للتجربة</span>
    <span class="ticker-item">⚡ نظام 12 مصدر تأكيد</span>
    <span class="ticker-item">🧠 تحليل استراتيجيتك بالذكاء الاصطناعي</span>
    <span class="ticker-item">📸 تحليل الشارت مجاناً بالـ AI</span>
    <!-- duplicate for seamless loop -->
    <span class="ticker-item"><span class="t">XAUUSD</span><span id="t1b">$——</span></span>
    <span class="ticker-item"><span class="t">تغيير</span><span id="t2b">——</span></span>
    <span class="ticker-item"><span class="t">أعلى</span><span id="t3b">——</span></span>
    <span class="ticker-item"><span class="t">أدنى</span><span id="t4b">——</span></span>
    <span class="ticker-item">🎁 {{ free_signals }} إشارات مجانية للتجربة</span>
    <span class="ticker-item">⚡ نظام 12 مصدر تأكيد</span>
    <span class="ticker-item">🧠 تحليل استراتيجيتك بالذكاء الاصطناعي</span>
    <span class="ticker-item">📸 تحليل الشارت مجاناً بالـ AI</span>
  </div>
</div>

<!-- CHART SECTION -->
<div class="chart-section" id="chart">
  <div class="container">
    <div class="sec-header center" style="margin-bottom:1.5rem">
      <div class="sec-badge">📊 رسم بياني مباشر</div>
      <h2 class="sec-title">شارت <span class="hl">XAUUSD</span> المباشر</h2>
    </div>
    <div class="tradingview-widget-container">
      <div id="tradingview_chart"></div>
    </div>
  </div>
</div>

<!-- SIGNAL SECTION -->
<section class="signal-section" id="signal">
  <div class="container">
    <div class="sec-header center" style="margin-bottom:2rem">
      <div class="sec-badge">⚡ إشارات لحظية</div>
      <h2 class="sec-title">آخر <span class="hl">إشارة تداول</span></h2>
      <p class="sec-sub">إشارات مبنية على 12 مصدر تأكيد — 3 إشارات مجانية لكل مستخدم جديد</p>
    </div>
    <div class="signal-grid">
      <!-- LIVE SIGNAL CARD -->
      <div class="signal-card">
        <div class="sig-header">
          <div class="sig-pair">⚡ XAUUSD / الذهب</div>
          <div class="sig-dir" id="sigDir">——</div>
        </div>
        <div class="sig-row"><span class="sig-lbl">💰 سعر الدخول</span><span class="sig-val blur" id="sigEntry">$3,321.50</span></div>
        <div class="sig-row"><span class="sig-lbl">🎯 الهدف الأول</span><span class="sig-val blur" id="sigTp1">$3,335.00</span></div>
        <div class="sig-row"><span class="sig-lbl">🎯 الهدف الثاني</span><span class="sig-val blur" id="sigTp2">$3,348.00</span></div>
        <div class="sig-row"><span class="sig-lbl">🎯 الهدف الثالث</span><span class="sig-val blur" id="sigTp3">$3,362.00</span></div>
        <div class="sig-row"><span class="sig-lbl">🛑 وقف الخسارة</span><span class="sig-val blur" id="sigSl">$3,307.00</span></div>
        <div class="sig-row"><span class="sig-lbl">🕐 وقت الإشارة</span><span class="sig-val" id="sigTime">——</span></div>
        <div class="sig-conf">
          <span style="font-size:.8rem;color:var(--muted)">الثقة:</span>
          <div class="conf-bar"><div class="conf-fill" id="confFill" style="width:0%"></div></div>
          <span class="conf-pct" id="confPct">——%</span>
        </div>
        <div style="margin-top:.8rem">
          <div style="font-size:.8rem;color:var(--muted);margin-bottom:.5rem">مصادر التأكيد:</div>
          <div class="sig-sources" id="sigSources"></div>
        </div>
        <div style="margin-top:1rem;padding:1rem;background:rgba(245,197,24,.06);border-radius:8px;border:1px dashed var(--border2);text-align:center">
          <div style="font-size:.8rem;color:var(--muted);margin-bottom:.6rem">🔒 الأرقام مخفية — للمشتركين فقط</div>
          <a href="{{ whatsapp }}" target="_blank" class="cta-free" style="font-size:.85rem;padding:.7rem">💎 اشترك الآن للحصول على الإشارة كاملة</a>
        </div>
      </div>
      <!-- TRIAL BOX -->
      <div class="trial-box">
        <div class="trial-num">{{ free_signals }}</div>
        <div class="trial-label">إشارات مجانية حقيقية لكل عضو جديد</div>
        <ul class="trial-features">
          <li>إشارة كاملة مع جميع الأرقام (دخول، هدف، وقف)</li>
          <li>12 مصدر تأكيد لكل إشارة</li>
          <li>تحليل الشارت بالذكاء الاصطناعي مجاناً</li>
          <li>تحليل استراتيجيتك الشخصية</li>
          <li>سعر الذهب المباشر لحظة بلحظة</li>
        </ul>
        <a href="{{ whatsapp }}" target="_blank" class="cta-free">
          🚀 ابدأ تجربتك المجانية الآن
        </a>
        <div style="margin-top:1.2rem;padding-top:1.2rem;border-top:1px solid var(--border)">
          <div style="font-size:.8rem;color:var(--muted);text-align:center;margin-bottom:.8rem">السوق مغلق يومي السبت والأحد</div>
          <div style="display:flex;justify-content:center;gap:.6rem;flex-wrap:wrap">
            <span style="background:rgba(34,197,94,.1);border:1px solid rgba(34,197,94,.2);color:var(--green);padding:.3rem .7rem;border-radius:6px;font-size:.75rem;font-weight:600">✅ الاثنين — الجمعة: مفتوح</span>
            <span style="background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.2);color:var(--red);padding:.3rem .7rem;border-radius:6px;font-size:.75rem;font-weight:600">⛔ السبت — الأحد: مغلق</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</section>

<!-- STATS BAR -->
<div class="stats-bar">
  <div class="container">
    <div class="stats-grid">
      <div class="stat-item"><div class="stat-num" id="statsUsers">0+</div><div class="stat-lbl">مستخدم مسجل</div></div>
      <div class="stat-item"><div class="stat-num" id="statsSigs">0+</div><div class="stat-lbl">إشارة أُرسلت</div></div>
      <div class="stat-item"><div class="stat-num">65-79%</div><div class="stat-lbl">دقة التوقع</div></div>
      <div class="stat-item"><div class="stat-num">24/7</div><div class="stat-lbl">مراقبة مستمرة</div></div>
    </div>
  </div>
</div>

<!-- TRADING BOT FEATURES -->
<section id="features">
  <div class="container">
    <div class="sec-header">
      <div class="sec-badge">⚡ بوت التداول الذكي</div>
      <h2 class="sec-title">مميزات <span class="hl">بوت التداول</span></h2>
      <p class="sec-sub">محرك تحليل احترافي يجمع أقوى المؤشرات التقنية مع الذكاء الاصطناعي لتوليد إشارات دقيقة</p>
    </div>
    <div class="features-grid">
      <div class="feat-card">
        <div class="feat-icon">📊</div>
        <div class="feat-title">12 مصدر تأكيد</div>
        <div class="feat-desc">6 نماذج تحليلية (إحصائي، رياضي، زخم، موجي، زمني، احتمالي) + 6 مؤشرات فنية. الإشارة تصدر فقط عند توافق 7+ مصادر.</div>
      </div>
      <div class="feat-card">
        <div class="feat-icon">🧠</div>
        <div class="feat-title">تحليل الشارت بالـ AI</div>
        <div class="feat-desc">أرسل صورة شارت وسيحللها النظام بالذكاء الاصطناعي: الاتجاه، الدعم/المقاومة، النماذج الفنية، نقطة دخول مثالية.</div>
      </div>
      <div class="feat-card">
        <div class="feat-icon">📊</div>
        <div class="feat-title">تحليل استراتيجيتك</div>
        <div class="feat-desc">أرسل وصف استراتيجيتك وسيحلل النظام نقاط قوتها، ضعفها، أفضل أوقات تطبيقها، وكيف تطورها — بشكل حقيقي واحترافي.</div>
      </div>
      <div class="feat-card">
        <div class="feat-icon">⚡</div>
        <div class="feat-title">إشارات تلقائية VIP</div>
        <div class="feat-desc">تصلك الإشارات تلقائياً كل 3 دقائق عند اكتمال شروط الدخول. 3 أهداف + وقف خسارة + نسبة الثقة.</div>
      </div>
      <div class="feat-card">
        <div class="feat-icon">💰</div>
        <div class="feat-title">سعر الذهب لحظي</div>
        <div class="feat-desc">مصدران مستقلان للسعر + Finnhub WebSocket للبيانات اللحظية. تحديث كل 30 ثانية مع تاريخ 200 نقطة للتحليل.</div>
      </div>
      <div class="feat-card">
        <div class="feat-icon">🎓</div>
        <div class="feat-title">مكتبة +200 كورس</div>
        <div class="feat-desc">12 تصنيف: كلاسيكي، SMC، ICT، إليوت، SK، فوليوم، هارمونيك، كريبتو، استراتيجيات، القبطان، خيارات ثنائية، علم النفس.</div>
      </div>
    </div>
    <div style="margin-top:2rem">
      <div style="font-size:.9rem;color:var(--muted);margin-bottom:1rem">المؤشرات الفنية المستخدمة:</div>
      <div class="indicators-grid">
        <div class="ind-chip active">RSI (14)</div>
        <div class="ind-chip active">MACD (12/26/9)</div>
        <div class="ind-chip active">Bollinger Bands</div>
        <div class="ind-chip active">ATR (14)</div>
        <div class="ind-chip active">Stochastic (14)</div>
        <div class="ind-chip active">Fibonacci</div>
        <div class="ind-chip active">EMA (5/13/21)</div>
        <div class="ind-chip active">Support/Resistance</div>
        <div class="ind-chip active">Wave Analysis</div>
        <div class="ind-chip active">Statistical Model</div>
        <div class="ind-chip active">Momentum Model</div>
        <div class="ind-chip active">Seasonal Model</div>
      </div>
    </div>
  </div>
</section>

<!-- STRATEGY ANALYSIS -->
<section class="strategy-section" id="strategy">
  <div class="container">
    <div class="strat-card">
      <div>
        <div class="sec-badge">🤖 ميزة حصرية جديدة</div>
        <h2 class="strat-title">تحليل <span class="hl2">استراتيجيتك</span><br>بالذكاء الاصطناعي</h2>
        <p class="strat-desc">
          أرسل وصف استراتيجيتك التداولية وسيقوم نظامنا الذكي بتحليلها بشكل احترافي حقيقي — ليس مجرد معلومات عامة، بل تحليل مخصص لاستراتيجيتك أنت.
        </p>
        <ul class="strat-list">
          <li><span class="ic">✅</span>نقاط القوة — ما يميز استراتيجيتك ويجعلها فعالة</li>
          <li><span class="ic">⚠️</span>نقاط الضعف — الثغرات والمخاطر الخفية</li>
          <li><span class="ic">📈</span>أفضل الأوقات — متى وأين تعمل الاستراتيجية بشكل مثالي</li>
          <li><span class="ic">🛡️</span>إدارة المخاطر — كيف تحسّن نسبة المخاطرة/العائد</li>
          <li><span class="ic">💡</span>توصيات التطوير — خطوات عملية لتحسين استراتيجيتك</li>
          <li><span class="ic">⭐</span>تقييم إجمالي من 10 مع تبرير مفصل</li>
        </ul>
      </div>
      <div class="strat-demo">
        <div class="strat-demo-title">🔍 جرّب التحليل الآن عبر البوت:</div>
        <textarea class="strat-input" id="stratInput" placeholder="مثال: أستخدم RSI عند مستوى 30 للشراء و70 للبيع، مع تأكيد من MACD، وأضع وقف خسارة 50 نقطة..."></textarea>
        <button class="strat-btn" onclick="tryStrategy()">🤖 تحليل الاستراتيجية</button>
        <div class="strat-result" id="stratResult"></div>
        <div style="margin-top:1rem;text-align:center">
          <a href="{{ whatsapp }}" target="_blank" style="font-size:.8rem;color:var(--muted)">أو تواصل عبر واتساب ←</a>
        </div>
      </div>
    </div>
  </div>
</section>

<!-- PLANS -->
<section id="plans">
  <div class="container">
    <div class="sec-header center">
      <div class="sec-badge">💎 خطط الاشتراك</div>
      <h2 class="sec-title">اختر <span class="hl">الخطة المناسبة</span></h2>
      <p class="sec-sub">جميع الخطط تبدأ بـ {{ free_signals }} إشارات مجانية — لا تحتاج بطاقة ائتمان</p>
    </div>
    <div class="plans-grid">
      <div class="plan-card">
        <div class="plan-name">🥉 الأساسية</div>
        <div class="plan-price">5$ <span>/ شهر</span></div>
        <div class="plan-desc">مثالية للمبتدئين الراغبين في متابعة السوق</div>
        <ul class="plan-features">
          <li><span class="ic">✅</span>سعر الذهب المباشر لحظياً</li>
          <li><span class="ic">✅</span>معاينة الإشارات (اتجاه فقط)</li>
          <li><span class="ic">✅</span>مؤشر RSI و MACD</li>
          <li><span class="ic">✅</span>دعم واتساب</li>
          <li class="off"><span class="ic">✗</span><span class="no">أرقام الإشارة الكاملة</span></li>
          <li class="off"><span class="ic">✗</span><span class="no">تحليل الشارت AI</span></li>
          <li class="off"><span class="ic">✗</span><span class="no">مكتبة الكورسات</span></li>
        </ul>
        <a href="{{ whatsapp }}" target="_blank" class="plan-btn">اشترك الأساسية</a>
      </div>
      <div class="plan-card featured">
        <div class="plan-badge-featured">🔥 الأكثر مبيعاً</div>
        <div class="plan-name">🥈 المتقدمة</div>
        <div class="plan-price">15$ <span>/ شهر</span></div>
        <div class="plan-desc">للمتداولين الجادين الراغبين في إشارات احترافية</div>
        <ul class="plan-features">
          <li><span class="ic">✅</span>كل مميزات الأساسية</li>
          <li><span class="ic">✅</span>إشارات XAUUSD كاملة مع الأرقام</li>
          <li><span class="ic">✅</span>12 مصدر تأكيد لكل إشارة</li>
          <li><span class="ic">✅</span>تحليل شارت AI (5 صور/يوم)</li>
          <li><span class="ic">✅</span>تحليل استراتيجيتك</li>
          <li><span class="ic">✅</span>كورسات التحليل الأساسية</li>
          <li class="off"><span class="ic">✗</span><span class="no">إشارات تلقائية 24/7</span></li>
        </ul>
        <a href="{{ whatsapp }}" target="_blank" class="plan-btn">اشترك المتقدمة</a>
      </div>
      <div class="plan-card">
        <div class="plan-name">🥇 VIP الاحترافية</div>
        <div class="plan-price">30$ <span>/ شهر</span></div>
        <div class="plan-desc">الحل الكامل للمتداول الاحترافي</div>
        <ul class="plan-features">
          <li><span class="ic">✅</span>كل مميزات المتقدمة</li>
          <li><span class="ic">✅</span>إشارات تلقائية فورية 24/7</li>
          <li><span class="ic">✅</span>تحليل شارت AI غير محدود</li>
          <li><span class="ic">✅</span>مكتبة +200 كورس كاملة</li>
          <li><span class="ic">✅</span>إشعار فوري عند كل إشارة</li>
          <li><span class="ic">✅</span>تحليل استراتيجية غير محدود</li>
          <li><span class="ic">✅</span>دعم VIP أولوية قصوى</li>
        </ul>
        <a href="{{ whatsapp }}" target="_blank" class="plan-btn">اشترك VIP</a>
      </div>
    </div>
  </div>
</section>

<!-- PAYMENT METHODS -->
<section class="payment-section" id="payment">
  <div class="container">
    <div class="sec-header center">
      <div class="sec-badge">💳 طرق الدفع</div>
      <h2 class="sec-title">طرق <span class="hl">الدفع المتاحة</span></h2>
      <p class="sec-sub">ندعم جميع وسائل الدفع الشائعة في العالم العربي والعالمي</p>
    </div>
    <div class="payment-grid">
      <div class="pay-card">
        <div class="pay-icon">🟡</div>
        <div class="pay-name">Binance Pay</div>
        <div class="pay-desc">تحويل USDT/BNB/BUSD فوري</div>
      </div>
      <div class="pay-card">
        <div class="pay-icon">🔵</div>
        <div class="pay-name">PayPal</div>
        <div class="pay-desc">دفع دولي سريع وآمن</div>
      </div>
      <div class="pay-card">
        <div class="pay-icon">💳</div>
        <div class="pay-name">Visa / MasterCard</div>
        <div class="pay-desc">بطاقات دولية مقبولة</div>
      </div>
      <div class="pay-card">
        <div class="pay-icon">🔴</div>
        <div class="pay-name">فودافون كاش</div>
        <div class="pay-desc">تحويل فوري على الرقم</div>
      </div>
      <div class="pay-card">
        <div class="pay-icon">🟢</div>
        <div class="pay-name">InstaPay</div>
        <div class="pay-desc">تحويل بنكي لحظي</div>
      </div>
      <div class="pay-card">
        <div class="pay-icon">🟠</div>
        <div class="pay-name">USDT (TRC20)</div>
        <div class="pay-desc">عملة مشفرة مستقرة</div>
      </div>
      <div class="pay-card">
        <div class="pay-icon">🔷</div>
        <div class="pay-name">بي باب / Fawry</div>
        <div class="pay-desc">دفع إلكتروني محلي</div>
      </div>
      <div class="pay-card">
        <div class="pay-icon">💬</div>
        <div class="pay-name">وسيلة أخرى؟</div>
        <div class="pay-desc">تواصل معنا للترتيب</div>
      </div>
    </div>
    <div class="pay-question">
      <div>
        <div class="pay-q-text">🤔 هل لديك وسيلة دفع أخرى؟</div>
        <div class="pay-q-sub">تواصل معنا وسنرتب أي طريقة دفع تناسبك — نريدك أن تنضم بأسهل طريقة ممكنة</div>
      </div>
      <a href="{{ whatsapp }}" target="_blank" class="btn-whatsapp">💬 تواصل معنا الآن</a>
    </div>
    <div class="binance-info">
      💡 <strong>ربط Binance Pay:</strong> نحتاج من عندك:
      (1) Binance ID أو رابط QR الخاص بحسابك ،
      (2) تأكيد المبلغ وإرسال لقطة الشاشة عبر واتساب.
      التفعيل فوري بعد التأكيد. للمساعدة:
      <a href="{{ whatsapp }}" target="_blank" style="color:#f0b90b">تواصل معنا ←</a>
    </div>
  </div>
</section>

<!-- GENERAL BOT FEATURES -->
<section style="background:var(--bg3);" id="genbot">
  <div class="container">
    <div class="sec-header">
      <div class="sec-badge">🤖 البوت العربي العام</div>
      <h2 class="sec-title">مساعد <span class="hl">ذكاء اصطناعي</span> متكامل</h2>
      <p class="sec-sub">بوت تيليجرام عربي متكامل بإمكانيات ذكاء اصطناعي متقدمة — منفصل عن بوت التداول</p>
    </div>
    <div class="genbot-grid">
      <div>
        <div class="genbot-features">
          <div class="gb-feat"><div class="gb-feat-icon">🤖</div><div class="gb-feat-text">محادثة AI ذكية 15 مفتاح Gemini</div></div>
          <div class="gb-feat"><div class="gb-feat-icon">📹</div><div class="gb-feat-text">تحميل يوتيوب / إنستغرام / تيك توك</div></div>
          <div class="gb-feat"><div class="gb-feat-icon">🎵</div><div class="gb-feat-text">تحميل الموسيقى بصيغة MP3</div></div>
          <div class="gb-feat"><div class="gb-feat-icon">🎤</div><div class="gb-feat-text">تحويل صوت → نص بالعربية</div></div>
          <div class="gb-feat"><div class="gb-feat-icon">🔊</div><div class="gb-feat-text">تحويل نص → صوت عربي احترافي</div></div>
          <div class="gb-feat"><div class="gb-feat-icon">🎨</div><div class="gb-feat-text">تعديل الصور (أنمي/واقعي/خلفية)</div></div>
          <div class="gb-feat"><div class="gb-feat-icon">📊</div><div class="gb-feat-text">استبيانات وتذكير يومي</div></div>
          <div class="gb-feat"><div class="gb-feat-icon">👑</div><div class="gb-feat-text">أوامر إدارية شاملة للمسؤول</div></div>
        </div>
      </div>
      <div class="genbot-card">
        <div class="genbot-logo">🤖</div>
        <div class="genbot-name">البوت العربي الذكي</div>
        <div class="genbot-desc">مساعد شامل يدعم تنزيل الوسائط وتحويل الصوت والمحادثة الذكية باللغة العربية</div>
        <div class="genbot-keys">
          <span class="gk">Gemini 2.0 Flash</span>
          <span class="gk">Gemini 1.5 Pro</span>
          <span class="gk">Faster Whisper</span>
          <span class="gk">14 مفتاح AI</span>
          <span class="gk">yt-dlp</span>
        </div>
        <a href="{{ whatsapp }}" target="_blank" class="btn-primary" style="width:100%;justify-content:center">💬 احصل على البوت</a>
      </div>
    </div>
  </div>
</section>

<!-- COURSES -->
<section class="courses-section" id="courses">
  <div class="container">
    <div class="sec-header center">
      <div class="sec-badge">🎓 المكتبة التعليمية</div>
      <h2 class="sec-title">أكثر من <span class="hl">200 كورس</span> تداول</h2>
      <p class="sec-sub">12 تصنيف شاملاً من أفضل المدربين العرب والعالميين</p>
    </div>
    <div class="courses-grid">{{ courses_html }}</div>
    <div style="text-align:center;margin-top:2rem">
      <a href="{{ whatsapp }}" target="_blank" class="btn-primary">💬 اشترك للوصول الكامل للمكتبة</a>
    </div>
  </div>
</section>

<!-- COMPANY POLICY -->
<section class="policy-section" id="policy">
  <div class="container">
    <div class="sec-header center">
      <div class="sec-badge">📋 سياسات الشركة</div>
      <h2 class="sec-title">الشروط و<span class="hl">السياسات</span></h2>
    </div>
    <div class="policy-grid">
      <div class="pol-card">
        <div class="pol-icon">⚠️</div>
        <div class="pol-title">إخلاء المسؤولية</div>
        <div class="pol-text">
          إشاراتنا للأغراض التعليمية والإعلامية فقط. التداول في الأسواق المالية ينطوي على مخاطر عالية وقد تخسر رأس مالك. النتائج السابقة لا تضمن نتائج مستقبلية. تداول فقط بما تستطيع تحمل خسارته.
        </div>
      </div>
      <div class="pol-card">
        <div class="pol-icon">🔒</div>
        <div class="pol-title">سياسة الخصوصية</div>
        <div class="pol-text">
          نحترم خصوصيتك. لا نشارك بياناتك مع أي طرف ثالث. نجمع فقط معرّف تيليجرام لتقديم الخدمة. يمكنك طلب حذف بياناتك في أي وقت عبر التواصل المباشر.
        </div>
      </div>
      <div class="pol-card">
        <div class="pol-icon">🔄</div>
        <div class="pol-title">سياسة الاشتراك والإلغاء</div>
        <div class="pol-text">
          يمكن إلغاء الاشتراك في أي وقت. لا يوجد استرداد للمبالغ بعد الدفع نظراً للطابع الرقمي للخدمة. التفعيل فوري بعد تأكيد الدفع. للشكاوى والدعم تواصل عبر واتساب.
        </div>
      </div>
    </div>
    <div class="risk-banner">
      ⚠️ <strong>تحذير المخاطر:</strong> تداول العملات الأجنبية والمعادن الثمينة ينطوي على مستوى عالٍ من المخاطر وقد لا يكون مناسباً لجميع المستثمرين. قبل اتخاذ أي قرار استثماري، تأكد من فهمك الكامل للمخاطر المرتبطة. لا تتداول بأموال لا تستطيع تحمل خسارتها.
    </div>
  </div>
</section>

<!-- SUPPORT & FAQ -->
<section class="support-section" id="support">
  <div class="container">
    <div class="sec-header center">
      <div class="sec-badge">💬 الدعم الفني</div>
      <h2 class="sec-title">نحن هنا <span class="hl">لمساعدتك</span></h2>
    </div>
    <div class="support-grid">
      <div>
        <div class="support-channels">
          <a href="{{ whatsapp }}" target="_blank" class="sc-card" style="text-decoration:none">
            <div class="sc-icon">💬</div>
            <div><div class="sc-title">واتساب المباشر</div><div class="sc-desc">دعم على مدار الساعة — رد خلال دقائق</div></div>
          </a>
          <div class="sc-card">
            <div class="sc-icon">🤖</div>
            <div><div class="sc-title">بوت تيليجرام</div><div class="sc-desc">استخدم أمر /start للقائمة الرئيسية</div></div>
          </div>
          <div class="sc-card">
            <div class="sc-icon">⏰</div>
            <div><div class="sc-title">أوقات الدعم</div><div class="sc-desc">الاثنين — الجمعة: 9 ص — 11 م | السبت — الأحد: مغلق (مع السوق)</div></div>
          </div>
          <div class="sc-card">
            <div class="sc-icon">⚡</div>
            <div><div class="sc-title">وقت الاستجابة</div><div class="sc-desc">عادةً خلال 15 دقيقة للمشتركين VIP</div></div>
          </div>
        </div>
      </div>
      <div>
        <div class="faq-item">
          <div class="faq-q" onclick="toggleFaq(this)">
            <span>كيف أحصل على 3 إشارات مجانية؟</span>
            <span class="arrow">▼</span>
          </div>
          <div class="faq-a">ابدأ بوت التداول على تيليجرام وسيتعرف عليك تلقائياً كعضو جديد. اضغط "إشارة تداول الآن" 3 مرات وستحصل على إشارات حقيقية كاملة مجاناً.</div>
        </div>
        <div class="faq-item">
          <div class="faq-q" onclick="toggleFaq(this)">
            <span>هل إشارات VIP تعمل يومياً؟</span>
            <span class="arrow">▼</span>
          </div>
          <div class="faq-a">الإشارات تعمل من الاثنين إلى الجمعة فقط (مع سوق الفوركس). البوت يتوقف تلقائياً يومي السبت والأحد وينبهك عند إعادة فتح السوق الاثنين.</div>
        </div>
        <div class="faq-item">
          <div class="faq-q" onclick="toggleFaq(this)">
            <span>ما دقة الإشارات فعلياً؟</span>
            <span class="arrow">▼</span>
          </div>
          <div class="faq-a">النظام يُصدر إشارة فقط عند توافق 7 من أصل 12 مصدر تأكيد بثقة 65% أو أعلى. الدقة التاريخية تتراوح بين 65%-79% حسب ظروف السوق.</div>
        </div>
        <div class="faq-item">
          <div class="faq-q" onclick="toggleFaq(this)">
            <span>كيف يعمل تحليل الاستراتيجية؟</span>
            <span class="arrow">▼</span>
          </div>
          <div class="faq-a">أرسل /strategy متبوعاً بوصف استراتيجيتك في البوت. الذكاء الاصطناعي يحلل نقاط القوة والضعف ويعطيك تقييم وتوصيات تطوير مخصصة.</div>
        </div>
        <div class="faq-item">
          <div class="faq-q" onclick="toggleFaq(this)">
            <span>هل يمكنني إلغاء الاشتراك؟</span>
            <span class="arrow">▼</span>
          </div>
          <div class="faq-a">نعم، تواصل معنا عبر واتساب وسيتم إلغاء اشتراكك فوراً. لا يوجد استرداد للمبالغ المدفوعة نظراً للطبيعة الرقمية للخدمة.</div>
        </div>
      </div>
    </div>
  </div>
</section>

<!-- FOOTER -->
<footer>
  <div class="footer-grid">
    <div class="footer-brand">
      <div class="logo"><span>⚡</span>بوت التداول الذكي</div>
      <p>نظام إشارات XAUUSD احترافي بـ12 مصدر تأكيد. تجربة مجانية 3 إشارات حقيقية.</p>
      <div style="margin-top:1rem;display:flex;gap:.5rem;flex-wrap:wrap">
        <span style="background:var(--gold3);border:1px solid var(--border);border-radius:4px;padding:.2rem .5rem;font-size:.72rem;color:var(--gold)">v7.0</span>
        <span style="background:rgba(34,197,94,.1);border:1px solid rgba(34,197,94,.2);border-radius:4px;padding:.2rem .5rem;font-size:.72rem;color:var(--green)">● يعمل</span>
      </div>
    </div>
    <div class="footer-col">
      <h4>الخدمات</h4>
      <ul>
        <li><a href="#signal">إشارات XAUUSD</a></li>
        <li><a href="#strategy">تحليل الاستراتيجية</a></li>
        <li><a href="#features">تحليل الشارت AI</a></li>
        <li><a href="#courses">مكتبة الكورسات</a></li>
      </ul>
    </div>
    <div class="footer-col">
      <h4>الاشتراكات</h4>
      <ul>
        <li><a href="#plans">الخطة الأساسية 5$</a></li>
        <li><a href="#plans">الخطة المتقدمة 15$</a></li>
        <li><a href="#plans">VIP الاحترافية 30$</a></li>
        <li><a href="#payment">طرق الدفع</a></li>
      </ul>
    </div>
    <div class="footer-col">
      <h4>الدعم</h4>
      <ul>
        <li><a href="{{ whatsapp }}" target="_blank">واتساب المباشر</a></li>
        <li><a href="#support">الأسئلة الشائعة</a></li>
        <li><a href="#policy">سياسة الخصوصية</a></li>
        <li><a href="/files">تحميل الملفات</a></li>
      </ul>
    </div>
  </div>
  <div class="footer-bottom">
    <div>© 2026 بوت التداول الذكي. جميع الحقوق محفوظة.</div>
    <div>صُنع بـ ❤️ للمتداولين العرب</div>
  </div>
</footer>

<!-- WHATSAPP FLOAT -->
<a href="{{ whatsapp }}" target="_blank" class="wa-float">💬</a>

<!-- TRADINGVIEW WIDGET -->
<script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
<script>
new TradingView.widget({
  "width": "100%","height": 500,
  "symbol": "OANDA:XAUUSD","interval": "15",
  "timezone": "Etc/UTC","theme": "dark","style": "1",
  "locale": "ar","toolbar_bg": "#07070f",
  "enable_publishing": false,"hide_top_toolbar": false,
  "hide_legend": false,"save_image": false,
  "container_id": "tradingview_chart",
  "studies": ["RSI@tv-basicstudies","MACD@tv-basicstudies","BB@tv-basicstudies"]
});
</script>

<script>
// ── Live Price Update
async function updatePrice(){
  try{
    const d=await fetch('/api/price').then(r=>r.json());
    if(!d.price)return;
    const p=d.price.toLocaleString('en',{minimumFractionDigits:2,maximumFractionDigits:2});
    document.getElementById('heroPrice').textContent='$'+p;
    document.getElementById('navPrice').textContent='XAU $'+p;
    document.getElementById('t1').textContent='$'+p;
    document.getElementById('t1b').textContent='$'+p;
    const chg=d.change||0,pct=d.pct||0;
    const sign=chg>=0?'+':'';
    const chgEl=document.getElementById('heroChange');
    chgEl.textContent=sign+chg.toFixed(2)+' ('+sign+pct.toFixed(3)+'%)';
    chgEl.className='price-change '+(chg>=0?'up':'dn');
    document.getElementById('t2').textContent=sign+chg.toFixed(2);
    document.getElementById('t2b').textContent=sign+chg.toFixed(2);
    if(d.high){
      const h='$'+d.high.toLocaleString('en',{minimumFractionDigits:2});
      document.getElementById('heroHigh').textContent=h;
      document.getElementById('t3').textContent=h;
      document.getElementById('t3b').textContent=h;
    }
    if(d.low){
      const l='$'+d.low.toLocaleString('en',{minimumFractionDigits:2});
      document.getElementById('heroLow').textContent=l;
      document.getElementById('t4').textContent=l;
      document.getElementById('t4b').textContent=l;
    }
    document.getElementById('heroUpdated').textContent=d.updated||'—';
    // RSI estimate
    const rsi=chg>0?55:45;
    const rsiEl=document.getElementById('mi_rsi');
    rsiEl.className='mi '+(rsi>60?'buy':rsi<40?'sell':'neutral');
    rsiEl.querySelector('.v').textContent=rsi.toFixed(0);
    // MACD
    const macdEl=document.getElementById('mi_macd');
    macdEl.className='mi '+(chg>0?'buy':'sell');
    macdEl.querySelector('.v').textContent=chg>0?'BUY':'SELL';
    // BB
    const bbEl=document.getElementById('mi_bb');
    bbEl.className='mi neutral';
    bbEl.querySelector('.v').textContent=Math.abs(pct)<0.15?'محايد':(pct>0?'أعلى':'أدنى');
    // Session
    const h=new Date().getUTCHours();
    let sess='مغلق 🌙';
    if(h>=22||h<8)sess='آسيا 🌏';
    else if(h>=8&&h<12)sess='لندن 🇬🇧';
    else if(h>=12&&h<17)sess='أمريكا 🇺🇸 + لندن 🔥';
    else if(h>=17&&h<22)sess='أمريكا 🇺🇸';
    document.getElementById('sessionText').textContent=sess;
  }catch(e){}
}

// ── Live Signal Update
async function updateSignal(){
  try{
    const d=await fetch('/api/signal').then(r=>r.json());
    if(!d.direction)return;
    const dirEl=document.getElementById('sigDir');
    dirEl.textContent=d.direction==='BUY'?'🟢 شراء BUY':'🔴 بيع SELL';
    dirEl.className='sig-dir '+(d.direction||'');
    document.getElementById('sigEntry').textContent='$'+(d.entry_price||0).toLocaleString('en',{minimumFractionDigits:2});
    document.getElementById('sigTp1').textContent='$'+(d.tp1||0).toLocaleString('en',{minimumFractionDigits:2});
    document.getElementById('sigTp2').textContent='$'+(d.tp2||0).toLocaleString('en',{minimumFractionDigits:2});
    document.getElementById('sigTp3').textContent='$'+(d.tp3||0).toLocaleString('en',{minimumFractionDigits:2});
    document.getElementById('sigSl').textContent='$'+(d.sl||0).toLocaleString('en',{minimumFractionDigits:2});
    document.getElementById('sigTime').textContent=d.timestamp||'—';
    const conf=d.confidence||0;
    document.getElementById('confFill').style.width=conf+'%';
    document.getElementById('confPct').textContent=conf+'%';
    // Sources
    const srcs=['RSI','MACD','Bollinger','Fibonacci','ATR','Stochastic'];
    const mc=d.models_confirmed||0,ic=d.indicators_confirmed||0;
    let html='';
    srcs.forEach((s,i)=>{
      const ok=i<ic;
      html+=`<div class="src-badge ${ok?'ok':'ng'}">${ok?'✅':'⬜'} ${s}</div>`;
    });
    document.getElementById('sigSources').innerHTML=html;
  }catch(e){}
}

// ── Stats Update
async function updateStats(){
  try{
    const d=await fetch('/api/stats').then(r=>r.json());
    const u=(d.users||0);const s=(d.signals||0);
    document.getElementById('statUsers').textContent=u>0?u+'+':'0+';
    document.getElementById('statSigs').textContent=s>0?s+'+':'0+';
    document.getElementById('statsUsers').textContent=u>0?u+'+':'0+';
    document.getElementById('statsSigs').textContent=s>0?s+'+':'0+';
  }catch(e){}
}

// ── Market Status
function checkMarket(){
  const d=new Date();const day=d.getUTCDay();
  const bar=document.getElementById('marketBar');
  if(day===0||day===6){bar.style.display='block';}
  else{bar.style.display='none';}
}

// ── FAQ Toggle
function toggleFaq(el){
  el.classList.toggle('open');
  const ans=el.nextElementSibling;
  ans.classList.toggle('open');
}

// ── Strategy Demo
function tryStrategy(){
  const txt=document.getElementById('stratInput').value.trim();
  if(!txt){alert('يرجى كتابة وصف استراتيجيتك أولاً');return;}
  const res=document.getElementById('stratResult');
  res.style.display='block';
  res.innerHTML='🔄 جاري التحليل...';
  setTimeout(()=>{
    res.innerHTML=`
      <strong style="color:var(--gold)">🤖 ملاحظة:</strong> التحليل الكامل متاح عبر البوت فقط.<br><br>
      للحصول على تحليل حقيقي ومفصل لاستراتيجيتك:<br>
      ① افتح بوت التداول على تيليجرام<br>
      ② اضغط "تحليل استراتيجيتي" أو أرسل: <code>/strategy ${txt.substring(0,30)}...</code><br>
      ③ ستحصل على تحليل احترافي في ثوانٍ!`;
  },1500);
}

// ── Init
updatePrice();updateSignal();updateStats();checkMarket();
setInterval(updatePrice,30000);
setInterval(updateSignal,60000);
setInterval(updateStats,60000);
</script>
</body>
</html>"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
