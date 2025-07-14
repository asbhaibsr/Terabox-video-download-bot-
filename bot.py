import os
import re
import logging
import requests
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from datetime import datetime, timedelta
import uuid
from bs4 import BeautifulSoup
from flask import Flask, jsonify, send_file, abort
import threading
import asyncio
from concurrent.futures import ThreadPoolExecutor

# Important: These libraries were provided by the user.
# Ensure all are installed: pip install pyrogram pymongo beautifulsoup4 flask requests yt-dlp telethon cryptg pyaes aiohttp aiodns pillow hachoir redis FastTelethonhelper humanreadable
import telethon # User provided
import cryptg # User provided
import pyaes # User provided
import aiohttp # User provided
import aiodns # User provided
# aiohttp[speedups] is a dependency, not a direct import
from PIL import Image # User provided, from pillow
import hachoir # User provided
# requests is already used
# redis is a client library, usually imported as `redis`
# FastTelethonhelper - assuming this is a custom helper, no direct import needed unless used
import humanreadable # User provided

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
executor = ThreadPoolExecutor(max_workers=10)

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
# Ensure it ends with a '/'
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
    
    # Check for expiration
    if file_info.get("expires_at") and file_info["expires_at"] < datetime.now():
        logger.warning(f"File expired: {file_id}. Deleting from DB and disk.")
        files_col.delete_one({"_id": file_id})
        if os.path.exists(file_path):
            os.remove(file_path)
        abort(404, description="File link expired. Please request a new one from the bot.")


    if not file_path or not os.path.exists(file_path):
        logger.warning(f"File not found on disk or path missing: {file_path}. Deleting from DB.")
        files_col.delete_one({"_id": file_id}) 
        abort(404, description="File not found or expired. Please request again.")

    logger.info(f"Serving file: {file_path}")
    try:
        return await asyncio.to_thread(send_file, file_path, as_attachment=True, download_name=filename)
    except Exception as e:
        logger.error(f"Error serving file {file_path}: {e}")
        abort(500, description="Error serving file.")

def run_flask():
    flask_app.run(host='0.0.0.0', port=PORT)

# Start Flask server in a separate thread
threading.Thread(target=run_flask, daemon=True).start()


# --- Core Terabox Link Resolution Function ---
# This function is crucial and needs working APIs.
# It tries to get the direct video URL from a Terabox sharing link.
async def resolve_terabox_link_to_direct_url(terabox_url):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        }
        
        # IMPORTANT: Replace these with CURRENTLY WORKING Terabox direct link APIs.
        # These are examples and might not work. You NEED to find active ones.
        # Always prioritize official/community-maintained APIs if possible.
        # Example API URLs - You MUST VERIFY and UPDATE these!
        apis = [
            # Example 1: Known public Terabox DL worker. Often works, but can be rate-limited or go down.
            {
                "url": f"https://terabox-dl.qtcloud.workers.dev/api?url={terabox_url}",
                "key": "download_url",
                "name_key": "file_name",
                "size_key": "file_size"
            },
            # Example 2: Another worker URL. Check if it's active.
            {
                "url": f"https://terabox-downloader.sanskar.workers.dev/?url={terabox_url}",
                "key": "downloadLink",
                "name_key": "fileName",
                "size_key": "fileSize"
            },
            # Example 3: You might find others on GitHub or forums.
            # {
            #     "url": f"https://api.example.com/terabox?link={terabox_url}",
            #     "key": "url", # Or 'direct_link', 'video_url', etc.
            #     "name_key": "title",
            #     "size_key": "size"
            # },
            # Example 4: HTML parsing API (less common for direct links, but possible)
            # {
            #     "url": f"https://some-html-parser.com/terabox/?url={terabox_url}",
            #     "parser": "html",
            #     "element": {"id": "download_button"}, # Find the correct element selector
            #     "attr": "href" # Attribute containing the URL
            # }
        ]
        
        for api in apis:
            try:
                logger.info(f"Trying API: {api.get('url', 'N/A').split('?')[0]}...")
                # Use aiohttp for asynchronous requests
                async with aiohttp.ClientSession() as session:
                    async with session.get(api["url"], headers=headers, timeout=30) as response:
                        if api.get("parser") == "html":
                            html_content = await response.text()
                            soup = BeautifulSoup(html_content, "html.parser")
                            download_btn = soup.find("a", api["element"])
                            if download_btn and download_btn.get(api["attr"]):
                                logger.info(f"HTML API success: {api['url']}")
                                return {
                                    "success": True,
                                    "direct_url": download_btn.get(api["attr"]),
                                    "file_name": "terabox_file",
                                    "file_size": "N/A"
                                }
                        else:
                            if response.status == 200:
                                data = await response.json()
                                direct_url = data.get(api["key"]) or data.get("url") or data.get("direct_link") or data.get("link")
                                if direct_url:
                                    logger.info(f"JSON API success: {api['url']}")
                                    return {
                                        "success": True,
                                        "direct_url": direct_url,
                                        "file_name": data.get(api.get("name_key"), "terabox_file"),
                                        "file_size": data.get(api.get("size_key"), "N/A")
                                    }
            except Exception as api_error:
                logger.warning(f"API {api.get('url', 'N/A').split('?')[0]} failed: {api_error}")
                continue # Try the next API
        
        return {"success": False, "error": "All configured APIs failed to resolve the Terabox link. Please try again later or provide working APIs."}
    except Exception as e:
        logger.error(f"Error in resolving Terabox link: {e}")
        return {"success": False, "error": str(e)}

