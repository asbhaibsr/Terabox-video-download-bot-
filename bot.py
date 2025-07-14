import os
import re
import logging
import requests
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from datetime import datetime
import uuid
from bs4 import BeautifulSoup
from flask import Flask, jsonify, send_file, abort
import threading
import asyncio
from concurrent.futures import ThreadPoolExecutor

# Import yt_dlp
try:
    import yt_dlp
except ImportError:
    logging.error("yt_dlp is not installed. Please install it using 'pip install yt-dlp'")
    exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app for health checks
flask_app = Flask(__name__)
PORT = int(os.getenv("PORT", 8080))

# Thread pool for blocking operations like yt-dlp download
executor = ThreadPoolExecutor(max_workers=5) # Adjust as needed

# Bot configuration
API_ID = int(os.getenv("API_ID", 12345))
API_HASH = os.getenv("API_HASH", "your_api_hash_here")
BOT_TOKEN = os.getenv("BOT_TOKEN", "your_bot_token_here")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
SUPPORT_GROUP = "aschat_group"
UPDATE_CHANNEL = "asbhai_bsr"
ADMIN_ID = 7315805581
DAILY_FREE_LIMIT = 5
DOWNLOAD_DIR = "downloads" # Directory to store downloaded files

# !!! IMPORTANT !!!
# Replace this with your actual Koyeb app URL (the base URL)
# Example: https://your-app-name.koyeb.app/
DOWNLOAD_BASE_URL = os.getenv("DOWNLOAD_BASE_URL", "https://remarkable-nonna-arsadsaifi784-f815332b.koyeb.app/")
if not DOWNLOAD_BASE_URL.endswith('/'):
    DOWNLOAD_BASE_URL += '/'

# Create download directory if it doesn't exist
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Initialize MongoDB
try:
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client["terabox_bot"]
    users_col = db["users"]
    files_col = db["downloadable_files"] # Collection to store info about downloadable files
    logger.info("Connected to MongoDB")
except Exception as e:
    logger.error(f"MongoDB connection error: {e}")
    raise

# Initialize Pyrogram client
app = Client("terabox_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Flask Routes for Health Check and File Serving
@flask_app.route('/')
def health_check():
    return jsonify({"status": "ok", "message": "Terabox Downloader Bot is running"})

@flask_app.route('/download/<file_id>/<filename>')
async def serve_file(file_id, filename):
    file_info = files_col.find_one({"_id": file_id})
    
    if not file_info:
        logger.warning(f"File ID not found in DB: {file_id}")
        abort(404, description="File not found or expired.")

    file_path = file_info.get("file_path")
    
    if not file_path or not os.path.exists(file_path):
        logger.warning(f"File not found on disk or path missing: {file_path}")
        # Remove from DB if file is missing from disk
        files_col.delete_one({"_id": file_id}) 
        abort(404, description="File not found or expired. Please request again.")

    logger.info(f"Serving file: {file_path}")
    try:
        # We use a non-blocking way to send file if possible, or use a separate thread
        # Flask's send_file is usually blocking, but this setup allows other async ops
        return await asyncio.to_thread(send_file, file_path, as_attachment=True, download_name=filename)
    except Exception as e:
        logger.error(f"Error serving file {file_path}: {e}")
        abort(500, description="Error serving file.")

def run_flask():
    flask_app.run(host='0.0.0.0', port=PORT)

# Start Flask server in a separate thread
threading.Thread(target=run_flask, daemon=True).start()


# Terabox Downloader Function with multiple API fallbacks
async def download_terabox_file_api(url):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        }
        
        # List of available APIs to try (in order of preference)
        apis = [
            {
                "url": f"https://terabox-dl.qtcloud.workers.dev/api?url={url}",
                "key": "download_url",
                "name_key": "file_name",
                "size_key": "file_size"
            },
            {
                "url": f"https://terabox-downloader.sanskar.workers.dev/?url={url}",
                "key": "downloadLink",
                "name_key": "fileName",
                "size_key": "fileSize"
            },
            {
                "url": f"https://youtube4kdownloader.com/terabox-downloader/?url={url}",
                "parser": "html",  # This one requires HTML parsing
                "element": {"class": "download-btn"},
                "attr": "href"
            }
        ]
        
        for api in apis:
            try:
                # Use requests directly, not inside asyncio.to_thread unless it's blocking
                response = requests.get(api["url"], headers=headers, timeout=30)
                if api.get("parser") == "html":
                    soup = BeautifulSoup(response.content, "html.parser")
                    download_btn = soup.find("a", api["element"])
                    if download_btn and download_btn.get(api["attr"]):
                        return {
                            "success": True,
                            "download_url": download_btn.get(api["attr"]),
                            "file_name": "terabox_file",
                            "file_size": "N/A"
                        }
                else:
                    if response.status_code == 200:
                        data = response.json()
                        if data.get(api["key"]):
                            return {
                                "success": True,
                                "download_url": data[api["key"]],
                                "file_name": data.get(api.get("name_key", "file_name"), "terabox_file"),
                                "file_size": data.get(api.get("size_key", "file_size"), "N/A")
                            }
            except Exception as api_error:
                logger.warning(f"API {api['url']} failed: {api_error}")
                continue
        
        return {"success": False, "error": "All API download methods failed. Please try again later."}
    except Exception as e:
        logger.error(f"Terabox API download error: {e}")
        return {"success": False, "error": str(e)}

