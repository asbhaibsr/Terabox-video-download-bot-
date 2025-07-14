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
API_ID = int(os.getenv("API_ID", 12345))
API_HASH = os.getenv("API_HASH", "your_api_hash_here")
BOT_TOKEN = os.getenv("BOT_TOKEN", "your_bot_token_here")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
FORCE_SUB_CHANNEL = -1002283182645  # Channel ID
FORCE_SUB_GROUP = -1002085088955    # Group ID
ADMIN_ID = 7315805581
DAILY_FREE_LIMIT = 5
PREMIUM_PRICES = {
    "500": {"amount": 500, "files": 1000, "duration": 30},
    "1000": {"amount": 1000, "files": 2000, "duration": 30}
}
UPI_ID = "arsadsaifi8272@ibl"

# Initialize MongoDB
try:
    mongo_client = MongoClient(MONGO_URI, connectTimeoutMS=30000, serverSelectionTimeoutMS=30000)
    mongo_client.admin.command('ping')
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
    return redirect("https://example.com/your-terabox-download-url")

# Helper functions
async def is_user_subscribed(user_id):
    try:
        # Check channel subscription
        channel_status = await app.get_chat_member(FORCE_SUB_CHANNEL, user_id)
        # Check group subscription
        group_status = await app.get_chat_member(FORCE_SUB_GROUP, user_id)
        
        return (channel_status.status in ["member", "administrator", "creator"] and 
                group_status.status in ["member", "administrator", "creator"])
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

# Modified start command with dual subscription check
@app.on_message(filters.command("start"))
async def start_command(client, message):
    try:
        user_id = message.from_user.id
        subscribed = await is_user_subscribed(user_id)
        
        if not subscribed:
            buttons = [
                [
                    InlineKeyboardButton("📢 Join Channel", url="https://t.me/your_channel"),
                    InlineKeyboardButton("👥 Join Group", url="https://t.me/your_group")
                ],
                [InlineKeyboardButton("🔄 Check Subscription", callback_data="check_sub")]
            ]
            
            await message.reply_text(
                "📢 To use this bot, you must join both our channel and group:\n\n"
                "1. Join our official channel\n"
                "2. Join our discussion group\n"
                "3. Click the 'Check Subscription' button below",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
            return
        
        welcome_msg = (
            "👋 Welcome to Terabox Downloader Bot!\n\n"
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

# Modified link handler with dual subscription check
@app.on_message(filters.regex(r'https?://[^\s]+'))
async def handle_links(client, message):
    try:
        user_id = message.from_user.id
        
        # Check both subscriptions
        subscribed = await is_user_subscribed(user_id)
        if not subscribed:
            buttons = [
                [
                    InlineKeyboardButton("📢 Join Channel", url="https://t.me/your_channel"),
                    InlineKeyboardButton("👥 Join Group", url="https://t.me/your_group")
                ],
                [InlineKeyboardButton("🔄 Check Subscription", callback_data="check_sub")]
            ]
            
            await message.reply_text(
                "📢 To download files, you must join both our channel and group:\n\n"
                "1. Join our official channel\n"
                "2. Join our discussion group\n"
                "3. Click the 'Check Subscription' button below",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
            return
        
        # Rest of your link handling code remains the same...
        # [Previous code for handling Terabox links...]
        
    except Exception as e:
        logger.error(f"Error handling link: {e}")
        await message.reply_text("An error occurred while processing your link. Please try again.")

# Add this callback handler for subscription checks
@app.on_callback_query(filters.regex("^check_sub$"))
async def check_sub_callback(client, callback_query):
    try:
        user_id = callback_query.from_user.id
        subscribed = await is_user_subscribed(user_id)
        
        if subscribed:
            await callback_query.answer("✅ You're subscribed to both channel and group!", show_alert=True)
            await callback_query.message.delete()
            
            # Show the start menu again
            welcome_msg = (
                "👋 Welcome to Terabox Downloader Bot!\n\n"
                f"🔗 Send me any Terabox link and I'll download it for you.\n\n"
                f"📌 Free users can download {DAILY_FREE_LIMIT} files per day.\n"
                "💎 Get premium for unlimited downloads!"
            )
            
            buttons = [
                [InlineKeyboardButton("💎 Buy Premium", callback_data="premium_info")],
                [InlineKeyboardButton("📊 My Stats", callback_data="my_stats")]
            ]
            
            await callback_query.message.reply_text(
                welcome_msg,
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        else:
            await callback_query.answer("❌ You're not subscribed to both channel and group yet!", show_alert=True)
    except Exception as e:
        logger.error(f"Error in check_sub callback: {e}")
        await callback_query.answer("An error occurred. Please try again.", show_alert=True)

def run_flask():
    flask_app.run(host='0.0.0.0', port=8000)

if __name__ == "__main__":
    import threading
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    logger.info("Starting Terabox Downloader Bot...")
    app.run()