# Function to download the resolved direct URL using yt-dlp and store it locally
async def download_file_and_get_info_ytdlp(source_url, message_to_edit):
    file_id = str(uuid.uuid4())
    filepath_template = os.path.join(DOWNLOAD_DIR, file_id + "_%(title)s.%(ext)s") 
    
    message_to_edit.file_id = file_id # Store file_id in message object
    
    ydl_opts = {
        'format': 'best',
        'outtmpl': filepath_template,
        'merge_output_format': 'mp4',
        'noplaylist': True,
        'verbose': False,
        'quiet': True,
        'no_warnings': True,
        'progress_hooks': [lambda d: asyncio.create_task(progress_hook(d, message_to_edit))]
    }

    loop = asyncio.get_running_loop()
    final_filepath = None
    try:
        info = await loop.run_in_executor(executor, lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(source_url, download=True))
        
        if 'entries' in info: 
            final_filepath = yt_dlp.YoutubeDL(ydl_opts).prepare_filename(info['entries'][0])
        else:
            final_filepath = yt_dlp.YoutubeDL(ydl_opts).prepare_filename(info)
        
        if ydl_opts['merge_output_format'] and not final_filepath.endswith(ydl_opts['merge_output_format']):
            final_filepath_check = f"{os.path.splitext(final_filepath)[0]}.{ydl_opts['merge_output_format']}"
            if os.path.exists(final_filepath_check):
                final_filepath = final_filepath_check
            else:
                possible_files = [f for f in os.listdir(DOWNLOAD_DIR) if f.startswith(file_id)]
                if possible_files:
                    final_filepath = os.path.join(DOWNLOAD_DIR, possible_files[0])


        if not os.path.exists(final_filepath):
            raise FileNotFoundError(f"Downloaded file not found at {final_filepath}")

        file_size_bytes = os.path.getsize(final_filepath)
        file_size_hr = human_readable_size(file_size_bytes)
        
        thumbnail_url = None
        if 'thumbnails' in info and info['thumbnails']:
            thumbnail_url = max(info['thumbnails'], key=lambda x: x.get('width', 0) * x.get('height', 0) if x.get('width') and x.get('height') else 0).get('url')
        elif info.get('thumbnail'):
            thumbnail_url = info['thumbnail']

        files_col.insert_one({
            "_id": file_id,
            "file_path": final_filepath,
            "original_source_url": source_url, # Changed from original_direct_url
            "file_name": info.get('title', 'video_file'),
            "file_size": file_size_hr,
            "created_at": datetime.now(),
            "expires_at": datetime.now() + timedelta(hours=6)
        })

        return {
            "success": True,
            "file_id": file_id,
            "file_name": info.get('title', 'video_file'),
            "file_size": file_size_hr,
            "thumbnail_url": thumbnail_url,
            "original_filename_for_download": os.path.basename(final_filepath).split('_', 1)[-1]
        }
    except Exception as e:
        logger.error(f"yt-dlp download and info extraction error for {source_url}: {e}")
        if final_filepath and os.path.exists(final_filepath):
            os.remove(final_filepath)
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
            if not hasattr(message_to_edit, 'last_update_time') or \
               (datetime.now() - message_to_edit.last_update_time).total_seconds() > 5:
                await message_to_edit.edit_text(status_text)
                message_to_edit.last_update_time = datetime.now()
        except Exception:
            pass

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
        "🔗 Send me any Terabox link, or use /download_other to download videos from YouTube, etc.\n\n"
        "⚠️ Note: This is free service, download speed may be slow",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@app.on_message(filters.regex(r'https?://[^\s]+') & filters.incoming)
