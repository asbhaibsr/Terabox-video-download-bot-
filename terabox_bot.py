import os
import time
import datetime
import asyncio
import logging
from pymongo import MongoClient
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait, MessageNotModified
from yt_dlp import YoutubeDL
import re
import shutil

# --- Configuration ---
# Get sensitive data from environment variables for security
API_TOKEN = os.environ.get("API_TOKEN")
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
ADMIN_ID = int(os.environ.get("ADMIN_ID"))
MONGO_URI = os.environ.get("MONGO_URI")

# UPI ID for payments
UPI_ID = os.environ.get("UPI_ID", "arsadsaifi8272@ibl") # Can be set as env var or hardcoded

# Premium Plan Prices (in Rs)
PREMIUM_PLANS = {
    "1_month": {"days": 30, "price": 600, "description": "1 महीना प्रीमियम"},
    "2_month": {"days": 60, "price": 1200, "description": "2 महीने प्रीमियम"},
    "3_month": {"days": 90, "price": 1800, "description": "3 महीने प्रीमियम"},
    "6_month": {"days": 180, "price": 3600, "description": "6 महीने प्रीमियम"},
    "1_year": {"days": 365, "price": 7200, "description": "1 साल प्रीमियम"}
}

# Download Limit for Free Users
FREE_DOWNLOAD_LIMIT = 3
DAILY_LIMIT_RESET_HOUR = 0 # 0 for midnight (12 AM)

# Download directory
DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True) # Ensure download directory exists on startup

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- MongoDB Connection ---
try:
    client = MongoClient(MONGO_URI)
    db = client["terabox_bot"] # Database name
    users_collection = db["users"]
    payments_collection = db["payments"]
    logger.info("MongoDB connected successfully!")
except Exception as e:
    logger.error(f"MongoDB connection failed: {e}")
    # In a production environment, you might want to exit or retry
    # For now, we'll let it proceed but note the error.
    # raise # If you want the bot to crash if DB connection fails

# --- Pyrogram Client ---
app = Client(
    "terabox_downloader_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=API_TOKEN
)

# --- Helper Functions ---

async def get_user_data(user_id):
    """Fetches user data from DB, creates if not exists."""
    user = users_collection.find_one({"_id": user_id})
    if not user:
        user = {
            "_id": user_id,
            "is_premium": False,
            "premium_expiry": None,
            "daily_downloads": 0,
            "last_download_date": None,
            "total_downloads": 0,
            "joined_date": datetime.datetime.now()
        }
        users_collection.insert_one(user)
    return user

async def update_user_data(user_id, update_fields):
    """Updates user data in DB."""
    users_collection.update_one({"_id": user_id}, {"$set": update_fields})

async def check_premium_status(user_id):
    """Checks if a user is premium and updates status if expired."""
    user = await get_user_data(user_id)
    if user.get("is_premium") and user.get("premium_expiry"):
        if user["premium_expiry"] > datetime.datetime.now():
            return True
        else:
            # Premium expired, update status
            await update_user_data(user_id, {"is_premium": False, "premium_expiry": None})
            logger.info(f"User {user_id}'s premium expired.")
    return False

async def reset_daily_downloads_task():
    """Task to periodically reset daily download count."""
    while True:
        now = datetime.datetime.now()
        # Check if it's the reset hour (e.g., 12 AM)
        if now.hour == DAILY_LIMIT_RESET_HOUR:
            # Check if reset has already happened today
            last_reset_doc = users_collection.find_one({"_id": "reset_tracker"})
            if last_reset_doc and last_reset_doc.get("date") and last_reset_doc["date"].date() == now.date():
                pass # Already reset today, do nothing
            else:
                users_collection.update_many(
                    {"is_premium": False}, # Only reset for non-premium users
                    {"$set": {"daily_downloads": 0, "last_download_date": now}}
                )
                users_collection.update_one(
                    {"_id": "reset_tracker"},
                    {"$set": {"date": now}},
                    upsert=True
                )
                logger.info("Daily download limits reset for all non-premium users.")
        await asyncio.sleep(3600) # Check every hour

# --- Filters ---
def is_admin(filter, client, message):
    return message.from_user.id == ADMIN_ID

# --- Bot Commands ---

@app.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    user_name = message.from_user.first_name or "दोस्त"
    await get_user_data(message.from_user.id) # Ensure user exists in DB

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡️ वीडियो डाउनलोड करें", callback_data="download_menu")],
        [InlineKeyboardButton("💎 प्रीमियम प्लान्स", callback_data="premium_plans")],
        [InlineKeyboardButton("🆘 मदद चाहिए?", callback_data="help_menu")],
        [InlineKeyboardButton("📊 बॉट की रिपोर्ट", callback_data="bot_stats_menu")]
    ])
    await message.reply_text(
        f"👋 नमस्कार {user_name}! मैं हूँ आपका सुपर टेराबॉक्स डाउनलोडर बॉट! "
        "मुझे टेराबॉक्स का लिंक दो और मैं उसे डाउनलोड कर दूँगा. "
        "चलो, शुरू करें?",
        reply_markup=keyboard
    )