# Function to extract info and download using yt-dlp (now saves to disk)
async def get_info_and_download_ytdlp(url, message_to_edit):
    file_id = str(uuid.uuid4())
    filepath = os.path.join(DOWNLOAD_DIR, file_id + "_%(title)s.%(ext)s")
    
    # Store message_to_edit and url for progress hook to access
    message_to_edit.current_url = url 
    message_to_edit.file_id = file_id # Store file_id in message object
    
    ydl_opts = {
        'format': 'best',
        'outtmpl': filepath,
        'merge_output_format': 'mp4',
        'noplaylist': True,
        'verbose': False, # Keep verbose False for production
        'quiet': True,
        'no_warnings': True,
        'progress_hooks': [lambda d: asyncio.create_task(progress_hook(d, message_to_edit))]
    }

    loop = asyncio.get_running_loop()
    try:
        # Run the blocking yt_dlp operation in a separate thread
        info = await loop.run_in_executor(executor, lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(url, download=True))
        
        final_filepath = None
        if 'entries' in info: # for playlists or multiple videos, take the first
            final_filepath = yt_dlp.YoutubeDL(ydl_opts).prepare_filename(info['entries'][0])
        else:
            final_filepath = yt_dlp.YoutubeDL(ydl_opts).prepare_filename(info)
        
        # Ensure correct extension after merge
        if ydl_opts['merge_output_format'] and not final_filepath.endswith(ydl_opts['merge_output_format']):
            final_filepath = f"{os.path.splitext(final_filepath)[0]}.{ydl_opts['merge_output_format']}"

        if not os.path.exists(final_filepath):
            raise FileNotFoundError(f"Downloaded file not found at {final_filepath}")

        # Get file size
        file_size_bytes = os.path.getsize(final_filepath)
        file_size_hr = human_readable_size(file_size_bytes)
        
        # Get thumbnail
        thumbnail_url = None
        if 'thumbnails' in info and info['thumbnails']:
            # Find the largest thumbnail
            thumbnail_url = max(info['thumbnails'], key=lambda x: x.get('width', 0) * x.get('height', 0)).get('url')
        elif info.get('thumbnail'):
            thumbnail_url = info['thumbnail']

        # Store file info in MongoDB for serving
        files_col.insert_one({
            "_id": file_id,
            "file_path": final_filepath,
            "original_url": url,
            "file_name": info.get('title', 'terabox_video'),
            "file_size": file_size_hr,
            "created_at": datetime.now(),
            "expires_at": datetime.now() + timedelta(hours=2) # Link expires after 2 hours (adjust as needed)
        })

        return {
            "success": True,
            "file_id": file_id,
            "file_name": info.get('title', 'terabox_video'),
            "file_size": file_size_hr,
            "thumbnail_url": thumbnail_url,
            "original_filename_for_download": os.path.basename(final_filepath).split('_', 1)[-1] # Remove UUID prefix
        }
    except Exception as e:
        logger.error(f"yt-dlp info/download error: {e}")
        if os.path.exists(filepath): # If a partial file was created
            os.remove(filepath)
        return {"success": False, "error": str(e)}

# Progress hook for yt-dlp
async def progress_hook(d, message_to_edit):
    if d['status'] == 'downloading':
        total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate')
        downloaded_bytes = d.get('downloaded_bytes', 0)
        
        if total_bytes:
            percentage = (downloaded_bytes / total_bytes) * 100
            status_text = f"⏳ Downloading: {percentage:.2f}% ({human_readable_size(downloaded_bytes)} / {human_readable_size(total_bytes)})"
        else:
            status_text = f"⏳ Downloading: {human_readable_size(downloaded_bytes)}..."
        
        try:
            # Edit the message only if there's a significant change to avoid flood waits
            # Or if it's the first update
            if not hasattr(message_to_edit, 'last_update_time') or \
               (datetime.now() - message_to_edit.last_update_time).total_seconds() > 5: # Update every 5 seconds
                await message_to_edit.edit_text(status_text)
                message_to_edit.last_update_time = datetime.now()
        except Exception:
            pass # Ignore if message is already deleted or too many updates

    elif d['status'] == 'finished':
        try:
            await message_to_edit.edit_text("✅ Download finished! Generating download link...")
        except Exception:
            pass
    elif d['status'] == 'error':
        try:
            await message_to_edit.edit_text("❌ Download failed.")
        except Exception:
            pass

