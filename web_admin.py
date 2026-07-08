from flask import Flask, render_template, request, jsonify
import os, json, sqlite3
from datetime import datetime

app = Flask(__name__)

# المسارات
DATA_DIR = "data"
DB_PATH = os.path.join(DATA_DIR, "bot.db")
KEYS_PATH = os.path.join(DATA_DIR, "gemini_keys.json")

def get_db_stats():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM messages")
        total_messages = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1")
        banned_users = cursor.fetchone()[0]
        
        conn.close()
        return {
            "total_users": total_users,
            "total_messages": total_messages,
            "banned_users": banned_users
        }
    except Exception as e:
        return {"total_users": 0, "total_messages": 0, "banned_users": 0, "error": str(e)}

@app.route('/')
def admin_panel():
    stats = get_db_stats()
    
    # تحميل مفاتيح Gemini
    gemini_keys = {}
    if os.path.exists(KEYS_PATH):
        try:
            with open(KEYS_PATH, 'r') as f:
                gemini_keys = json.load(f)
        except:
            pass
            
    return render_template('admin.html', stats=stats, keys=gemini_keys)

@app.route('/update_keys', methods=['POST'])
def update_keys():
    try:
        new_keys = request.json
        os.makedirs(os.path.dirname(KEYS_PATH), exist_ok=True)
        with open(KEYS_PATH, 'w') as f:
            json.dump(new_keys, f, indent=4)
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

if __name__ == '__main__':
    # تشغيل على بورت 5000 لعرضه في Replit
    app.run(host='0.0.0.0', port=5000)
