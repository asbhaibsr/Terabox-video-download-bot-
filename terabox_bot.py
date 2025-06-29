import os
import asyncio
import datetime
import urllib.parse
import hashlib
import mimetypes
import time
import logging # Import logging

from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from yt_dlp import YoutubeDL
from motor.motor_asyncio import AsyncIOMotorClient # For MongoDB
from flask import Flask, request, send_from_directory, abort, Response, jsonify
from hypercorn.asyncio import serve
from hypercorn.config import Config

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Bot Configuration ---
API_ID = int(os.environ.get("API_ID", "YOUR_API_ID")) # Replace with your actual API ID
API_HASH = os.environ.get("API_HASH", "YOUR_API_HASH") # Replace with your actual API Hash
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN") # Replace with your actual Bot Token
MONGO_URI = os.environ.get("MONGO_URI", "YOUR_MONGO_URI") # Replace with your MongoDB URI
ADMIN_ID = int(os.environ.get("ADMIN_ID", "YOUR_ADMIN_ID")) # Replace with your admin user ID

FREE_DOWNLOAD_LIMIT = 5 # Example limit for free users

# Initialize Pyrogram Client
app = Client(
    "terabox_download_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# Initialize MongoDB
db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client.terabox_bot_db
users_collection = db.users

async def get_user_data(user_id):
    user = await users_collection.find_one({"_id": user_id})
    if not user:
        user = {
            "_id": user_id,
            "daily_downloads": 0,
            "total_downloads": 0,
            "is_premium": False,
            "last_download_date": datetime.datetime.now()
        }
        await users_collection.insert_one(user)
    return user

async def update_user_data(user_id, update_fields):
    await users_collection.update_one({"_id": user_id}, {"$set": update_fields}, upsert=True)

async def check_premium_status(user_id):
    user = await get_user_data(user_id)
    return user.get("is_premium", False)

# --- Flask Web Server Configuration ---
flask_app = Flask(__name__)

# Directory to temporarily store downloaded files
# This will be shared between the bot's process and the Flask server process
DOWNLOAD_CACHE_DIR = "stream_cache"
os.makedirs(DOWNLOAD_CACHE_DIR, exist_ok=True)

# Your Channel/Group Links
TELEGRAM_MAIN_CHANNEL = "t.me/asbhai_bsr"
TELEGRAM_CHAT_GROUP = "t.me/aschat_group"
TELEGRAM_MOVIE_GROUP = "t.me/istreamx"

# Helper function to clean up old files in the cache
def cleanup_old_files():
    now = time.time()
    for filename in os.listdir(DOWNLOAD_CACHE_DIR):
        filepath = os.path.join(DOWNLOAD_CACHE_DIR, filename)
        if os.path.isfile(filepath):
            # Delete files older than, say, 1 hour (3600 seconds)
            # Adjust as needed based on your storage capacity and usage
            if (now - os.stat(filepath).st_mtime) > 3600:
                try:
                    os.remove(filepath)
                    logger.info(f"Cleaned up old file: {filepath}")
                except Exception as e:
                    logger.error(f"Error cleaning up file {filepath}: {e}")

# This will run cleanup periodically, but in a multi-process Gunicorn setup
# you might need a different strategy (e.g., a cron job or separate worker)
# For a single process (like Pyrogram + Hypercorn for testing), it's okay.
# For Gunicorn in production, this before_request is per request.
# Let's run it once at startup and perhaps less frequently.

@flask_app.route('/')
def web_index():
    cleanup_old_files() # Run cleanup when homepage is accessed
    return "Terabox Streaming Server is running! Use via Telegram Bot."

# This route will show the HTML page with links and initiate the download/stream
@flask_app.route('/view_media')
def view_media():
    terabox_link = request.args.get('url')
    decoded_terabox_link = urllib.parse.unquote_plus(terabox_link) if terabox_link else ""
    
    if not terabox_link:
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Media Viewer</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{ font-family: sans-serif; text-align: center; margin-top: 50px; background-color: #222; color: #eee; }}
                .container {{ background-color: #333; padding: 20px; border-radius: 8px; max-width: 600px; margin: auto; box-shadow: 0 4px 8px rgba(0,0,0,0.5); }}
                .button {{
                    display: inline-block;
                    padding: 10px 20px;
                    margin: 10px;
                    background-color: #007bff;
                    color: white;
                    text-decoration: none;
                    border-radius: 5px;
                    transition: background-color 0.3s ease;
                }}
                .button.download {{ background-color: #28a745; }}
                .button.stream {{ background-color: #007bff; }}
                .button:hover {{ opacity: 0.9; }}
                .important-message {{ color: #ffdd00; font-weight: bold; margin-bottom: 20px; }}
                .channel-links {{ margin-top: 30px; border-top: 1px solid #444; padding-top: 20px; }}
                .channel-links a {{ color: #66ccff; text-decoration: none; margin: 0 10px; }}
                .channel-links a:hover {{ text-decoration: underline; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>मीडिया लिंक अनुपलब्ध!</h2>
                <p>कृपया टेलीग्राम बॉट के माध्यम से वैध टेराबॉक्स लिंक प्रदान करें।</p>
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

    watch_direct_url = f"/_serve_media?url={terabox_link}&action=stream"
    download_direct_url = f"/_serve_media?url={terabox_link}&action=download"
    
    video_title = request.args.get('title', 'Video').replace("_", " ")

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>मीडिया उपलब्ध!</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{ font-family: sans-serif; text-align: center; margin-top: 50px; background-color: #222; color: #eee; }}
            .container {{ background-color: #333; padding: 20px; border-radius: 8px; max-width: 600px; margin: auto; box-shadow: 0 4px 8px rgba(0,0,0,0.5); }}
            .button {{
                display: inline-block;
                padding: 10px 20px;
                margin: 10px;
                background-color: #007bff;
                color: white;
                text-decoration: none;
                border-radius: 5px;
                transition: background-color 0.3s ease;
            }}
            .button.download {{ background-color: #28a745; }}
            .button.stream {{ background-color: #007bff; }}
            .button:hover {{ opacity: 0.9; }}
            .important-message {{ color: #ffdd00; font-weight: bold; margin-bottom: 20px; }}
            .channel-links {{ margin-top: 30px; border-top: 1px solid #444; padding-top: 20px; }}
            .channel-links a {{ color: #66ccff; text-decoration: none; margin: 0 10px; }}
            .channel-links a:hover {{ text-decoration: underline; }}
            .loading-message {{ margin-top: 20px; font-style: italic; color: #bbb; }}
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
@flask_app.route('/_serve_media')
async def serve_media():
    terabox_link = request.args.get('url')
    action = request.args.get('action') # 'stream' or 'download'

    if not terabox_link or not action:
        return jsonify({"error": "Missing 'url' or 'action' parameter"}), 400

    # Generate a unique filename for the downloaded video
    unique_id = hashlib.md5(terabox_link.encode()).hexdigest()
    
    filepath = None
    try:
        # Check if file already exists in cache
        cached_files = [f for f in os.listdir(DOWNLOAD_CACHE_DIR) if f.startswith(unique_id)]
        if cached_files:
            filepath = os.path.join(DOWNLOAD_CACHE_DIR, cached_files[0])
            logger.info(f"Serving from cache: {filepath}")
        else:
            # File not in cache, download it
            temp_filepath_template = os.path.join(DOWNLOAD_CACHE_DIR, f'{unique_id}_%(title)s.%(ext)s')
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
            logger.info(f"Successfully downloaded to: {filepath}")

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
        logger.error(f"Error serving media for {terabox_link}: {e}")
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

# --- Bot Handlers ---
@app.on_message(filters.command("start"))
async def start_command(client, message):
    await message.reply_text(
        "👋 नमस्ते! मैं टेराबॉक्स वीडियो डाउनलोडर बॉट हूँ. "
        "मुझे कोई भी टेराबॉक्स लिंक भेजो और मैं उसे डाउनलोड करके तुम्हें दूंगा!\n\n"
        "अपनी डाउनलोड लिमिट जानने के लिए /limit दबाएं. "
        "प्रीमियम प्लान्स देखने के लिए /premium दबाएं.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💎 प्रीमियम प्लान्स", callback_data="premium_plans")],
            [InlineKeyboardButton("⚙️ बॉट स्टैट्स", callback_data="bot_stats_menu")]
        ])
    )

@app.on_message(filters.command("limit"))
async def limit_command(client, message):
    user_id = message.from_user.id
    user = await get_user_data(user_id)
    is_premium = user.get("is_premium", False)
    daily_downloads = user.get("daily_downloads", 0)

    status_text = ""
    if is_premium:
        status_text = "✨ आप एक **प्रीमियम उपयोगकर्ता** हैं! आपकी कोई दैनिक डाउनलोड सीमा नहीं है."
    else:
        remaining = FREE_DOWNLOAD_LIMIT - daily_downloads
        status_text = (
            f"📊 आपकी आज की डाउनलोड लिमिट: **{FREE_DOWNLOAD_LIMIT}**\n"
            f"⬇️ आज डाउनलोड किए गए: **{daily_downloads}**\n"
            f"✅ शेष डाउनलोड: **{remaining}**\n\n"
            "ज़्यादा डाउनलोड के लिए प्रीमियम प्लान्स देखें: /premium"
        )
    await message.reply_text(status_text)

@app.on_message(filters.command("premium"))
async def premium_command(client, message):
    await message.reply_text(
        "💎 **हमारे प्रीमियम प्लान्स:**\n\n"
        "✨ **अनलिमिटेड डाउनलोड:** कोई दैनिक सीमा नहीं!\n"
        "⚡️ **तेज़ डाउनलोड स्पीड:** हाई-स्पीड सर्वर!\n"
        "🚫 **कोई विज्ञापन नहीं:** बिना रुकावट डाउनलोड अनुभव!\n\n"
        "अभी प्रीमियम खरीदें और बेहतरीन अनुभव पाएं!\n\n"
        "अधिक जानकारी के लिए @आपके_एडमिन_का_यूज़रनेम से संपर्क करें.", # Replace with your admin's username
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💎 प्रीमियम खरीदें", url="https://t.me/asbhai_bsr")], # Replace with your contact/payment link
            [InlineKeyboardButton("🔙 वापस", callback_data="start_menu")]
        ])
    )

@app.on_callback_query()
async def callback_handler(client, callback_query):
    query = callback_query.data
    user_id = callback_query.from_user.id

    if query == "premium_plans":
        await callback_query.message.edit_text(
            "💎 **हमारे प्रीमियम प्लान्स:**\n\n"
            "✨ **अनलिमिटेड डाउनलोड:** कोई दैनिक सीमा नहीं!\n"
            "⚡️ **तेज़ डाउनलोड स्पीड:** हाई-स्पीड सर्वर!\n"
            "🚫 **कोई विज्ञापन नहीं:** बिना रुकावट डाउनलोड अनुभव!\n\n"
            "अभी प्रीमियम खरीदें और बेहतरीन अनुभव पाएं!\n\n"
            "अधिक जानकारी के लिए @आपके_एडमिन_का_यूज़रनेम से संपर्क करें.", # Replace with your admin's username
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 प्रीमियम खरीदें", url="https://t.me/asbhai_bsr")], # Replace with your contact/payment link
                [InlineKeyboardButton("🔙 वापस", callback_data="start_menu")]
            ])
        )
    elif query == "start_menu":
        await callback_query.message.edit_text(
            "👋 नमस्ते! मैं टेराबॉक्स वीडियो डाउनलोडर बॉट हूँ. "
            "मुझे कोई भी टेराबॉक्स लिंक भेजो और मैं उसे डाउनलोड करके तुम्हें दूंगा!\n\n"
            "अपनी डाउनलोड लिमिट जानने के लिए /limit दबाएं. "
            "प्रीमियम प्लान्स देखने के लिए /premium दबाएं.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 प्रीमियम प्लान्स", callback_data="premium_plans")],
                [InlineKeyboardButton("⚙️ बॉट स्टैट्स", callback_data="bot_stats_menu")]
            ])
        )
    elif query == "bot_stats_menu":
        total_users = await users_collection.count_documents({})
        premium_users = await users_collection.count_documents({"is_premium": True})
        total_downloads_sum = await users_collection.aggregate([{"$group": {"_id": None, "total": {"$sum": "$total_downloads"}}}]).to_list(1)
        total_downloads = total_downloads_sum[0]["total"] if total_downloads_sum else 0

        stats_text = (
            f"📊 **बॉट स्टैटिस्टिक्स:**\n\n"
            f"👤 कुल उपयोगकर्ता: **{total_users}**\n"
            f"💎 प्रीमियम उपयोगकर्ता: **{premium_users}**\n"
            f"⬇️ कुल डाउनलोड: **{total_downloads}**\n\n"
            "यह डेटा हर दिन अपडेट होता है."
        )
        await callback_query.message.edit_text(
            stats_text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 वापस", callback_data="start_menu")]
            ])
        )
    # No need for download_quality_ callbacks here as we are using web streaming

    await callback_query.answer()


@app.on_message(filters.regex(r"(?i)https?://(?:www\.)?(terabox|nephobox|kofile|mirrobox|momoradar|www.4funbox\.com|www.sukifiles\.com|www.terabox\.com|www.teraboxapp\.com|teraboxapp\.com|terabox\.com|www.4hfile\.com|www.rapidgator\.net|www.kufile\.net|www.pandafiles\.com|www.subyshare\.com|www.filepress\.com|filepress\.com|m.terabox\.com)\.(com|app|net|cc|co|xyz|me|live|cloud|jp|ru|io|pw|site|online|ga|ml|tk|ai|info|store|shop|org|biz|club|fun|pro|sbs|digital|solutions|host|website|tech|dev|page|buzz|guru|news|press|top|blog|art|media|zone|icu|wiki|photos|tube|games|social|group|network|link|center|studio|design|agency|market|events|gallery|house|land|life|today|world|city|estate|fund|gold|health|inc|solutions|systems|tools|ventures|vodka|wedding|work|yoga|zone|academy|accountant|ad|ads|agency|ai|air|apartments|app|archi|associates|attorney|au|band|bar|bargains|beer|best|bid|bike|bio|biz|black|blog|blue|boutique|build|builders|business|cab|cafe|cam|camera|camp|capital|car|cards|care|careers|casa|cash|casino|catering|cc|center|ceo|church|city|claims|cleaning|clinic|clothing|cloud|coach|codes|coffee|college|community|company|computer|condos|construction|consulting|contractors|cool|coupons|credit|creditcard|cruises|dad|dance|data|date|deals|delivery|democrat|dental|design|diamonds|diet|digital|direct|directory|discount|doctor|dog|domains|education|email|energy|engineer|engineering|enterprises|equipment|estate|events|exchange|expert|express|faith|family|fan|farm|fashion|film|finance|financial|firm|fitness|flights|florist|flowers|football|forsale|foundation|fund|furniture|fyi|gallery|games|garden|gay|gent|gifts|gives|glass|global|gold|golf|graphics|gratis|green|gripe|guide|guitars|guru|haus|health|healthcare|help|here|hiphop|holdings|holiday|homes|horse|host|hosting|house|how|id|industries|info|ink|institute|insurance|insure|international|investments|irish|is|jetzt|jewelry|job|jobs|join|juegos|kaufen|kim|kitchen|land|lease|legal|lgbt|life|lighting|limited|live|llc|loan|loans|lol|london|ltd|maison|management|marketing|mba|media|memorial|men|menu|mobi|moda|moe|money|mortgage|mov|movie|museum|name|navy|network|new|news|ninja|nyc|okinawa|one|online|ooo|organic|partners|parts|party|photo|photography|photos|pics|pictures|pink|pizza|place|plumbing|plus|poker|porn|press|pro|productions|prof|properties|property|pub|qa|quebec|racing|recipes|red|rehab|reise|reisen|rent|rentals|repair|report|republican|restaurant|reviews|rip|rocks|rodeo|run|sarl|school|schule|science|scot|security|services|sex|sexy|shiksha|shoes|shop|shopping|show|singles|site|ski|soccer|social|software|solar|solutions|soy|space|studio|style|sucks|supplies|supply|support|surf|surgery|sydney|systems|tax|taxi|team|tech|technology|tel|telecom|tennis|theater|tickets|tienda|tips|tires|today|tools|tours|town|toys|trade|training|travel|tube|university|uno|vacations|ventures|vet|viajes|video|villas|vin|vision|vodka|vote|voting|voto|voyage|wales|wang|watch|webcam|website|wed|wedding|whoswho|wiki|win|wine|work|works|world|wtf|xyz|yachts|ye|yoga|zara)/[a-zA-Z0-9]+", filters.private))
async def handle_terabox_link(client, message):
    user_id = message.from_user.id
    terabox_link = message.text
    user = await get_user_data(user_id)

    is_premium = await check_premium_status(user_id)
    today = datetime.date.today()

    if user.get("last_download_date") is None or user["last_download_date"].date() != today:
        await update_user_data(user_id, {"daily_downloads": 0, "last_download_date": datetime.datetime.now()})
        user = await get_user_data(user_id)

    if not is_premium and user["daily_downloads"] >= FREE_DOWNLOAD_LIMIT:
        await message.reply_text(
            f"🚫 ओह नो! आपकी आज की {FREE_DOWNLOAD_LIMIT} डाउनलोड लिमिट पूरी हो गई है. "
            "ज़्यादा डाउनलोड के लिए प्रीमियम ले लो या कल फिर ट्राई करना!"
            "\n\n💎 प्रीमियम प्लान्स देखने के लिए /premium दबाएं.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 प्रीमियम प्लान्स", callback_data="premium_plans")],
                [InlineKeyboardButton("🆘 मदद चाहिए?", callback_data="help_menu")]
            ])
        )
        return

    status_message = await message.reply_text(
        f"🔗 लिंक मिल गया! मैं इसे स्कैन कर रहा हूँ, रुको ज़रा... "
        f"(`{terabox_link}`)\n\n"
        "यह प्रक्रिया थोड़ी देर ले सकती है, धैर्य रखें."
    )

    try:
        ydl_opts = {
            'format': 'best', 
            'noplaylist': True,
            'verbose': False,
            'quiet': True,
            'no_warnings': True,
            'skip_download': True, # Only extract info, don't download yet
        }

        info_dict = None
        with YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(terabox_link, download=False)
            if not info_dict:
                raise Exception("Could not extract info from the link.")

        await update_user_data(user_id, {
            "$inc": {"daily_downloads": 1, "total_downloads": 1}
        })

        video_title = info_dict.get('title', 'Video')
        video_thumbnail = info_dict.get('thumbnail')
        
        estimated_size_bytes = 0
        if 'formats' in info_dict:
            best_format = next((f for f in info_dict['formats'] if f.get('vcodec') != 'none' and f.get('acodec') != 'none'), None)
            if best_format and best_format.get('filesize'):
                estimated_size_bytes = best_format['filesize']
            elif best_format and best_format.get('filesize_approx'):
                estimated_size_bytes = best_format['filesize_approx']
        
        estimated_size_mb = estimated_size_bytes / (1024 * 1024) if estimated_size_bytes else 0

        encoded_terabox_link = urllib.parse.quote_plus(terabox_link)
        encoded_video_title = urllib.parse.quote_plus(video_title)

        # Construct the URL that points to the Flask web server's HTML viewer page
        # Since Flask is running within the same process, we can use relative path or base URL
        # Koyeb will expose it on its main URL
        media_viewer_url = f"{os.environ.get('KOYEB_PUBLIC_URL', 'http://localhost:5000')}/view_media?url={encoded_terabox_link}&title={encoded_video_title}"

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("▶️ स्ट्रीम / ⬇️ डाउनलोड", url=media_viewer_url)
                ],
                [
                    InlineKeyboardButton("🔙 वापस", callback_data="start_menu")
                ]
            ]
        )
        
        caption_text = (
            f"🎥 **FILENAME** : `{video_title}`\n"
            f"📏 **SIZE** : `{estimated_size_mb:.2f} MB` (अनुमानित)\n\n"
            f"यह मीडिया सीधे हमारे सर्वर से स्ट्रीम या डाउनलोड किया जाएगा। "
            f"बटन पर क्लिक करें!"
        )

        if video_thumbnail:
            try:
                await client.send_photo(
                    chat_id=message.chat.id,
                    photo=video_thumbnail,
                    caption=caption_text,
                    reply_markup=keyboard
                )
            except Exception as photo_e:
                logger.warning(f"Could not send photo thumbnail: {photo_e}. Sending text message instead.")
                await client.send_message(
                    chat_id=message.chat.id,
                    text=caption_text,
                    reply_markup=keyboard
                )
        else:
            await client.send_message(
                chat_id=message.chat.id,
                text=caption_text,
                reply_markup=keyboard
            )
        
        await status_message.delete()

    except Exception as e:
        logger.error(f"Error extracting info or creating links from Terabox link {terabox_link}: {e}")
        if "unable to extract" in str(e).lower() or "no appropriate format" in str(e).lower() or "Video unavailable" in str(e).lower():
             await client.send_message(
                 ADMIN_ID,
                 f"🚨 **एडमिन अलर्ट:** टेराबॉक्स डाउनलोड विधि में कुछ बदलाव हुआ लगता है! "
                 f"लिंक `{terabox_link}` से जानकारी नहीं निकाल पाया. "
                 f"एरर: `{e}`. कृपया कोड जांचें."
             )
        await status_message.edit_text(
            f"😥 ओह! इस लिंक से वीडियो नहीं मिल रहा है या कुछ गड़बड़ हो गई है. "
            "कृपया सही टेराबॉक्स लिंक भेजें या बाद में कोशिश करें.\n\n"
            f"**एरर:** `{e}`"
        )


# --- Main Runner for Bot and Flask ---
async def main():
    # Start the Pyrogram bot
    await app.start()
    logger.info("Pyrogram Bot started!")

    # Setup Hypercorn for Flask
    config = Config()
    config.bind = [f"0.0.0.0:{os.environ.get('PORT', '5000')}"]
    
    # Run Flask app with Hypercorn inside the asyncio loop
    # Use a separate task for Hypercorn
    flask_task = asyncio.create_task(serve(flask_app, config))
    logger.info(f"Flask Web Server starting on port {os.environ.get('PORT', '5000')}...")

    # Keep the bot running
    await idle()
    
    # Stop the Flask task when bot stops
    flask_task.cancel()
    await app.stop()
    logger.info("Pyrogram Bot stopped.")
    logger.info("Flask Web Server stopped.")

if __name__ == "__main__":
    # Run the main async function
    asyncio.run(main())
