import os
import re
import logging
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from pymongo import MongoClient
from datetime import datetime, timedelta
import requests
from urllib.parse import urlparse, parse_qs
import uuid
from flask import Flask, request, jsonify, redirect

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
flask_app = Flask(__name__)

# Bot configuration
API_ID = int(os.getenv("API_ID", 12345))  # Default value for testing
API_HASH = os.getenv("API_HASH", "your_api_hash_here")
BOT_TOKEN = os.getenv("BOT_TOKEN", "your_bot_token_here")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")  # You'll set this in Koyeb
FORCE_SUB_CHANNEL = "@asbhaibsr"
ADMIN_ID = 7315805581  # Change to your admin ID
DAILY_FREE_LIMIT = 5
PREMIUM_PRICES = {
    "500": {"amount": 500, "files": 1000, "duration": 30},
    "1000": {"amount": 1000, "files": 2000, "duration": 30}
}
UPI_ID = "arsadsaifi8272@ibl"

# Initialize MongoDB with error handling
try:
    mongo_client = MongoClient(MONGO_URI, connectTimeoutMS=30000, serverSelectionTimeoutMS=30000)
    mongo_client.admin.command('ping')  # Test connection
    db = mongo_client["terabox_bot"]
    users_col = db["users"]
    downloads_col = db["downloads"]
    payments_col = db["payments"]
    logger.info("Successfully connected to MongoDB!")
except Exception as e:
    logger.error(f"MongoDB connection error: {e}")
    raise

# Initialize Pyrogram client
app = Client(
    "terabox_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# Flask routes
@flask_app.route('/')
def home():
    return "Terabox Downloader Bot is running!"

@flask_app.route('/<file_id>/<filename>')
def download_file(file_id, filename):
    # Here you would implement your actual file download logic
    # For now, we'll just redirect to a placeholder
    return redirect("https://example.com/your-terabox-download-url")

# Helper functions
async def extract_terabox_info(url):
    try:
        parsed = urlparse(url)
        filename = parsed.path.split('/')[-1]
        return {
            "title": filename.replace('+', ' ').split('.')[0],
            "size": "Unknown",
            "url": url
        }
    except Exception as e:
        logger.error(f"Error extracting terabox info: {e}")
        return None

async def is_user_subscribed(user_id):
    try:
        status = await app.get_chat_member(FORCE_SUB_CHANNEL, user_id)
        return status.status in ["member", "administrator", "creator"]
    except Exception as e:
        logger.error(f"Subscription check error: {e}")
        return False

async def get_user_data(user_id):
    try:
        user_data = users_col.find_one({"user_id": user_id})
        if not user_data:
            user_data = {
                "user_id": user_id,
                "is_premium": False,
                "premium_expiry": None,
                "total_downloads": 0,
                "daily_downloads": 0,
                "last_download_date": None,
                "joined_date": datetime.now()
            }
            users_col.insert_one(user_data)
        return user_data
    except Exception as e:
        logger.error(f"Error getting user data: {e}")
        return None

async def update_daily_counter(user_id):
    try:
        user_data = await get_user_data(user_id)
        today = datetime.now().date()
        last_download_date = user_data.get("last_download_date")
        
        if last_download_date and last_download_date.date() == today:
            new_count = user_data["daily_downloads"] + 1
        else:
            new_count = 1
        
        users_col.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "daily_downloads": new_count,
                    "last_download_date": datetime.now(),
                    "total_downloads": user_data["total_downloads"] + 1
                }
            }
        )
        
        downloads_col.insert_one({
            "user_id": user_id,
            "download_date": datetime.now(),
            "count": new_count
        })
    except Exception as e:
        logger.error(f"Error updating daily counter: {e}")