async def handle_any_link(client, message):
    url = message.text
    if "terabox" in url.lower() or "teraboxapp" in url.lower():
        # Handle Terabox links
        try:
            user_id = message.from_user.id
            
            # Check daily limit
            user_data = users_col.find_one({"user_id": user_id})
            today = datetime.now().date()
            
            if user_data and user_data.get("last_download"):
                last_download_date = user_data["last_download"].date()
                if last_download_date < today:
                    users_col.update_one({"user_id": user_id}, {"$set": {"download_count": 0}})
                    user_data["download_count"] = 0
            
            if user_data and user_data.get("download_count", 0) >= DAILY_FREE_LIMIT:
                await message.reply_text(f"❌ You've reached your daily limit of {DAILY_FREE_LIMIT} downloads. Please try again tomorrow or upgrade for unlimited downloads.")
                return
            
            temp_storage[user_id] = url 

            buttons = [
                [
                    InlineKeyboardButton("⬇️ Fast Download (API Link)", callback_data=f"download_terabox_api_{user_id}"),
                    InlineKeyboardButton("⬇️ Stable Download (Koyeb Link)", callback_data=f"download_terabox_koyeb_{user_id}")
                ],
                [
                    InlineKeyboardButton("📢 Updates", url=f"https://t.me/{UPDATE_CHANNEL}"),
                    InlineKeyboardButton("👥 Support", url=f"https://t.me/{SUPPORT_GROUP}")
                ]
            ]
            
            await message.reply_text(
                "Choose your Terabox download method:",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
            
        except Exception as e:
            logger.error(f"Error handling Terabox link: {e}")
            await message.reply_text("❌ An error occurred. Please try again later.")
    else:
        # If it's not a Terabox link, offer to download it using yt-dlp (Other Videos)
        await message.reply_text(
            "This doesn't seem like a Terabox link. Do you want to download it using our 'Other Video Download' feature (YouTube, etc.)?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Yes, Download This", callback_data=f"download_other_confirm_{message.from_user.id}_{url}")],
                [InlineKeyboardButton("❌ No, Ignore", callback_data="ignore_link")]
            ])
        )