@app.on_message(filters.command("help") & filters.private)
async def help_command(client, message):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 अभी डाउनलोड करो!", callback_data="download_menu")],
        [InlineKeyboardButton("🔙 वापस", callback_data="start_menu")]
    ])
    await message.reply_text(
        "🆘 मैं आपकी मदद के लिए यहाँ हूँ! ये कमांड्स आपके काम आएंगे:\n\n"
        "✨ `/start` - बॉट को फिर से शुरू करें.\n"
        "🔗 मुझे सीधा टेराबॉक्स लिंक भेजें - मैं डाउनलोड शुरू कर दूँगा.\n"
        "💎 `/premium` - प्रीमियम प्लान्स देखें.\n"
        "📊 `/botstats` - बॉट की रिपोर्ट देखें.\n"
        "💡 `/help` - यह हेल्प मैसेज.\n\n"
        "एडमिन कमांड्स (सिर्फ़ मेरे मालिक के लिए 😉):\n"
        "👤 `/addpremium <user_id> <days>` - किसी यूज़र को प्रीमियम दें.\n"
        "📊 `/checkpremiumstats` - प्रीमियम यूज़र्स की जानकारी.\n"
        "📢 `/broadcast <message>` - सभी यूज़र्स को मैसेज भेजें.\n",
        reply_markup=keyboard
    )

@app.on_message(filters.command("premium") & filters.private)
async def premium_command(client, message):
    await show_premium_plans(client, message)

@app.on_message(filters.command("botstats") & filters.private)
async def bot_stats_command(client, message):
    await show_bot_stats(client, message)

@app.on_message(filters.command("addpremium") & filters.private & filters.create(is_admin))
async def add_premium_command(client, message):
    if len(message.command) != 3:
        await message.reply_text(
            "मालिक, सही इस्तेमाल करें: `/addpremium <user_id> <days>`\n"
            "उदाहरण: `/addpremium 123456789 30` (30 दिन के लिए)."
        )
        return

    try:
        user_id = int(message.command[1])
        days = int(message.command[2])
    except ValueError:
        await message.reply_text("मालिक, User ID और दिन नंबर में होने चाहिए.")
        return

    user = await get_user_data(user_id)
    current_expiry = user.get("premium_expiry")

    if current_expiry and current_expiry > datetime.datetime.now():
        new_expiry = current_expiry + datetime.timedelta(days=days)
        message_text = f"प्रीमियम बढ़ाया गया! `{user_id}` का प्रीमियम अब **{new_expiry.strftime('%d-%m-%Y %H:%M:%S')}** तक वैलिड है."
    else:
        new_expiry = datetime.datetime.now() + datetime.timedelta(days=days)
        message_text = f"प्रीमियम एक्टिवेट किया गया! `{user_id}` का प्रीमियम अब **{new_expiry.strftime('%d-%m-%Y %H:%M:%S')}** तक वैलिड है."

    await update_user_data(user_id, {
        "is_premium": True,
        "premium_expiry": new_expiry
    })

    await message.reply_text(message_text)
    try:
        await app.send_message(
            user_id,
            f"🎉 वाह! आपका प्रीमियम एक्टिवेट हो गया है! अब आप **{new_expiry.strftime('%d-%m-%Y %H:%M:%S')}** तक अनलिमिटेड डाउनलोड कर सकते हैं! मौज करो!"
        )
    except Exception as e:
        logger.warning(f"Could not notify user {user_id} about premium activation: {e}")
        await message.reply_text(f"यूज़र को नोटिफाई नहीं कर पाया: {e}")


@app.on_message(filters.command("checkpremiumstats") & filters.private & filters.create(is_admin))
async def check_premium_stats_command(client, message):
    premium_users = users_collection.find({"is_premium": True, "premium_expiry": {"$gt": datetime.datetime.now()}})
    
    stats_message = "💎 **प्रीमियम यूज़र्स की जानकारी:**\n\n"
    count = 0
    for user in premium_users:
        count += 1
        user_id = user["_id"]
        expiry = user["premium_expiry"].strftime('%d-%m-%Y')
        stats_message += f"👤 ID: `{user_id}` | एक्सपायरी: `{expiry}`\n"
    
    if count == 0:
        stats_message += "अभी कोई एक्टिव प्रीमियम यूज़र नहीं है."

    await message.reply_text(stats_message)

