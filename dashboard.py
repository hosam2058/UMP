import json
import sqlite3
import os
from flask import Flask, render_template, request, redirect, url_for, jsonify
from datetime import datetime
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'downloads/broadcast'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def get_db_connection():
    conn = sqlite3.connect('data/bot.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def index():
    conn = get_db_connection()
    try:
        total_users = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        blocked_users = conn.execute('SELECT COUNT(*) FROM users WHERE blocked_or_left = 1').fetchone()[0]
        today = datetime.utcnow().strftime('%Y-%m-%d')
        joined_today = conn.execute('SELECT COUNT(*) FROM users WHERE date(created_at) = ?', (today,)).fetchone()[0]
        usage_stats = conn.execute('SELECT feature_name, COUNT(*) as count FROM feature_usage GROUP BY feature_name ORDER BY count DESC').fetchall()
        users = conn.execute('''
            SELECT u.*, 
            (SELECT COUNT(*) FROM messages WHERE tg_id = u.tg_id) as msg_count 
            FROM users u 
            ORDER BY created_at DESC
        ''').fetchall()
    except:
        total_users = 0
        blocked_users = 0
        joined_today = 0
        usage_stats = []
        users = []
    
    gemini_keys = []
    for i in range(1, 15):
        key = os.environ.get(f'GEMINI_API_KEY_{i}')
        if key:
            gemini_keys.append({"id": i, "status": "نشط" if len(key) > 10 else "غير صالح"})
    
    conn.close()
    return render_template('index.html', 
                           total_users=total_users, 
                           blocked_users=blocked_users, 
                           joined_today=joined_today,
                           usage_stats=usage_stats,
                           users=users,
                           gemini_keys=gemini_keys)

@app.route('/user/<tg_id>')
def user_history(tg_id):
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE tg_id = ?', (tg_id,)).fetchone()
    messages = conn.execute('SELECT * FROM messages WHERE tg_id = ? ORDER BY created_at ASC', (tg_id,)).fetchall()
    conn.close()
    return render_template('user_history.html', user=user, messages=messages)

@app.route('/broadcast', methods=['POST'])
def broadcast():
    target_bot = request.form.get('target_bot', 'bot1')
    msg_type = request.form.get('type')
    text_content = request.form.get('text_content', '')
    
    db_file = 'data/bot.db' if target_bot == 'bot1' else 'data/trading_bot.db'
    
    if msg_type == 'survey':
        question = request.form.get('question')
        options = request.form.getlist('options[]')
        responses = request.form.getlist('responses[]')
        survey_id = str(int(datetime.utcnow().timestamp()))
        survey_data = []
        for i in range(len(options)):
            survey_data.append({
                "text": options[i],
                "response": responses[i] if i < len(responses) else "تم تسجيل صوتك!",
                "count": 0
            })
        
        # إضافة الاستبيان إلى طابور البث لكل البوتات المختارة
        conn = sqlite3.connect(db_file)
        try:
            conn.execute('CREATE TABLE IF NOT EXISTS broadcast_queue (id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, file_path TEXT, text_content TEXT, status TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)')
            # حفظ بيانات الاستبيان في text_content كـ JSON ليتم إرساله عبر الحلقات الخلفية
            survey_payload = json.dumps({
                "id": survey_id,
                "question": question,
                "options": survey_data
            })
            conn.execute('INSERT INTO broadcast_queue (type, text_content, status) VALUES (?, ?, ?)',
                         ('survey', survey_payload, 'pending'))
            
            # حفظ في جداول الاستبيانات الأصلية للتوثيق
            if target_bot == 'bot1':
                conn.execute('CREATE TABLE IF NOT EXISTS surveys_multi (id INTEGER PRIMARY KEY AUTOINCREMENT, survey_id TEXT UNIQUE, question TEXT, options_json TEXT, active INTEGER, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)')
                conn.execute('INSERT INTO surveys_multi (survey_id, question, options_json, active) VALUES (?, ?, ?, ?)', 
                             (survey_id, question, json.dumps(survey_data), 1))
            else:
                conn.execute('CREATE TABLE IF NOT EXISTS trading_surveys (id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT, options TEXT, results TEXT, is_active INTEGER, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)')
                conn.execute('INSERT INTO trading_surveys (question, options, results, is_active) VALUES (?, ?, ?, ?)',
                             (question, json.dumps(survey_data), json.dumps([]), 1))
            conn.commit()
        finally:
            conn.close()
    else:
        file_path = None
        if 'file' in request.files:
            file = request.files['file']
            if file and file.filename != '':
                filename = secure_filename(f"{datetime.utcnow().timestamp()}_{file.filename}")
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)
        
        conn = sqlite3.connect(db_file)
        try:
            conn.execute('CREATE TABLE IF NOT EXISTS broadcast_queue (id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, file_path TEXT, text_content TEXT, status TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)')
            conn.execute('INSERT INTO broadcast_queue (type, file_path, text_content, status) VALUES (?, ?, ?, ?)',
                         (msg_type, file_path, text_content, 'pending'))
            conn.commit()
            print(f"DEBUG: Broadcast added to {db_file} queue")
        finally:
            conn.close()
        
    return redirect(url_for('index'))

@app.route('/survey_results')
def survey_results():
    results = []
    # Bot 1 Results
    try:
        conn1 = sqlite3.connect('data/bot.db')
        conn1.row_factory = sqlite3.Row
        # Ensure table exists to prevent Internal Server Error
        conn1.execute('CREATE TABLE IF NOT EXISTS surveys_multi (id INTEGER PRIMARY KEY AUTOINCREMENT, survey_id TEXT UNIQUE, question TEXT, options_json TEXT, active INTEGER, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)')
        surveys1 = conn1.execute('SELECT * FROM surveys_multi ORDER BY created_at DESC').fetchall()
        for s in surveys1:
            try:
                results.append({
                    "bot": "بوت التحميل",
                    "id": s['survey_id'],
                    "question": s['question'],
                    "options": json.loads(s['options_json']),
                    "created_at": s['created_at']
                })
            except Exception as e:
                print(f"Error parsing bot1 survey: {e}")
        conn1.close()
    except Exception as e:
        print(f"Error reading bot1 surveys: {e}")

    # Bot 2 Results
    try:
        conn2 = sqlite3.connect('data/trading_bot.db')
        conn2.row_factory = sqlite3.Row
        # Ensure table exists
        conn2.execute('CREATE TABLE IF NOT EXISTS trading_surveys (id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT, options TEXT, results TEXT, is_active INTEGER, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)')
        surveys2 = conn2.execute('SELECT * FROM trading_surveys ORDER BY created_at DESC').fetchall()
        for s in surveys2:
            try:
                results.append({
                    "bot": "بوت التداول",
                    "id": s['id'],
                    "question": s['question'],
                    "options": json.loads(s['options']),
                    "created_at": s['created_at']
                })
            except Exception as e:
                print(f"Error parsing bot2 survey: {e}")
        conn2.close()
    except Exception as e:
        print(f"Error reading bot2 surveys: {e}")
    
    return render_template('survey_results.html', surveys=results)

@app.route('/api/stats')
def api_stats():
    try:
        conn = get_db_connection()
        total = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
        conn.close()
    except: total = 0
    return jsonify({"total": total, "timestamp": datetime.utcnow().isoformat()})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000)
