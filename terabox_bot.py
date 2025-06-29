import urllib.parse # Add this import at the top

# ... (rest of your imports) ...

# Global variable for your streaming app's base URL
# REPLACE THIS WITH YOUR ACTUAL DEPLOYED STREAMING APP URL
STREAMING_APP_BASE_URL = "https://bewildered-georgine-asmwasearchbot-d80957c4.koyeb.app/" # आपकी Koyeb ऐप की लिंक

# ... (rest of your bot code) ...

@app.on_message(filters.regex(r"(?i)https?://(?:www\.)?(terabox|nephobox|kofile|mirrobox|momoradar|www.4funbox\.com|www.sukifiles\.com|www.terabox\.com|www.teraboxapp\.com|teraboxapp\.com|terabox\.com|www.4hfile\.com|www.rapidgator\.net|www.kufile\.net|www.pandafiles\.com|www.subyshare\.com|www.filepress\.com|filepress\.com|m.terabox\.com)\.(com|app|net|cc|co|xyz|me|live|cloud|jp|ru|io|pw|site|online|ga|ml|tk|ai|info|store|shop|org|biz|club|fun|pro|sbs|digital|solutions|host|website|tech|dev|page|buzz|guru|news|press|top|blog|art|media|zone|icu|wiki|photos|tube|games|social|group|network|link|center|studio|design|agency|market|events|gallery|house|land|life|today|world|city|estate|fund|gold|health|inc|solutions|systems|tools|ventures|vodka|wedding|work|yoga|zone|academy|accountant|ad|ads|agency|ai|air|apartments|app|archi|associates|attorney|au|band|bar|bargains|beer|best|bid|bike|bio|biz|black|blog|blue|boutique|build|builders|business|cab|cafe|cam|camera|camp|capital|car|cards|care|careers|casa|cash|casino|catering|cc|center|ceo|church|city|claims|cleaning|clinic|clothing|cloud|coach|codes|coffee|college|community|company|computer|condos|construction|consulting|contractors|cool|coupons|credit|creditcard|cruises|dad|dance|data|date|deals|delivery|democrat|dental|design|diamonds|diet|digital|direct|directory|discount|doctor|dog|domains|education|email|energy|engineer|engineering|enterprises|equipment|estate|events|exchange|expert|express|faith|family|fan|farm|fashion|film|finance|financial|firm|fitness|flights|florist|flowers|football|forsale|foundation|fund|furniture|fyi|gallery|games|garden|gay|gent|gifts|gives|glass|global|gold|golf|graphics|gratis|green|gripe|guide|guitars|guru|haus|health|healthcare|help|here|hiphop|holdings|holiday|homes|horse|host|hosting|house|how|id|industries|info|ink|institute|insurance|insure|international|investments|irish|is|jetzt|jewelry|job|jobs|join|juegos|kaufen|kim|kitchen|land|lease|legal|lgbt|life|lighting|limited|live|llc|loan|loans|lol|london|ltd|maison|management|marketing|mba|media|memorial|men|menu|mobi|moda|moe|money|mortgage|mov|movie|museum|name|navy|network|new|news|ninja|nyc|okinawa|one|online|ooo|organic|partners|parts|party|photo|photography|photos|pics|pictures|pink|pizza|place|plumbing|plus|poker|porn|press|pro|productions|prof|properties|property|pub|qa|quebec|racing|recipes|red|rehab|reise|reisen|rent|rentals|repair|report|republican|restaurant|reviews|rip|rocks|rodeo|run|sarl|school|schule|science|scot|security|services|sex|sexy|shiksha|shoes|shop|shopping|show|singles|site|ski|soccer|social|software|solar|solutions|soy|space|studio|style|sucks|supplies|supply|support|surf|surgery|sydney|systems|tax|taxi|team|tech|technology|tel|telecom|tennis|theater|tickets|tienda|tips|tires|today|tools|tours|town|toys|trade|training|travel|tube|university|uno|vacations|ventures|vet|viajes|video|villas|vin|vision|vodka|vote|voting|voto|voyage|wales|wang|watch|webcam|website|wed|wedding|whoswho|wiki|win|wine|work|works|world|wtf|xyz|yachts|ye|yoga|zara)/[a-zA-Z0-9]+", filters.private))
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

        # Encode the original terabox link and video title for URL parameters
        encoded_terabox_link = urllib.parse.quote_plus(terabox_link)
        encoded_video_title = urllib.parse.quote_plus(video_title)

        # Construct the URL that points to your streaming server's HTML viewer page
        # This will be the URL for the "Watch" and "Download" buttons on Telegram
        media_viewer_url = f"{STREAMING_APP_BASE_URL}view_media?url={encoded_terabox_link}&title={encoded_video_title}"

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