@app.on_message(filters.command("broadcast") & filters.private & filters.create(is_admin))
async def broadcast_command(client, message):
    if len(message.command) < 2:
        await message.reply_text("मालिक, ब्रॉडकास्ट करने के लिए मैसेज लिखें: `/broadcast आपका मैसेज`")
        return

    broadcast_message = " ".join(message.command[1:])
    all_users = users_collection.find({}, {"_id": 1}) # Get all user IDs

    success_count = 0
    fail_count = 0

    status_message = await message.reply_text("ब्रॉडकास्ट शुरू हो रहा है... धीरज रखें मालिक!")

    for user in all_users:
        user_id = user["_id"]
        try:
            await app.send_message(user_id, f"📢 **बॉट का ज़रूरी मैसेज:**\n\n{broadcast_message}")
            success_count += 1
            await asyncio.sleep(0.1) # Small delay to avoid flood waits
        except FloodWait as e:
            logger.warning(f"FloodWait encountered. Sleeping for {e.value} seconds.")
            await asyncio.sleep(e.value + 5) # Add extra buffer
            try: # Try again after flood wait
                await app.send_message(user_id, f"📢 **बॉट का ज़रूरी मैसेज:**\n\n{broadcast_message}")
                success_count += 1
            except Exception:
                fail_count += 1
        except Exception as e:
            logger.error(f"Failed to send broadcast to {user_id}: {e}")
            fail_count += 1
        
        try:
            await status_message.edit_text(
                f"ब्रॉडकास्ट चल रहा है...\n"
                f"✅ सफल: {success_count}\n"
                f"❌ विफल: {fail_count}"
            )
        except MessageNotModified:
            pass # Ignore if message content is the same

    await status_message.edit_text(
        f"ब्रॉडकास्ट पूरा हुआ मालिक!\n"
        f"✅ कुल सफल: {success_count}\n"
        f"❌ कुल विफल: {fail_count}"
    )

# --- Callback Query Handlers ---

@app.on_callback_query()
async def callback_handler(client, callback_query):
    data = callback_query.data
    message = callback_query.message
    user_id = callback_query.from_user.id

    if data == "start_menu":
        # Delete old message and send new one to reset state for some reason
        try:
            await message.delete() 
        except Exception:
            pass # Ignore if message already deleted or not found
        await start_command(client, message)
    elif data == "download_menu":
        await message.edit_text(
            "🔗 मुझे टेराबॉक्स वीडियो का लिंक भेजें. मैं उसे डाउनलोड कर दूँगा!\n\n"
            "उदाहरण: `https://teraboxapp.com/s/abcdefg`",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 वापस", callback_data="start_menu")]
            ])
        )
    elif data == "premium_plans":
        await show_premium_plans(client, message)
    elif data.startswith("buy_premium_"):
        plan_key = data.replace("buy_premium_", "")
        selected_plan = PREMIUM_PLANS.get(plan_key)
        if selected_plan:
            await message.edit_text(
                f"💎 आपने **{selected_plan['description']}** प्लान चुना है. इसकी क़ीमत ₹{selected_plan['price']} है.\n\n"
                f"हमारे UPI ID पर पेमेंट करें: `{UPI_ID}`\n\n"
                "पेमेंट करने के बाद, पेमेंट का **स्क्रीनशॉट मुझे भेजें.** मेरे मालिक उसे देखकर आपका प्रीमियम एक्टिवेट कर देंगे! "
                "पेमेंट होने के बाद धैर्य रखें, इसमें थोड़ा समय लग सकता है.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 वापस", callback_data="premium_plans")]
                ])
            )
        else:
            await message.edit_text("ऊप्स! यह प्लान नहीं मिला. फिर से कोशिश करें.",
                                    reply_markup=InlineKeyboardMarkup([
                                        [InlineKeyboardButton("🔙 वापस", callback_data="premium_plans")]
                                    ]))
    elif data == "help_menu":
        # Edit message to help content
        await message.edit_text(
            "🆘 मैं आपकी मदद के लिए यहाँ हूँ! ये कमांड्स आपके काम आएंगे:\n\n"
            "✨ `/start` - बॉट को फिर से शुरू करें.\n"
            "🔗 मुझे सीधा टेराबॉक्स लिंक भेजें - मैं डाउनलोड शुरू कर दूँगा.\n"
            "💎 `/premium` - प्रीमियम प्लान्स देखें.\n"
            "📊 `/botstats` - बॉट की रिपोर्ट देखें.\n"
            "💡 `/help` - यह हेल्प मैसेज.\n\n"
            "एडमिन कमांड्स (सिर्फ़ मेरे मालिक के लिए 😉):\n"
            "👤 `/addpremium <user_id> <days>` - किसी यूज़र को प्रीमियम दें.\n"
            "📊 `/checkpremiumstats` - प्रीमियम यूज़र्स की जानकारी.\n"
            "📢 `/broadcast <message>` - सभी यूज़र्स को मैसेज भेजें.\n",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🚀 अभी डाउनलोड करो!", callback_data="download_menu")],
                [InlineKeyboardButton("🔙 वापस", callback_data="start_menu")]
            ])
        )
    elif data == "bot_stats_menu":
        await show_bot_stats(client, message)

    await callback_query.answer() # Acknowledge the callback query