@app.on_message(filters.command("download_other") & filters.text)
async def command_download_other(client, message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply_text("Please provide a video link after the command. \nExample: `/download_other https://youtube.com/watch?v=your_video`")
        return
    
    url = args[1]
    user_id = message.from_user.id

    # Check daily limit
    user_data = users_col.find_one({"user_id": user_id})
    today = datetime.now().date()
    
    if user_data and user_data.get("last_download"):
        last_download_date = user_data["last_download"].date()
        if last_download_date < today:
            users_col.update_one({"user_id": user_id}, {"$set": {"download_count": 0}})
            user_data["download_count"] = 0
    
    if user_data and user_data.get("download_count", 0) >= DAILY_FREE_LIMIT:
        await message.reply_text(f"❌ You've reached your daily limit of {DAILY_FREE_LIMIT} downloads. Please try again tomorrow or upgrade for unlimited downloads.")
        return

    # Call the download handler for other videos
    await handle_other_video_download(client, message, url, user_id)


# Temporary storage for URLs (for callback query, should be robust for production)
temp_storage = {}

@app.on_callback_query(filters.regex(r"^(download_terabox_api_|download_terabox_koyeb_)(\d+)$"))
async def handle_terabox_download_choice(client, callback_query):
    user_id = callback_query.from_user.id
    choice_parts = callback_query.data.split('_')
    choice_type = choice_parts[2] # 'api' or 'koyeb'
    original_user_id = int(choice_parts[3])

    if user_id != original_user_id:
        await callback_query.answer("This button is not for you!", show_alert=True)
        return

    url = temp_storage.pop(user_id, None)
    if not url:
        await callback_query.answer("Error: Link not found. Please send the link again.", show_alert=True)
        return

    await callback_query.answer("Processing your request...")
    processing_msg = await callback_query.message.edit_text("⏳ Processing your Terabox link...")

    try:
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

        # --- Resolve Terabox link to Direct URL first for both methods ---
        await processing_msg.edit_text("⏳ Resolving Terabox link to direct video URL...")
        resolved_info = await resolve_terabox_link_to_direct_url(url)
        
        if not resolved_info["success"]:
            await processing_msg.delete()
            await callback_query.message.reply_text(f"❌ Failed to get direct video URL: {resolved_info['error']}")
            return

        direct_video_url = resolved_info["direct_url"]
        
        users_col.update_one(
            {"user_id": user_id},
            {"$inc": {"download_count": 1}, "$set": {"last_download": datetime.now()}},
            upsert=True
        )

        if choice_type == "api":
            await processing_msg.delete()
            await callback_query.message.reply_text(
                f"✅ Direct Download Link (API Method)!\n\n"
                f"📁 File: {resolved_info.get('file_name', 'terabox_file')}\n"
                f"📦 Size: {resolved_info.get('file_size', 'N/A')}\n\n"
                f"⚠️ Note: This link is provided by an external API and may expire quickly.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬇️ Download Now", url=direct_video_url)],
                    [
                        InlineKeyboardButton("📢 Updates", url=f"https://t.me/{UPDATE_CHANNEL}"),
                        InlineKeyboardButton("👥 Support", url=f"https://t.me/{SUPPORT_GROUP}")
                    ]
                ])
            )

        elif choice_type == "koyeb":
            await processing_msg.edit_text("⏳ Downloading file to server (Koyeb Hosted)... This might take longer...")
            download_result = await download_file_and_get_info_ytdlp(direct_video_url, processing_msg)
            
            if download_result and download_result.get("success"):
                file_id = download_result["file_id"]
                file_name = download_result["file_name"]
                file_size = download_result["file_size"]
                thumbnail_url = download_result["thumbnail_url"]
                original_filename = download_result["original_filename_for_download"]

                direct_download_link_koyeb = f"{DOWNLOAD_BASE_URL}download/{file_id}/{original_filename}"

                caption_text = (
                    f"✅ Download Ready (Koyeb Hosted)!\n\n"
                    f"📁 **Title**: {file_name}\n"
                    f"📦 **Size**: {file_size}\n\n"
                    f"⚠️ Note: Download link will expire after some time."
                )
                
                buttons = [
                    [InlineKeyboardButton("⬇️ Download Now", url=direct_download_link_koyeb)],
                    [
                        InlineKeyboardButton("📢 Updates", url=f"https://t.me/{UPDATE_CHANNEL}"),
                        InlineKeyboardButton("👥 Support", url=f"https://t.me/{SUPPORT_GROUP}")
                    ]
                ]

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
                await callback_query.message.reply_text("✨ Your Koyeb hosted download link is ready!")

            else:
                await processing_msg.delete()
                await callback_query.message.reply_text(f"❌ Error during Koyeb hosted download: {download_result.get('error', 'Failed to download to server.')}")

    except Exception as e:
        logger.error(f"Error in handle_terabox_download_choice: {e}")
        if processing_msg:
            await processing_msg.delete()
        await callback_query.message.reply_text("❌ An unexpected error occurred. Please try again later.")

# Handler for 'other_video_download' confirmation from inline button
@app.on_callback_query(filters.regex(r"^download_other_confirm_(\d+)_(.*)$"))
async def handle_other_video_confirm(client, callback_query):
    user_id = callback_query.from_user.id
    original_user_id = int(callback_query.data.split('_')[3])
    url = callback_query.data.split('_', 4)[4] # Re-extract the URL from callback_data

    if user_id != original_user_id:
        await callback_query.answer("This button is not for you!", show_alert=True)
        return
    
    await callback_query.answer("Starting other video download...")
    await callback_query.message.delete() # Delete the confirmation message

    # Now proceed with the actual download
    await handle_other_video_download(client, callback_query.message, url, user_id)


