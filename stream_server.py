# stream_server.py
from flask import Flask, request, send_from_directory, abort, Response, jsonify
import os
import mimetypes
import asyncio
from yt_dlp import YoutubeDL
import time
import hashlib
import urllib.parse # Added for URL encoding/decoding

app = Flask(__name__)

DOWNLOAD_CACHE_DIR = "stream_cache"
os.makedirs(DOWNLOAD_CACHE_DIR, exist_ok=True)

# Your Channel/Group Links
TELEGRAM_MAIN_CHANNEL = "t.me/asbhai_bsr"
TELEGRAM_CHAT_GROUP = "t.me/aschat_group"
TELEGRAM_MOVIE_GROUP = "t.me/istreamx"

@app.route('/')
def index():
    return "Terabox Streaming Server is running! Use via Telegram Bot."

# This route will show the HTML page with links and initiate the download/stream
@app.route('/view_media')
def view_media():
    terabox_link = request.args.get('url')
    # Use urllib.parse.unquote_plus to decode the URL
    decoded_terabox_link = urllib.parse.unquote_plus(terabox_link) if terabox_link else ""
    
    if not terabox_link:
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Media Viewer</title>
            <style>
                body { font-family: sans-serif; text-align: center; margin-top: 50px; background-color: #222; color: #eee; }
                .container { background-color: #333; padding: 20px; border-radius: 8px; max-width: 600px; margin: auto; box-shadow: 0 4px 8px rgba(0,0,0,0.5); }
                .button {
                    display: inline-block;
                    padding: 10px 20px;
                    margin: 10px;
                    background-color: #007bff;
                    color: white;
                    text-decoration: none;
                    border-radius: 5px;
                    transition: background-color 0.3s ease;
                }
                .button.download { background-color: #28a745; }
                .button.stream { background-color: #007bff; }
                .button:hover { opacity: 0.9; }
                .important-message { color: #ffdd00; font-weight: bold; margin-bottom: 20px; }
                .channel-links { margin-top: 30px; border-top: 1px solid #444; padding-top: 20px; }
                .channel-links a { color: #66ccff; text-decoration: none; margin: 0 10px; }
                .channel-links a:hover { text-decoration: underline; }
            </style>
        </head>
        <body>
            <div class="container">
                <h2>मीडिया लिंक अनुपलब्ध!</h2>
                <p>कृपया टेलीग्राम बॉट के माध्यम से वैध टेराबॉक्स लिंक प्रदान करें।</p>
                <div class="channel-links">
                    <p class="important-message">हमारे अन्य चैनलों और ग्रुप्स को ज्वाइन करें:</p>
                    <a class="button" href="{main_channel_link}" target="_blank">मेन चैनल</a>
                    <a class="button" href="{chat_group_link}" target="_blank">चैट ग्रुप</a>
                    <a class="button" href="{movie_group_link}" target="_blank">मूवी डाउनलोड ग्रुप</a>
                </div>
            </div>
        </body>
        </html>
        """.format(
            main_channel_link=TELEGRAM_MAIN_CHANNEL,
            chat_group_link=TELEGRAM_CHAT_GROUP,
            movie_group_link=TELEGRAM_MOVIE_GROUP
        )

    # If URL is present, show buttons that trigger the actual download/stream
    # These URLs will call the /_serve_media route internally
    watch_direct_url = f"/_serve_media?url={terabox_link}&action=stream"
    download_direct_url = f"/_serve_media?url={terabox_link}&action=download"

    # You can also pass video title here if you want to display it on the page
    video_title = request.args.get('title', 'Video').replace("_", " ") # Decode title for display

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>मीडिया उपलब्ध!</title>
        <style>
            body { font-family: sans-serif; text-align: center; margin-top: 50px; background-color: #222; color: #eee; }
            .container { background-color: #333; padding: 20px; border-radius: 8px; max-width: 600px; margin: auto; box-shadow: 0 4px 8px rgba(0,0,0,0.5); }
            .button {
                display: inline-block;
                padding: 10px 20px;
                margin: 10px;
                background-color: #007bff;
                color: white;
                text-decoration: none;
                border-radius: 5px;
                transition: background-color 0.3s ease;
            }
            .button.download { background-color: #28a745; }
            .button.stream { background-color: #007bff; }
            .button:hover { opacity: 0.9; }
            .important-message { color: #ffdd00; font-weight: bold; margin-bottom: 20px; }
            .channel-links { margin-top: 30px; border-top: 1px solid #444; padding-top: 20px; }
            .channel-links a { color: #66ccff; text-decoration: none; margin: 0 10px; }
            .channel-links a:hover { text-decoration: underline; }
            .loading-message { margin-top: 20px; font-style: italic; color: #bbb; }
        </style>
        <script>
            function showLoading(buttonType) {{
                const messageDiv = document.getElementById('status-message');
                messageDiv.innerHTML = 'कृपया प्रतीक्षा करें... ' + buttonType + ' शुरू हो रहा है। यह प्रक्रिया कुछ मिनट ले सकती है।';
                messageDiv.style.color = '#ffdd00';
            }}
        </script>
    </head>
    <body>
        <div class="container">
            <h2>🎉 आपका मीडिया तैयार है!</h2>
            <h3>{video_title}</h3>
            <p>नीचे दिए गए बटन से आप मीडिया को स्ट्रीम या डाउनलोड कर सकते हैं।</p>
            <div id="status-message" class="loading-message"></div>
            <div>
                <a class="button stream" href="{watch_direct_url}" onclick="showLoading('स्ट्रीमिंग')">▶️ देखो</a>
                <a class="button download" href="{download_direct_url}" onclick="showLoading('डाउनलोड')">⬇️ डाउनलोड</a>
            </div>
            <div class="channel-links">
                <p class="important-message">हमारे अन्य चैनलों और ग्रुप्स को ज्वाइन करें:</p>
                <a class="button" href="{TELEGRAM_MAIN_CHANNEL}" target="_blank">मेन चैनल</a>
                <a class="button" href="{TELEGRAM_CHAT_GROUP}" target="_blank">चैट ग्रुप</a>
                <a class="button" href="{TELEGRAM_MOVIE_GROUP}" target="_blank">मूवी डाउनलोड ग्रुप</a>
            </div>
        </div>
    </body>
    </html>
    """

# This route will actually handle the streaming/downloading of the media
@app.route('/_serve_media')
async def serve_media():
    terabox_link = request.args.get('url')
    action = request.args.get('action') # 'stream' or 'download'

    if not terabox_link or not action:
        return jsonify({"error": "Missing 'url' or 'action' parameter"}), 400

    # Generate a unique filename for the downloaded video
    unique_id = hashlib.md5(terabox_link.encode()).hexdigest()
    temp_filepath_template = os.path.join(DOWNLOAD_CACHE_DIR, f'{unique_id}_%(title)s.%(ext)s')

    filepath = None
    try:
        # Check if file already exists in cache (simple cache mechanism)
        cached_files = [f for f in os.listdir(DOWNLOAD_CACHE_DIR) if f.startswith(unique_id)]
        if cached_files:
            filepath = os.path.join(DOWNLOAD_CACHE_DIR, cached_files[0])
            app.logger.info(f"Serving from cache: {filepath}")
        else:
            # File not in cache, download it
            ydl_opts = {
                'format': 'best',
                'outtmpl': temp_filepath_template,
                'noplaylist': True,
                'verbose': False,
                'quiet': True,
                'no_warnings': True,
                'merge_output_format': 'mp4', # Ensures compatible format
                'retries': 3,
                'fragment_retries': 3,
            }
            with YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(terabox_link, download=True)
                if not info_dict:
                    raise Exception("Could not extract info or download from the link.")

                downloaded_files = [f for f in os.listdir(DOWNLOAD_CACHE_DIR) if f.startswith(unique_id)]
                if not downloaded_files:
                    raise Exception("Downloaded file not found after yt-dlp.")
                
                filepath = os.path.join(DOWNLOAD_CACHE_DIR, downloaded_files[0])
            app.logger.info(f"Successfully downloaded to: {filepath}")

        if not filepath or not os.path.exists(filepath):
            raise Exception("File not found or downloaded incorrectly.")

        mime_type, _ = mimetypes.guess_type(filepath)
        if mime_type is None:
            mime_type = 'application/octet-stream'

        if action == 'download':
            return send_from_directory(
                directory=DOWNLOAD_CACHE_DIR,
                path=os.path.basename(filepath),
                as_attachment=True,
                mimetype=mime_type
            )
        elif action == 'stream':
            range_header = request.headers.get('Range', None)
            file_size = os.path.getsize(filepath)

            if range_header:
                parts = range_header.replace('bytes=', '').split('-')
                byte_start = int(parts[0])
                byte_end = int(parts[1]) if len(parts) > 1 and parts[1] else file_size - 1

                if byte_end >= file_size:
                    byte_end = file_size - 1

                content_length = byte_end - byte_start + 1
                headers = {
                    'Content-Range': f'bytes {byte_start}-{byte_end}/{file_size}',
                    'Accept-Ranges': 'bytes',
                    'Content-Length': str(content_length),
                    'Content-Type': mime_type
                }
                response = Response(
                    _generate_file_chunk(filepath, byte_start, byte_end),
                    206, # Partial Content
                    headers=headers
                )
                return response
            else:
                return send_from_directory(
                    directory=DOWNLOAD_CACHE_DIR,
                    path=os.path.basename(filepath),
                    mimetype=mime_type
                )
        else:
            return jsonify({"error": "Invalid action specified"}), 400

    except Exception as e:
        app.logger.error(f"Error serving media for {terabox_link}: {e}")
        return jsonify({"error": f"मीडिया प्रोसेस करने में विफल: {e}"}), 500

def _generate_file_chunk(file_path, start, end):
    with open(file_path, 'rb') as f:
        f.seek(start)
        remaining_bytes = end - start + 1
        while remaining_bytes > 0:
            chunk_size = min(remaining_bytes, 8192)
            chunk = f.read(chunk_size)
            if not chunk:
                break
            yield chunk
            remaining_bytes -= len(chunk)

# Simple cleanup - consider a more robust solution for production
@app.before_request
def before_request():
    # Only run cleanup if enough time has passed
    if not hasattr(app, 'last_cleanup_time') or (time.time() - app.last_cleanup_time) > 3600: # Every 1 hour
        cleanup_old_files()
        app.last_cleanup_time = time.time()

if __name__ == '__main__':
    # For local testing
    # app.run(debug=True, port=int(os.environ.get('PORT', 5000)))
    pass # Gunicorn will run this on Koyeb