async def show_premium_plans(client, message):
    user_id = message.from_user.id
    is_premium = await check_premium_status(user_id)
    user = await get_user_data(user_id)
    
    text = "💎 **प्रीमियम प्लान्स:**\n\n"
    if is_premium:
        expiry_date = user["premium_expiry"].strftime('%d-%m-%Y %H:%M:%S')
        text += f"आप पहले से प्रीमियम यूज़र हैं! आपका प्रीमियम {expiry_date} तक वैलिड है. मौज करो! 🎉\n\n"
    else:
        text += "फ़्री यूज़र्स के लिए रोज़ 3 डाउनलोड की लिमिट है.\n"
        text += "प्रीमियम से पाएं **अनलिमिटेड डाउनलोड**, कोई लिमिट नहीं!\n\n"
        text += "अपनी पसंद का प्लान चुनें:\n\n"

    keyboard_buttons = []
    for key, plan in PREMIUM_PLANS.items():
        keyboard_buttons.append(
            [InlineKeyboardButton(f"🚀 {plan['description']} - ₹{plan['price']}", callback_data=f"buy_premium_{key}")]
        )
    keyboard_buttons.append([InlineKeyboardButton("🔙 वापस", callback_data="start_menu")])

    await message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard_buttons)
    )

async def show_bot_stats(client, message):
    total_users = users_collection.count_documents({})
    premium_users_count = users_collection.count_documents({"is_premium": True, "premium_expiry": {"$gt": datetime.datetime.now()}})
    total_downloads_sum = users_collection.aggregate([
        {"$group": {"_id": None, "total": {"$sum": "$total_downloads"}}}
    ])
    total_downloads = next(total_downloads_sum, {"total": 0})["total"]

    stats_text = (
        f"📊 **बॉट की रिपोर्ट:**\n\n"
        f"👥 कुल यूज़र्स: **{total_users}**\n"
        f"💎 एक्टिव प्रीमियम यूज़र्स: **{premium_users_count}**\n"
        f"⬇️ कुल डाउनलोड किए गए वीडियो: **{total_downloads}**\n\n"
        "बॉट का स्टेटस: 🚀 रॉकेट की तरह चल रहा है!"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 वापस", callback_data="start_menu")]
    ])
    await message.edit_text(stats_text, reply_markup=keyboard)


# --- Handle Incoming Terabox Links ---