@app.on_callback_query(filters.regex("^ignore_link$"))
async def ignore_link(client, callback_query):
    await callback_query.answer("Link ignored.")
    await callback_query.message.delete()


async def handle_other_video_download(client, message, url, user_id):
    processing_msg = await message.reply_text("⏳ Processing your video link (YouTube, etc.)...")

    try:
        user_data = users_col.find_one({"user_id": user_id})
        today = datetime.now().date()
        
        if user_data and user_data.get("last_download"):
            last_download_date = user_data["last_download"].date()
            if last_download_date < today:
                users_col.update_one({"user_id": user_id}, {"$set": {"download_count": 0}})
                user_data["download_count"] = 0
        
        if user_data and user_data.get("download_count", 0) >= DAILY_FREE_LIMIT:
            await processing_msg.delete()
            await message.reply_text(f"❌ You've reached your daily limit of {DAILY_FREE_LIMIT} downloads. Please try again tomorrow or upgrade for unlimited downloads.")
            return

        # Use yt-dlp to download directly as it supports many platforms
        download_result = await download_file_and_get_info_ytdlp(url, processing_msg)

        if download_result and download_result.get("success"):
            users_col.update_one(
                {"user_id": user_id},
                {"$inc": {"download_count": 1}, "$set": {"last_download": datetime.now()}},
                upsert=True
            )
            file_id = download_result["file_id"]
            file_name = download_result["file_name"]
            file_size = download_result["file_size"]
            thumbnail_url = download_result["thumbnail_url"]
            original_filename = download_result["original_filename_for_download"]

            direct_download_link_koyeb = f"{DOWNLOAD_BASE_URL}download/{file_id}/{original_filename}"

            caption_text = (
                f"✅ Download Ready (Koyeb Hosted)!\n\n"
                f"📁 **Title**: {file_name}\n"
                f"📦 **Size**: {file_size}\n\n"
                f"⚠️ Note: Download link will expire after some time."
            )
            
            buttons = [
                [InlineKeyboardButton("⬇️ Download Now", url=direct_download_link_koyeb)],
                [
                    InlineKeyboardButton("📢 Updates", url=f"https://t.me/{UPDATE_CHANNEL}"),
                    InlineKeyboardButton("👥 Support", url=f"https://t.me/{SUPPORT_GROUP}")
                ]
            ]

            if thumbnail_url:
                try:
                    await client.send_photo(
                        chat_id=user_id,
                        photo=thumbnail_url,
                        caption=caption_text,
                        reply_markup=InlineKeyboardMarkup(buttons)
                    )
                except Exception as photo_error:
                    logger.warning(f"Failed to send photo thumbnail for other video: {photo_error}. Sending text message instead.")
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
            await message.reply_text("✨ Your Koyeb hosted download link for this video is ready!")

        else:
            await processing_msg.delete()
            await message.reply_text(f"❌ Error downloading this video: {download_result.get('error', 'Failed to download from the provided URL.')}\n\nPlease ensure the URL is valid and the video is publicly accessible.")

    except Exception as e:
        logger.error(f"Error handling other video download: {e}")
        if processing_msg:
            await processing_msg.delete()
        await message.reply_text("❌ An unexpected error occurred while processing this video. Please try again later.")


@app.on_callback_query(filters.regex("^help_download$"))
async def help_download(client, callback_query):
    help_text = (
        "📹 How to Download Videos:\n\n"
        "1. **For Terabox Links:**\n"
        "   - Open Terabox app or website, copy the link.\n"
        "   - Paste the link here in the bot.\n"
        "   - Choose: 'Fast Download (API Link)' (direct link from external API) or 'Stable Download (Koyeb Link)' (downloads to our server).\n\n"
        "2. **For Other Videos (YouTube, etc.):**\n"
        "   - Send the link directly (if it's not Terabox, bot will ask to download).\n"
        "   - OR Use the command: `/download_other <video_link>` (e.g., `/download_other https://youtube.com/watch?v=xyz`)\n\n"
        "⚠️ Note: All download links will expire after some time.\n\n"
        "For any issues, contact @aschat_group"
    )
    await callback_query.answer()
    await callback_query.message.reply_text(help_text)

if __name__ == "__main__":
    logger.info("Starting Free Terabox & Other Video Downloader Bot...")
    logger.info(f"Flask health check server running on port {PORT}")
    app.run()