def human_readable_size(size_bytes):
    if size_bytes is None:
        return "N/A"
    size_bytes = float(size_bytes)
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0

@app.on_message(filters.command("start"))
async def start(client, message):
    buttons = [
        [
            InlineKeyboardButton("📢 Updates Channel", url=f"https://t.me/{UPDATE_CHANNEL}"),
            InlineKeyboardButton("👥 Support Group", url=f"https://t.me/{SUPPORT_GROUP}")
        ],
        [InlineKeyboardButton("❓ How to Download", callback_data="help_download")]
    ]
    
    await message.reply_text(
        "👋 Welcome to Terabox Downloader Bot!\n\n"
        "🔗 Send me any Terabox link to download the file\n\n"
        "⚠️ Note: This is free service, download speed may be slow",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@app.on_message(filters.regex(r'https?://[^\s]+'))
async def handle_terabox_link(client, message):
    try:
        user_id = message.from_user.id
        url = message.text
        if "terabox" not in url.lower() and "teraboxapp" not in url.lower():
            await message.reply_text("❌ Please send a valid Terabox link")
            return
        
        # Check daily limit
        user_data = users_col.find_one({"user_id": user_id})
        today = datetime.now().date()
        
        # Reset count if it's a new day
        if user_data and user_data.get("last_download"):
            last_download_date = user_data["last_download"].date()
            if last_download_date < today:
                users_col.update_one({"user_id": user_id}, {"$set": {"download_count": 0}})
                user_data["download_count"] = 0 # Update in-memory data
        
        if user_data and user_data.get("download_count", 0) >= DAILY_FREE_LIMIT:
            await message.reply_text(f"❌ You've reached your daily limit of {DAILY_FREE_LIMIT} downloads. Please try again tomorrow or upgrade for unlimited downloads.")
            return
        
        # Store the URL temporarily for callback queries (use user_id as key)
        temp_storage[user_id] = url 

        # Offer two download options
        buttons = [
            [
                InlineKeyboardButton("⬇️ Fast Download (API)", callback_data=f"download_api_{user_id}"),
                InlineKeyboardButton("⬇️ Stable Download (Library)", callback_data=f"download_ytdlp_{user_id}")
            ],
            [
                InlineKeyboardButton("📢 Updates", url=f"https://t.me/{UPDATE_CHANNEL}"),
                InlineKeyboardButton("👥 Support", url=f"https://t.me/{SUPPORT_GROUP}")
            ]
        ]
        
        await message.reply_text(
            "Choose your download method:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        
    except Exception as e:
        logger.error(f"Error handling Terabox link: {e}")
        await message.reply_text("❌ An error occurred. Please try again later.")

# Temporary storage for URLs (for callback query, should be robust for production)
temp_storage = {}

@app.on_callback_query(filters.regex(r"^(download_api_|download_ytdlp_)(\d+)$"))
async def handle_download_choice(client, callback_query):
    user_id = callback_query.from_user.id
    choice_type = callback_query.data.split('_')[1] # 'api' or 'ytdlp'
    original_user_id = int(callback_query.data.split('_')[2]) # User who initiated the download

    if user_id != original_user_id:
        await callback_query.answer("This button is not for you!", show_alert=True)
        return

    url = temp_storage.pop(user_id, None) # Retrieve and remove the URL
    if not url:
        await callback_query.answer("Error: Link not found. Please send the link again.", show_alert=True)
        return

    await callback_query.answer("Processing your request...")
    processing_msg = await callback_query.message.edit_text("⏳ Processing your Terabox link...")

    download_info = None
    try:
        # Check daily limit again (important for preventing abuse)
        user_data = users_col.find_one({"user_id": user_id})
        today = datetime.now().date()
        
        if user_data and user_data.get("last_download"):
            last_download_date = user_data["last_download"].date()
            if last_download_date < today:
                users_col.update_one({"user_id": user_id}, {"$set": {"download_count": 0}})
                user_data["download_count"] = 0
        
        if user_data and user_data.get("download_count", 0) >= DAILY_FREE_LIMIT:
            await processing_msg.delete()
            await callback_query.message.reply_text(f"❌ You've reached your daily limit of {DAILY_FREE_LIMIT} downloads.")
            return

        if choice_type == "api":
            await processing_msg.edit_text("⏳ Using Fast Download (API method)...")
            download_info = await download_terabox_file_api(url)
            
            if download_info and download_info.get("success"):
                users_col.update_one(
                    {"user_id": user_id},
                    {"$inc": {"download_count": 1}, "$set": {"last_download": datetime.now()}},
                    upsert=True
                )
                file_name = download_info.get("file_name", "file")
                download_url = download_info["download_url"]
                
                await processing_msg.delete()
                await callback_query.message.reply_text(
                    f"✅ Download Ready (API Method)!\n\n"
                    f"📁 File: {file_name}\n"
                    f"📦 Size: {download_info.get('file_size', 'N/A')}\n\n"
                    f"⚠️ Note: Free download links may expire quickly",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⬇️ Download Now", url=download_url)],
                        [
                            InlineKeyboardButton("📢 Updates", url=f"https://t.me/{UPDATE_CHANNEL}"),
                            InlineKeyboardButton("👥 Support", url=f"https://t.me/{SUPPORT_GROUP}")
                        ]
                    ])
                )
            else:
                await processing_msg.delete()
                await callback_query.message.reply_text(f"❌ Error: {download_info.get('error', 'Failed to process link with selected method.')}")

        elif choice_type == "ytdlp":
            await processing_msg.edit_text("⏳ Using Stable Download (Library method)... This might take longer...")
            download_info = await get_info_and_download_ytdlp(url, processing_msg) # Now it downloads the file and stores info
            
            if download_info and download_info.get("success"):
                users_col.update_one(
                    {"user_id": user_id},
                    {"$inc": {"download_count": 1}, "$set": {"last_download": datetime.now()}},
                    upsert=True
                )
                file_id = download_info["file_id"]
                file_name = download_info["file_name"]
                file_size = download_info["file_size"]
                thumbnail_url = download_info["thumbnail_url"]
                original_filename = download_info["original_filename_for_download"]

                # Construct the direct download link using your Koyeb base URL
                direct_download_link = f"{DOWNLOAD_BASE_URL}download/{file_id}/{original_filename}"

                caption_text = (
                    f"✅ Download Ready (Library Method)!\n\n"
                    f"📁 **Title**: {file_name}\n"
                    f"📦 **Size**: {file_size}\n\n"
                    f"⚠️ Note: Download link will expire after some time."
                )
                
                buttons = [
                    [InlineKeyboardButton("⬇️ Download Now", url=direct_download_link)],
                    [
                        InlineKeyboardButton("📢 Updates", url=f"https://t.me/{UPDATE_CHANNEL}"),
                        InlineKeyboardButton("👥 Support", url=f"https://t.me/{SUPPORT_GROUP}")
                    ]
                ]

                # Send photo with caption and button
                if thumbnail_url:
                    try:
                        await client.send_photo(
                            chat_id=user_id,
                            photo=thumbnail_url,
                            caption=caption_text,
                            reply_markup=InlineKeyboardMarkup(buttons)
                        )
                    except Exception as photo_error:
                        logger.warning(f"Failed to send photo thumbnail: {photo_error}. Sending text message instead.")
                        await client.send_message(
                            chat_id=user_id,
                            text=caption_text,
                            reply_markup=InlineKeyboardMarkup(buttons)
                        )
                else:
                    await client.send_message(
                        chat_id=user_id,
                        text=caption_text,
                        reply_markup=InlineKeyboardMarkup(buttons)
                    )
                await processing_msg.delete()
                await callback_query.message.reply_text("✨ Your download link is ready!")

            else:
                await processing_msg.delete()
                await callback_query.message.reply_text(f"❌ Error: {download_info.get('error', 'Failed to process link with selected method.')}")

    except Exception as e:
        logger.error(f"Error in handle_download_choice: {e}")
        if processing_msg:
            await processing_msg.delete()
        await callback_query.message.reply_text("❌ An error occurred during download. Please try again later.")


@app.on_callback_query(filters.regex("^help_download$"))
async def help_download(client, callback_query):
    help_text = (
        "📹 How to Download Videos:\n\n"
        "1. Open Terabox app or website\n"
        "2. Find the video you want to download\n"
        "3. Click 'Share' and copy the link\n"
        "4. Paste that link here in the bot\n"
        "5. Choose your preferred download method (Fast API or Stable Library)\n"
        "6. Wait for processing and either get a direct download link or the file directly!\n\n"
        "For any issues, contact @aschat_group"
    )
    await callback_query.answer()
    await callback_query.message.reply_text(help_text)

if __name__ == "__main__":
    logger.info("Starting Free Terabox Downloader Bot...")
    logger.info(f"Flask health check server running on port {PORT}")
    app.run()