# Regex for Terabox links, with flags=0 for Python 3.12 compatibility
@app.on_message(filters.regex(r"https?://(?:www\.)?(terabox|nephobox|kofile|mirrobox|momoradar|www.4funbox\.com|www.sukifiles\.com|www.terabox\.com|www.teraboxapp\.com|teraboxapp\.com|terabox\.com|www.4hfile\.com|www.rapidgator\.net|www.kufile\.net|www.pandafiles\.com|www.subyshare\.com|www.filepress\.com|filepress\.com|m.terabox\.com)\.(com|app|net|cc|co|xyz|me|live|cloud|jp|ru|io|pw|site|online|ga|ml|tk|ai|info|store|shop|org|biz|club|fun|pro|sbs|digital|solutions|host|website|tech|dev|page|buzz|guru|news|press|top|blog|art|media|zone|icu|wiki|photos|tube|games|social|group|network|link|center|studio|design|agency|market|events|gallery|house|land|life|today|world|city|estate|fund|gold|health|inc|solutions|systems|tools|ventures|vodka|wedding|work|yoga|zone|academy|accountant|ad|ads|agency|ai|air|apartments|app|archi|associates|attorney|au|band|bar|bargains|beer|best|bid|bike|bio|biz|black|blog|blue|boutique|build|builders|business|cab|cafe|cam|camera|camp|capital|car|cards|care|careers|casa|cash|casino|catering|cc|center|ceo|church|city|claims|cleaning|clinic|clothing|cloud|coach|codes|coffee|college|community|company|computer|condos|construction|consulting|contractors|cool|coupons|credit|creditcard|cruises|dad|dance|data|date|deals|delivery|democrat|dental|design|diamonds|diet|digital|direct|directory|discount|doctor|dog|domains|education|email|energy|engineer|engineering|enterprises|equipment|estate|events|exchange|expert|express|faith|family|fan|farm|fashion|film|finance|financial|firm|fitness|flights|florist|flowers|football|forsale|foundation|fund|furniture|fyi|gallery|games|garden|gay|gent|gifts|gives|glass|global|gold|golf|graphics|gratis|green|gripe|guide|guitars|guru|haus|health|healthcare|help|here|hiphop|holdings|holiday|homes|horse|host|hosting|house|how|id|industries|info|ink|institute|insurance|insure|international|investments|irish|is|jetzt|jewelry|job|jobs|join|juegos|kaufen|kim|kitchen|land|lease|legal|lgbt|life|lighting|limited|live|llc|loan|loans|lol|london|ltd|maison|management|marketing|mba|media|memorial|men|menu|mobi|moda|moe|money|mortgage|mov|movie|museum|name|navy|network|new|news|ninja|nyc|okinawa|one|online|ooo|organic|partners|parts|party|photo|photography|photos|pics|pictures|pink|pizza|place|plumbing|plus|poker|porn|press|pro|productions|prof|properties|property|pub|qa|quebec|racing|recipes|red|rehab|reise|reisen|rent|rentals|repair|report|republican|restaurant|reviews|rip|rocks|rodeo|run|sarl|school|schule|science|scot|security|services|sex|sexy|shiksha|shoes|shop|shopping|show|singles|site|ski|soccer|social|software|solar|solutions|soy|space|studio|style|sucks|supplies|supply|support|surf|surgery|sydney|systems|tax|taxi|team|tech|technology|tel|telecom|tennis|theater|tickets|tienda|tips|tires|today|tools|tours|town|toys|trade|training|travel|tube|university|uno|vacations|ventures|vet|viajes|video|villas|vin|vision|vodka|vote|voting|voto|voyage|wales|wang|watch|webcam|website|wed|wedding|whoswho|wiki|win|wine|work|works|world|wtf|xyz|yachts|ye|yoga|zara)/[a-zA-Z0-9]+", filters.private)
async def handle_terabox_link(client, message):
    user_id = message.from_user.id
    terabox_link = message.text
    user = await get_user_data(user_id)

    is_premium = await check_premium_status(user_id)
    today = datetime.date.today()

    # Reset daily downloads if it's a new day
    if user.get("last_download_date") is None or user["last_download_date"].date() != today:
        await update_user_data(user_id, {"daily_downloads": 0, "last_download_date": datetime.datetime.now()})
        user = await get_user_data(user_id) # Reload user data after reset

    # Check download limit for free users
    if not is_premium and user["daily_downloads"] >= FREE_DOWNLOAD_LIMIT:
        await message.reply_text(
            f"🚫 ओह नो! आपकी आज की {FREE_DOWNLOAD_LIMIT} डाउनलोड लिमिट पूरी हो गई है. "
            "ज़्यादा डाउनलोड के लिए प्रीमियम ले लो या कल फिर ट्राई करना!"
            "\n\n💎 प्रीमियम प्लान्स देखने के लिए /premium दबाएं.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 प्रीमियम प्लान्स", callback_data="premium_plans")],
                [InlineKeyboardButton("🆘 मदद चाहिए?", callback_data="help_menu")]
            ])
        )
        return

    status_message = await message.reply_text(
        f"🔗 लिंक मिल गया! मैं इसे स्कैन कर रहा हूँ, रुको ज़रा... "
        f"(`{terabox_link}`)\n\n"
        "यह प्रक्रिया थोड़ी देर ले सकती है, धैर्य रखें."
    )

    try:
        # Use a temporary file name to avoid clashes and for clean deletion
        temp_filepath_template = os.path.join(DOWNLOAD_DIR, f'{user_id}_%(title)s.%(ext)s')
        
        ydl_opts = {
            'format': 'best', # Initially get best quality to present options
            'outtmpl': temp_filepath_template,
            'noplaylist': True,
            'verbose': False,
            'quiet': True,
            'no_warnings': True,
            'skip_download': True, # Only extract info, don't download yet
        }

        with YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(terabox_link, download=False)
            if not info_dict:
                raise Exception("Could not extract info from the link.")

            # Get available formats
            formats = info_dict.get('formats', [])
            
            # Filter for video and audio formats, prioritizing standard qualities
            quality_options = []
            seen_qualities = set()

            # Add common video formats
            for f in sorted(formats, key=lambda x: x.get('height', 0), reverse=True):
                if f.get('vcodec') != 'none' and f.get('ext') in ['mp4', 'mkv', 'webm']: # Filter common video types
                    quality_str = f"{f.get('height')}p" if f.get('height') else f.get('format_note', 'Video')
                    if quality_str not in seen_qualities:
                        quality_options.append({
                            "text": quality_str, 
                            "callback": f"download_quality_{terabox_link}_{f['format_id']}"
                        })
                        seen_qualities.add(quality_str)
            
            # Add Audio Only if available
            audio_formats_filtered = [f for f in formats if f.get('acodec') != 'none' and f.get('vcodec') == 'none' and f.get('ext') in ['mp3', 'm4a', 'opus']]
            if audio_formats_filtered:
                quality_options.append({
                    "text": "🎧 ऑडियो ओनली", 
                    "callback": f"download_quality_{terabox_link}_bestaudio"
                })

            if not quality_options:
                raise Exception("No usable video or audio formats found for download.")
            
            # Create inline keyboard from quality options
            keyboard_buttons = []
            for option in quality_options:
                keyboard_buttons.append([InlineKeyboardButton(option["text"], callback_data=option["callback"])])
            
            keyboard_buttons.append([InlineKeyboardButton("🔙 वापस", callback_data="start_menu")])

            await status_message.edit_text(
                f"🎉 वीडियो मिल गया: **{info_dict.get('title', 'शीर्षक नहीं मिला')}**\n"
                f"कौन-सी क्वालिटी चाहिए, दोस्त?",
                reply_markup=InlineKeyboardMarkup(keyboard_buttons)
            )

    except Exception as e:
        logger.error(f"Error extracting info from Terabox link {terabox_link}: {e}")
        # Notify admin if it's a potential Terabox system change
        if "unable to extract" in str(e).lower() or "no appropriate format" in str(e).lower() or "Video unavailable" in str(e).lower():
             await client.send_message(
                 ADMIN_ID,
                 f"🚨 **एडमिन अलर्ट:** टेराबॉक्स डाउनलोड विधि में कुछ बदलाव हुआ लगता है! "
                 f"लिंक `{terabox_link}` से जानकारी नहीं निकाल पाया. "
                 f"एरर: `{e}`. कृपया कोड जांचें."
             )
        await status_message.edit_text(
            f"😥 ओह! इस लिंक से वीडियो नहीं मिल रहा है या कुछ गड़बड़ हो गई है. "
            "कृपया सही टेराबॉक्स लिंक भेजें या बाद में कोशिश करें.\n\n"
            f"**एरर:** `{e}`"
        )