async def can_user_download(user_id):
    try:
        user_data = await get_user_data(user_id)
        if not user_data:
            return False, "Error accessing your account data"
        
        if user_data["is_premium"] and user_data["premium_expiry"] > datetime.now():
            return True, None
        
        today = datetime.now().date()
        last_download_date = user_data.get("last_download_date")
        
        if last_download_date and last_download_date.date() == today:
            if user_data["daily_downloads"] >= DAILY_FREE_LIMIT:
                return False, f"⚠️ You've reached your daily free limit of {DAILY_FREE_LIMIT} downloads.\n\nPlease purchase premium to download more files."
        
        return True, None
    except Exception as e:
        logger.error(f"Error checking download permission: {e}")
        return False, "An error occurred while checking your download permissions"

# Bot handlers
@app.on_message(filters.command("start"))
async def start_command(client, message):
    try:
        user_id = message.from_user.id
        subscribed = await is_user_subscribed(user_id)
        
        if not subscribed:
            await message.reply_text(
                f"📢 Please join our channel {FORCE_SUB_CHANNEL} to use this bot.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Join Channel", url=f"https://t.me/{FORCE_SUB_CHANNEL[1:]}")],
                    [InlineKeyboardButton("Try Again", callback_data="check_sub")]
                ])
            )
            return
        
        welcome_msg = (
            f"👋 Welcome to Terabox Downloader Bot!\n\n"
            f"🔗 Send me any Terabox link and I'll download it for you.\n\n"
            f"📌 Free users can download {DAILY_FREE_LIMIT} files per day.\n"
            "💎 Get premium for unlimited downloads!"
        )
        
        buttons = [
            [InlineKeyboardButton("💎 Buy Premium", callback_data="premium_info")],
            [InlineKeyboardButton("📊 My Stats", callback_data="my_stats")]
        ]
        
        await message.reply_text(
            welcome_msg,
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    except Exception as e:
        logger.error(f"Error in start command: {e}")
        await message.reply_text("An error occurred. Please try again later.")

@app.on_message(filters.regex(r'https?://[^\s]+'))
async def handle_links(client, message):
    try:
        user_id = message.from_user.id
        
        # Check subscription
        subscribed = await is_user_subscribed(user_id)
        if not subscribed:
            await message.reply_text(
                f"📢 Please join our channel {FORCE_SUB_CHANNEL} to use this bot.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Join Channel", url=f"https://t.me/{FORCE_SUB_CHANNEL[1:]}")],
                    [InlineKeyboardButton("Try Again", callback_data="check_sub")]
                ])
            )
            return
        
        # Check if URL is Terabox
        url = message.text
        if "terabox" not in url.lower():
            await message.reply_text("❌ Please send a valid Terabox link.")
            return
        
        # Check download limits
        can_download, error_msg = await can_user_download(user_id)
        if not can_download:
            await message.reply_text(error_msg)
            return
        
        # Extract file info
        file_info = await extract_terabox_info(url)
        if not file_info:
            await message.reply_text("❌ Could not extract file information from the link.")
            return
        
        # Create download button
        download_url = f"https://{os.getenv('KOYEB_APP_NAME', 'your-app-name')}.koyeb.app/{uuid.uuid4().hex}/{file_info['title']}.mp4"
        
        response_msg = (
            f"📁 **File Information**\n\n"
            f"🔹 **Title:** {file_info['title']}\n"
            f"🔹 **Size:** {file_info['size']}\n\n"
            "Click below to download:"
        )
        
        await message.reply_text(
            response_msg,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬇️ Download", url=download_url)],
                [InlineKeyboardButton("💎 Get Premium", callback_data="premium_info")]
            ])
        )
        
        # Update user download count
        await update_daily_counter(user_id)
    except Exception as e:
        logger.error(f"Error handling link: {e}")
        await message.reply_text("An error occurred while processing your link. Please try again.")

def run_flask():
    flask_app.run(host='0.0.0.0', port=8000)

if __name__ == "__main__":
    import threading
    # Start Flask server in a separate thread
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    logger.info("Starting Terabox Downloader Bot...")
    app.run()
