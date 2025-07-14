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
from flask import Flask, jsonify
import threading

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app for health checks
flask_app = Flask(__name__)
PORT = int(os.getenv("PORT", 8080))

@flask_app.route('/')
def health_check():
    return jsonify({"status": "ok", "message": "Terabox Downloader Bot is running"})

def run_flask():
    flask_app.run(host='0.0.0.0', port=PORT)

# Start Flask server in a separate thread
threading.Thread(target=run_flask, daemon=True).start()

# Bot configuration
API_ID = int(os.getenv("API_ID", 12345))
API_HASH = os.getenv("API_HASH", "your_api_hash_here")
BOT_TOKEN = os.getenv("BOT_TOKEN", "your_bot_token_here")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
SUPPORT_GROUP = "aschat_group"
UPDATE_CHANNEL = "asbhai_bsr"
ADMIN_ID = 7315805581
DAILY_FREE_LIMIT = 5

# Initialize MongoDB
try:
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client["terabox_bot"]
    users_col = db["users"]
    logger.info("Connected to MongoDB")
except Exception as e:
    logger.error(f"MongoDB connection error: {e}")
    raise

# Initialize Pyrogram client
app = Client("terabox_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Updated Terabox Downloader Function with working APIs
async def download_terabox_file(url):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        }
        
        # Try first working API
        api1 = f"https://terabox-dl.qtcloud.workers.dev/api?url={url}"
        response = requests.get(api1, headers=headers, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("download_url"):
                return {
                    "success": True,
                    "download_url": data["download_url"],
                    "file_name": data.get("file_name", "terabox_file"),
                    "file_size": data.get("file_size", "N/A")
                }
        
        # Try second working API if first fails
        api2 = f"https://teraboxapi.com/api?url={url}"
        response = requests.get(api2, headers=headers, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("direct_link"):
                return {
                    "success": True,
                    "download_url": data["direct_link"],
                    "file_name": data.get("file_name", "terabox_file"),
                    "file_size": data.get("file_size", "N/A")
                }
        
        # Try third alternative
        api3 = f"https://youtube4kdownloader.com/terabox-downloader/?url={url}"
        soup = BeautifulSoup(requests.get(api3, headers=headers).content, "html.parser")
        download_btn = soup.find("a", {"class": "download-btn"})
        if download_btn and download_btn.get("href"):
            return {
                "success": True,
                "download_url": download_btn.get("href"),
                "file_name": "terabox_file",
                "file_size": "N/A"
            }
            
        return {"success": False, "error": "Failed to get download link from all sources"}
    except Exception as e:
        logger.error(f"Terabox download error: {e}")
        return {"success": False, "error": str(e)}

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
        if user_data and user_data.get("download_count", 0) >= DAILY_FREE_LIMIT:
            await message.reply_text(f"❌ You've reached your daily limit of {DAILY_FREE_LIMIT} downloads")
            return
        
        # Show processing message
        processing_msg = await message.reply_text("⏳ Processing your Terabox link (Free method may take time)...")
        
        # Get download info from free service
        download_info = await download_terabox_file(url)
        
        if not download_info.get("success"):
            await processing_msg.delete()
            await message.reply_text(f"❌ Error: {download_info.get('error', 'Failed to process link')}")
            return
        
        # Update download count
        users_col.update_one(
            {"user_id": user_id},
            {"$inc": {"download_count": 1}, "$set": {"last_download": datetime.now()}},
            upsert=True
        )
        
        # Create download button
        file_name = download_info.get("file_name", "file")
        download_url = download_info["download_url"]
        
        await processing_msg.delete()
        await message.reply_text(
            f"✅ Download Ready!\n\n"
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
        
    except Exception as e:
        logger.error(f"Error handling Terabox link: {e}")
        await message.reply_text("❌ An error occurred. Please try again later.")

@app.on_callback_query(filters.regex("^help_download$"))
async def help_download(client, callback_query):
    help_text = (
        "📹 How to Download Videos:\n\n"
        "1. Open Terabox app or website\n"
        "2. Find the video you want to download\n"
        "3. Click 'Share' and copy the link\n"
        "4. Paste that link here in the bot\n"
        "5. Wait for processing and click the download button\n\n"
        "For any issues, contact @aschat_group"
    )
    await callback_query.answer()
    await callback_query.message.reply_text(help_text)

if __name__ == "__main__":
    logger.info("Starting Free Terabox Downloader Bot...")
    logger.info(f"Flask health check server running on port {PORT}")
    app.run()