# Callback handler for quality selection and download
@app.on_callback_query(filters.regex(r"download_quality_https?://.*"))
async def download_selected_quality(client, callback_query):
    data = callback_query.data
    message = callback_query.message
    user_id = callback_query.from_user.id
    
    # Extract link and format_id from callback data
    # Example: download_quality_https://terabox.com/s/abcdef_formatid
    parts = data.split('_', 2) # Splits 'download', 'quality', and 'rest_of_string'
    if len(parts) < 3:
        await message.edit_text("कुछ गड़बड़ हो गई. कृपया फिर से कोशिश करें.")
        await callback_query.answer()
        return

    # The actual link and format_id are within parts[2]
    # We need to find the last underscore to separate format_id
    full_link_and_format_id = parts[2]
    
    last_underscore_index = full_link_and_format_id.rfind('_')
    if last_underscore_index == -1: # Should not happen if data is well-formed
        await message.edit_text("लिंक या फॉर्मेट पहचानने में समस्या हुई. फिर से कोशिश करें.")
        await callback_query.answer()
        return

    terabox_link = full_link_and_format_id[:last_underscore_index]
    format_id = full_link_and_format_id[last_underscore_index + 1:]
    
    # Sanitize terabox_link in case it contains extra callback_data prefixes
    if terabox_link.startswith("https:/") and not terabox_link.startswith("https://"): # Fix for common callback data issue
        terabox_link = terabox_link.replace("https:/", "https://", 1)


    user = await get_user_data(user_id)
    is_premium = await check_premium_status(user_id)
    today = datetime.date.today()

    # Reset daily downloads if it's a new day (re-check in case user clicked callback later)
    if user.get("last_download_date") is None or user["last_download_date"].date() != today:
        await update_user_data(user_id, {"daily_downloads": 0, "last_download_date": datetime.datetime.now()})
        user = await get_user_data(user_id) # Reload user data after reset


    if not is_premium and user["daily_downloads"] >= FREE_DOWNLOAD_LIMIT:
        await message.edit_text(
            f"🚫 ओह नो! आपकी आज की {FREE_DOWNLOAD_LIMIT} डाउनलोड लिमिट पूरी हो गई है. "
            "ज़्यादा डाउनलोड के लिए प्रीमियम ले लो या कल फिर ट्राई करना!"
            "\n\n💎 प्रीमियम प्लान्स देखने के लिए /premium दबाएं.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 प्रीमियम प्लान्स", callback_data="premium_plans")],
                [InlineKeyboardButton("🆘 मदद चाहिए?", callback_data="help_menu")]
            ])
        )
        await callback_query.answer()
        return

    # Acknowledge the callback immediately
    await callback_query.answer("आपका डाउनलोड शुरू हो रहा है! कृपया धैर्य रखें...")

    try:
        info_message = await message.edit_text("🚀 आपका डाउनलोड शुरू हो रहा है! कृपया इंतज़ार करें...")
        
        # Use a temporary filename unique to the user and download to avoid conflicts
        temp_filename = f"{user_id}_{int(time.time())}" # Unique temp name
        output_template = os.path.join(DOWNLOAD_DIR, temp_filename + '_%(title)s.%(ext)s')

        ydl_opts = {
            'format': format_id, # Use the selected format ID
            'outtmpl': output_template,
            'noplaylist': True,
            'verbose': False,
            'quiet': True,
            'no_warnings': True,
            'progress_hooks': [lambda d: asyncio.run_coroutine_threadsafe(
                download_progress_hook(d, info_message), app.loop)]
        }

        filepath = None
        with YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(terabox_link, download=True)
            # Find the actual downloaded file path
            # This can be tricky with yt-dlp, let's list files in the directory
            downloaded_files = [f for f in os.listdir(DOWNLOAD_DIR) if f.startswith(f"{user_id}_{temp_filename}")]
            if not downloaded_files:
                raise Exception("Downloaded file not found after yt-dlp.")
            
            filepath = os.path.join(DOWNLOAD_DIR, downloaded_files[0]) # Assuming only one file downloaded

        if not filepath or not os.path.exists(filepath):
            raise Exception("File not downloaded successfully or path incorrect.")

        # Update download counts
        await update_user_data(user_id, {
            "$inc": {"daily_downloads": 1, "total_downloads": 1}
        })

        file_size_bytes = os.path.getsize(filepath)
        file_size_mb = file_size_bytes / (1024 * 1024)

        # Telegram file size limit for non-premium is 2GB
        if file_size_mb > 2000 and not is_premium: 
            await info_message.edit_text(
                f"Oops! 😅 यह फ़ाइल **{file_size_mb:.2f} MB** की है, जो Telegram की फ़्री लिमिट (2GB) से ज़्यादा है.\n"
                "बड़ी फ़ाइलें डाउनलोड करने और भेजने के लिए **प्रीमियम** लें!"
            )
            os.remove(filepath) # Delete large file
            return

        # Send the file
        await info_message.edit_text(f"🥳 डाउनलोड पूरा हो गया! अब मैं फ़ाइल भेज रहा हूँ...")

        start_time = time.time()
        try:
            await client.send_document(
                chat_id=message.chat.id,
                document=filepath,
                caption=f"✅ आपका वीडियो `{info_dict.get('title', 'Video')}` डाउनलोड हो गया है!",
                progress=lambda current, total: asyncio.run_coroutine_threadsafe(
                    send_progress_hook(current, total, info_message, start_time), app.loop
                )
            )
            await info_message.edit_text(f"🚀 वीडियो सफलतापूर्वक भेज दिया गया! मौज करो!")
        except Exception as send_e:
            logger.error(f"Failed to send document for user {user_id}: {send_e}")
            await info_message.edit_text(f"फ़ाइल भेजने में समस्या हुई: `{send_e}`")


    except FloodWait as e:
        logger.warning(f"FloodWait while downloading/sending. Sleeping for {e.value} seconds.")
        await info_message.edit_text(f"टेलीग्राम की तरफ़ से थोड़ी देर के लिए रुकावट है. {e.value} सेकंड बाद फिर कोशिश करूँगा.")
        await asyncio.sleep(e.value + 5) # Add extra buffer
    except Exception as e:
        logger.error(f"Error during download or sending for user {user_id}: {e}")
        error_msg = f"😥 अरे यार! डाउनलोड या भेजने में कुछ गड़बड़ हो गई: `{e}`\n"
        if "No video formats" in str(e) or "Unsupported URL" in str(e).lower():
            error_msg = "😥 यह टेराबॉक्स लिंक काम नहीं कर रहा है या इसमें वीडियो नहीं है. " \
                        "कृपया सही लिंक भेजें."
        elif "Private video" in str(e).lower() or "This video is unavailable" in str(e).lower() or "not available" in str(e).lower():
            error_msg = "😥 यह वीडियो प्राइवेट है या उपलब्ध नहीं है. मैं इसे डाउनलोड नहीं कर सकता."
        
        await info_message.edit_text(error_msg)
    finally:
        # Clean up downloaded file
        if filepath and os.path.exists(filepath):
            await asyncio.sleep(600) # Wait 10 minutes before deleting
            try:
                os.remove(filepath)
                logger.info(f"Deleted downloaded file: {filepath}")
            except OSError as e:
                logger.error(f"Error deleting file {filepath}: {e}")
        # Clean up the parent directory if it's empty and was created by yt-dlp's output template
        # (yt-dlp sometimes creates sub-directories, though not expected with this outtmpl)
        if DOWNLOAD_DIR and os.path.exists(DOWNLOAD_DIR):
            try:
                # Remove empty subdirectories if any, not the main DOWNLOAD_DIR
                for root, dirs, files in os.walk(DOWNLOAD_DIR, topdown=False):
                    for d in dirs:
                        dir_path = os.path.join(root, d)
                        if not os.listdir(dir_path): # Check if directory is empty
                            shutil.rmtree(dir_path)
            except OSError as e:
                logger.error(f"Error cleaning up directories in {DOWNLOAD_DIR}: {e}")


