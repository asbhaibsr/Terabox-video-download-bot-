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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Bot configuration
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
FORCE_SUB_CHANNEL = "@asbhaibser"  # Change to your channel
ADMIN_ID = 7315805581  # Change to your admin ID
DAILY_FREE_LIMIT = 5
PREMIUM_PRICES = {
    "500": {"amount": 500, "files": 1000, "duration": 30},
    "1000": {"amount": 1000, "files": 2000, "duration": 30}
}
UPI_ID = "arsadsaifi8272@ibl"

# Initialize MongoDB
mongo_client = MongoClient(MONGO_URI)
db = mongo_client["terabox_bot"]
users_col = db["users"]
downloads_col = db["downloads"]
payments_col = db["payments"]

# Initialize Pyrogram client
app = Client("terabox_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Helper functions
async def extract_terabox_info(url):
    try:
        # This is a placeholder - you'll need to implement actual Terabox link parsing
        # For now, we'll extract filename from URL
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
    except Exception:
        return False

async def get_user_data(user_id):
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

async def update_daily_counter(user_id):
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

async def can_user_download(user_id):
    user_data = await get_user_data(user_id)
    
    if user_data["is_premium"] and user_data["premium_expiry"] > datetime.now():
        return True, None
    
    today = datetime.now().date()
    last_download_date = user_data.get("last_download_date")
    
    if last_download_date and last_download_date.date() == today:
        if user_data["daily_downloads"] >= DAILY_FREE_LIMIT:
            return False, f"⚠️ You've reached your daily free limit of {DAILY_FREE_LIMIT} downloads.\n\nPlease purchase premium to download more files."
    
    return True, None

# Bot handlers
@app.on_message(filters.command("start"))
async def start_command(client, message):
    user_id = message.from_user.id
    user_data = await get_user_data(user_id)
    
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
        "👋 Welcome to Terabox Downloader Bot!\n\n"
        "🔗 Send me any Terabox link and I'll download it for you.\n\n"
        "📌 Free users can download {DAILY_FREE_LIMIT} files per day.\n"
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

@app.on_message(filters.regex(r'https?://[^\s]+'))
async def handle_links(client, message):
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
    download_url = f"https://depressed-cornelle-asbhaibsr-179ba27d.koyeb.app/{uuid.uuid4().hex}/{file_info['title']}.mp4"
    
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

@app.on_callback_query(filters.regex("^premium_info$"))
async def premium_info(client, callback_query):
    user_id = callback_query.from_user.id
    user_data = await get_user_data(user_id)
    
    premium_msg = (
        "💎 **Premium Plans** 💎\n\n"
        f"🔹 ₹500 - 1000 files for 1 month\n"
        f"🔹 ₹1000 - 2000 files for 1 month\n\n"
        "After payment, send screenshot to @asbhaibser with your user ID."
    )
    
    buttons = [
        [InlineKeyboardButton("Pay ₹500", callback_data="premium_500"),
         InlineKeyboardButton("Pay ₹1000", callback_data="premium_1000")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ]
    
    await callback_query.edit_message_text(
        premium_msg,
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@app.on_callback_query(filters.regex("^premium_(500|1000)$"))
async def premium_payment(client, callback_query):
    plan = callback_query.data.split("_")[1]
    plan_data = PREMIUM_PRICES[plan]
    
    payment_msg = (
        f"💳 **Payment Details for {plan} Plan**\n\n"
        f"🔹 Amount: ₹{plan_data['amount']}\n"
        f"🔹 Files: {plan_data['files']}\n"
        f"🔹 Duration: {plan_data['duration']} days\n\n"
        f"📌 Please send payment to UPI ID: `{UPI_ID}`\n"
        "After payment, send screenshot to @asbhaibser with your user ID."
    )
    
    await callback_query.edit_message_text(
        payment_msg,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="premium_info")]
        ])
    )

@app.on_callback_query(filters.regex("^my_stats$"))
async def my_stats(client, callback_query):
    user_id = callback_query.from_user.id
    user_data = await get_user_data(user_id)
    
    today = datetime.now().date()
    last_download_date = user_data.get("last_download_date")
    
    if last_download_date and last_download_date.date() == today:
        downloads_today = user_data["daily_downloads"]
    else:
        downloads_today = 0
    
    if user_data["is_premium"] and user_data["premium_expiry"] > datetime.now():
        premium_status = f"Active (expires on {user_data['premium_expiry'].strftime('%Y-%m-%d')})"
    else:
        premium_status = "Not Active"
    
    stats_msg = (
        "📊 **Your Stats**\n\n"
        f"🔹 User ID: `{user_id}`\n"
        f"🔹 Premium Status: {premium_status}\n"
        f"🔹 Downloads Today: {downloads_today}/{DAILY_FREE_LIMIT}\n"
        f"🔹 Total Downloads: {user_data['total_downloads']}\n\n"
        "💎 Upgrade to premium for unlimited downloads!"
    )
    
    buttons = [
        [InlineKeyboardButton("💎 Buy Premium", callback_data="premium_info")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ]
    
    await callback_query.edit_message_text(
        stats_msg,
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@app.on_callback_query(filters.regex("^main_menu$"))
async def main_menu(client, callback_query):
    welcome_msg = (
        "👋 Welcome to Terabox Downloader Bot!\n\n"
        "🔗 Send me any Terabox link and I'll download it for you.\n\n"
        "📌 Free users can download {DAILY_FREE_LIMIT} files per day.\n"
        "💎 Get premium for unlimited downloads!"
    )
    
    buttons = [
        [InlineKeyboardButton("💎 Buy Premium", callback_data="premium_info")],
        [InlineKeyboardButton("📊 My Stats", callback_data="my_stats")]
    ]
    
    await callback_query.edit_message_text(
        welcome_msg,
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@app.on_callback_query(filters.regex("^check_sub$"))
async def check_sub(client, callback_query):
    user_id = callback_query.from_user.id
    subscribed = await is_user_subscribed(user_id)
    
    if subscribed:
        await callback_query.edit_message_text(
            "✅ Thanks for joining! Now you can use the bot.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
            ])
        )
    else:
        await callback_query.answer("Please join the channel first.", show_alert=True)

# Admin commands
@app.on_message(filters.command("addpremium") & filters.user(ADMIN_ID))
async def add_premium(client, message):
    try:
        parts = message.text.split()
        if len(parts) < 3:
            await message.reply_text("Usage: /addpremium <user_id> <duration_in_days>")
            return
        
        user_id = int(parts[1])
        duration = int(parts[2])
        
        expiry_date = datetime.now() + timedelta(days=duration)
        
        users_col.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "is_premium": True,
                    "premium_expiry": expiry_date
                }
            },
            upsert=True
        )
        
        await message.reply_text(f"✅ Premium added for user {user_id} for {duration} days.")
    except Exception as e:
        await message.reply_text(f"Error: {e}")

@app.on_message(filters.command("stats") & filters.user(ADMIN_ID))
async def admin_stats(client, message):
    total_users = users_col.count_documents({})
    premium_users = users_col.count_documents({"is_premium": True, "premium_expiry": {"$gt": datetime.now()}})
    total_downloads = downloads_col.count_documents({})
    
    stats_msg = (
        "📊 **Admin Stats**\n\n"
        f"🔹 Total Users: {total_users}\n"
        f"🔹 Active Premium Users: {premium_users}\n"
        f"🔹 Total Downloads: {total_downloads}"
    )
    
    await message.reply_text(stats_msg)

# Start the bot
if __name__ == "__main__":
    logger.info("Starting Terabox Downloader Bot...")
    app.run()
