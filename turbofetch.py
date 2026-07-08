import os
import subprocess
import uuid

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

def turbo_download(url):
    """
    محرك تحميل فائق القوة يستخدم yt-dlp مع تقنيات الالتفاف المتقدمة
    """
    file_id = str(uuid.uuid4())
    output_template = os.path.join(DOWNLOAD_DIR, f"{file_id}.%(ext)s")

    # إعدادات الالتفاف المتقدمة (Bypass)
    command = [
        "yt-dlp",
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "--no-playlist",
        "--nocheckcertificate",
        "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "--add-header", "Referer:https://www.google.com/",
        "--add-header", "Accept:text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "-o", output_template,
        "--geo-bypass",
        url
    ]

    try:
        # محاولة التحميل
        subprocess.run(command, check=True, capture_output=True, timeout=120)

        for file in os.listdir(DOWNLOAD_DIR):
            if file.startswith(file_id):
                return os.path.join(DOWNLOAD_DIR, file)
                
    except Exception as e:
        print(f"Bypass Download Error: {e}")
        
        # محاولة أخيرة (Fallback) بجودة أقل لضمان التحميل
        try:
            command_fallback = [
                "yt-dlp",
                "-f", "best",
                "--no-playlist",
                "-o", output_template,
                url
            ]
            subprocess.run(command_fallback, check=True, capture_output=True, timeout=60)
            for file in os.listdir(DOWNLOAD_DIR):
                if file.startswith(file_id):
                    return os.path.join(DOWNLOAD_DIR, file)
        except:
            pass
    
    return None