# --- Progress Hooks for Download and Upload ---
# Store last update time for throttling
last_dl_update_time = {}
last_ul_update_time = {}

async def download_progress_hook(d, message_obj):
    """Updates download progress in real-time."""
    chat_id = message_obj.chat.id
    current_time = time.time()

    if chat_id not in last_dl_update_time:
        last_dl_update_time[chat_id] = 0

    if (current_time - last_dl_update_time[chat_id]) < 3: # Update every 3 seconds
        return

    if d['status'] == 'downloading':
        total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
        downloaded_bytes = d.get('downloaded_bytes', 0)
        
        if total_bytes > 0:
            percentage = (downloaded_bytes / total_bytes) * 100
            try:
                await message_obj.edit_text(
                    f"⬇️ डाउनलोड हो रहा है... **{percentage:.2f}%**\n"
                    f" (`{downloaded_bytes / (1024*1024):.2f} MB` / `{total_bytes / (1024*1024):.2f} MB`)"
                )
                last_dl_update_time[chat_id] = current_time
            except MessageNotModified:
                pass # Ignore if message content is the same
            except Exception as e:
                logger.warning(f"Error updating download progress message: {e}")

async def send_progress_hook(current, total, message_obj, start_time):
    """Updates upload progress in real-time."""
    chat_id = message_obj.chat.id
    current_time = time.time()

    if chat_id not in last_ul_update_time:
        last_ul_update_time[chat_id] = 0

    if (current_time - last_ul_update_time[chat_id]) < 3: # Update every 3 seconds
        return

    percentage = (current / total) * 100
    try:
        await message_obj.edit_text(
            f"⬆️ फ़ाइल अपलोड हो रही है... **{percentage:.2f}%**\n"
            f" (`{current / (1024*1024):.2f} MB` / `{total / (1024*1024):.2f} MB`)"
        )
        last_ul_update_time[chat_id] = current_time
    except MessageNotModified:
        pass # Ignore if message content is the same
    except Exception as e:
        logger.warning(f"Error updating upload progress message: {e}")

# --- Handle Screenshot Payments (Admin Notification) ---

@app.on_message(filters.photo & filters.private)
async def handle_screenshot(client, message):
    user_id = message.from_user.id
    caption = message.caption
    
    # Check if the photo caption indicates a payment screenshot
    # Or if it's just a photo from user who recently requested premium
    user = await get_user_data(user_id)
    
    # Heuristic: If user has 'buy_premium' in last 5 minutes AND sends a photo, it's likely a screenshot
    # For a robust system, you might add a 'waiting_for_payment_screenshot' flag in DB
    is_recent_premium_request = False # You would need to track this in DB based on callback data
    
    if (caption and ("payment" in caption.lower() or "screenshot" in caption.lower())) or \
       (message.reply_to_message and message.reply_to_message.from_user.is_self and "UPI ID" in message.reply_to_message.text): # Check if replying to bot's UPI message
        
        # Forward the screenshot to the admin
        await client.send_photo(
            chat_id=ADMIN_ID,
            photo=message.photo.file_id,
            caption=f"💰 **नया पेमेंट स्क्रीनशॉट!**\n\n"
                    f"यूज़र ID: `{user_id}`\n"
                    f"यूज़र का नाम: `{message.from_user.first_name}`\n"
                    f"यूज़र का यूज़रनेम: @{message.from_user.username or 'N/A'}\n\n"
                    "एडमिन, प्रीमियम एक्टिवेट करने के लिए `/addpremium` कमांड का उपयोग करें."
        )
        await message.reply_text(
            "👍 आपका पेमेंट स्क्रीनशॉट मेरे मालिक को भेज दिया गया है! "
            "धैर्य रखें, वे जल्द ही आपका प्रीमियम एक्टिवेट कर देंगे."
        )
    else:
        # If it's just a random photo, don't forward to admin unless it's explicitly a screenshot
        await message.reply_text("मुझे समझ नहीं आया. क्या यह पेमेंट स्क्रीनशॉट है? अगर हाँ, तो कृपया कैप्शन में 'screenshot' लिखें या पेमेंट वाले मैसेज का जवाब दें.")

# --- Main Bot Runner ---
async def main():
    logger.info("Starting Terabox Downloader Bot...")
    # Start the periodic reset task
    asyncio.create_task(reset_daily_downloads_task())
    await app.start()
    logger.info("Bot started!")
    await app.idle() # Keep the bot running until stopped

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
    finally:
        if app.is_connected:
            app.stop()
        logger.info("Bot process finished.")
