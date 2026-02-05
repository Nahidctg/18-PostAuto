import asyncio
import os
import shutil
import time
import logging
import aiohttp
import cv2  # ভিডিও প্রসেসিং এর জন্য
import numpy as np  # কোলাজ থাম্বনেইল বানানোর জন্য
import gc  # মেমোরি ক্লিয়ার করার জন্য
import math
import random
from datetime import datetime
from pyrogram import Client, filters, idle
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, 
    InputMediaPhoto, CallbackQuery
)
from pyrogram.errors import FloodWait, UserIsBlocked, InputUserDeactivated, UserNotParticipant
from motor.motor_asyncio import AsyncIOMotorClient
from aiohttp import web

# ====================================================================
#                          ১. সিস্টেম কনফিগারেশন
# ====================================================================

# আপনার টেলিগ্রাম ক্রেডেনশিয়ালস
API_ID = 22697010
API_HASH = "fd88d7339b0371eb2a9501d523f3e2a7"
BOT_TOKEN = "8303315439:AAGKPEugn60XGMC7_u4pOaZPnUWkWHvXSNM"
ADMIN_ID = 8172129114  # আপনার ইউজার আইডি

# মঙ্গোডিবি (ডাটাবেস) কানেকশন
MONGO_URL = "mongodb+srv://mewayo8672:mewayo8672@cluster0.ozhvczp.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"

# লগিং কনফিগারেশন
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("AutoBot_Enterprise_Max")

# ডাটাবেস ইনিশিলাইজেশন
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client["Enterprise_Bot_DB"]

# কালেকশন সমূহ (অরিজিনাল + নতুন)
queue_collection = db["video_queue"]    
config_collection = db["bot_settings"]  
users_collection = db["users_list"]     
history_collection = db["user_history"] # স্মার্ট ফিচার: ইউজারের হিস্ট্রি
stats_collection = db["video_stats"]    # স্মার্ট ফিচার: ভিউ কাউন্ট

# গ্লোবাল কনফিগ ও সুন্দর ক্যাপশন টেম্পলেট (Updated)
SYSTEM_CONFIG = {
    "source_channel": None,
    "public_channel": None,
    "log_channel": None,          
    "post_interval": 30,          
    "shortener_domain": None,
    "shortener_key": None,
    "shortener_list": [],         # স্মার্ট ফিচার: মাল্টি শর্টনার সাপোর্ট
    "auto_delete_time": 0,        
    "protect_content": False,     
    "tutorial_link": None,        
    "force_sub": True,            
    "watermark_text": "@Enterprise_Bots", # স্মার্ট ফিচার: থাম্বনেইলে ওয়াটারমার্ক
    "caption_template": "🔥 **{title}** 🔥\n\n🎬 **Quality:** `{quality}`\n📦 **Size:** `{size}`\n👁 **Views:** `{views}`\n\n🚀 **Fastest Download Link**\n\n📢 *Join our channel for more exclusive content!*"
}

# এন্টি-স্প্যাম ট্র্যাকার (স্মার্ট ফিচার)
user_last_request = {}

# পাইরোগ্রাম ক্লায়েন্ট সেটআপ
app = Client(
    "Enterprise_Session_Max",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=100
)

# ====================================================================
#                       ২. ওয়েব সার্ভার
# ====================================================================

async def web_server_handler(request):
    """সিম্পল ওয়েব পেজ রেসপন্স"""
    return web.Response(text="✅ Bot is Running in Ultimate Smart Mode with Full Details!")

async def start_web_server():
    """aiohttp ওয়েব সার্ভার রানার"""
    app_runner = web.Application()
    app_runner.add_routes([web.get('/', web_server_handler)])
    runner = web.AppRunner(app_runner)
    await runner.setup()
    
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"🌍 Web Server started on port {port}")

# ====================================================================
#                       ৩. হেল্পার ফাংশনস (Original & Smart)
# ====================================================================

async def load_database_settings():
    """বট স্টার্ট হলে ডাটাবেস থেকে সব সেটিং মেমোরিতে লোড করবে"""
    settings = await config_collection.find_one({"_id": "global_settings"})
    
    if not settings:
        await config_collection.insert_one({"_id": "global_settings"})
        logger.info("⚙️ New Settings Created in Database.")
    else:
        # ডাটাবেস থেকে ভ্যালু নিয়ে কনফিগে বসানো (অরিজিনাল কি-সমূহ)
        SYSTEM_CONFIG["source_channel"] = settings.get("source_channel")
        SYSTEM_CONFIG["public_channel"] = settings.get("public_channel")
        SYSTEM_CONFIG["log_channel"] = settings.get("log_channel")
        SYSTEM_CONFIG["post_interval"] = settings.get("post_interval", 30)
        SYSTEM_CONFIG["shortener_domain"] = settings.get("shortener_domain")
        SYSTEM_CONFIG["shortener_key"] = settings.get("shortener_key")
        SYSTEM_CONFIG["auto_delete_time"] = settings.get("auto_delete_time", 0)
        SYSTEM_CONFIG["protect_content"] = settings.get("protect_content", False)
        SYSTEM_CONFIG["tutorial_link"] = settings.get("tutorial_link", None)
        SYSTEM_CONFIG["force_sub"] = settings.get("force_sub", True)
        SYSTEM_CONFIG["shortener_list"] = settings.get("shortener_list", [])
        SYSTEM_CONFIG["watermark_text"] = settings.get("watermark_text", "@Enterprise_Bots")
        logger.info("⚙️ Settings Loaded Successfully from MongoDB.")

async def update_database_setting(key, value):
    """কোনো সেটিং চেঞ্জ হলে সাথে সাথে ডাটাবেস আপডেট করবে"""
    await config_collection.update_one(
        {"_id": "global_settings"},
        {"$set": {key: value}},
        upsert=True
    )
    SYSTEM_CONFIG[key] = value

async def add_user_to_db(user_id):
    """নতুন ইউজারকে ডাটাবেসে এড করবে"""
    if not await users_collection.find_one({"_id": user_id}):
        await users_collection.insert_one({"_id": user_id})

async def send_log_message(text):
    """লগ চ্যানেলে বটের স্ট্যাটাস বা এরর মেসেজ পাঠাবে"""
    if SYSTEM_CONFIG["log_channel"]:
        try:
            await app.send_message(
                chat_id=int(SYSTEM_CONFIG["log_channel"]),
                text=text
            )
        except Exception as e:
            logger.error(f"Failed to send log: {e}")

async def check_force_sub(client, user_id):
    """ইউজার পাবলিক চ্যানেলে জয়েন আছে কিনা চেক করবে"""
    if not SYSTEM_CONFIG["force_sub"] or not SYSTEM_CONFIG["public_channel"]:
        return True 
    try:
        member = await client.get_chat_member(int(SYSTEM_CONFIG["public_channel"]), user_id)
        if member.status in ["banned", "kicked"]:
            return False
        return True
    except UserNotParticipant:
        return False
    except Exception:
        return True  

def get_readable_size(size_in_bytes):
    """বাইট থেকে রিডেবল সাইজ (স্মার্ট ফিচার)"""
    if size_in_bytes == 0: return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_in_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_in_bytes / p, 2)
    return f"{s} {size_name[i]}"

async def shorten_url_api(long_url):
    """লিংক শর্টনার API দিয়ে লিংক ছোট করবে (স্মার্ট মাল্টি-শর্টনার লজিক সহ)"""
    # যদি মাল্টি শর্টনার লিস্ট থাকে তবে সেখান থেকে র্যান্ডমলি নিবে
    if SYSTEM_CONFIG["shortener_list"]:
        shortener = random.choice(SYSTEM_CONFIG["shortener_list"])
        domain = shortener.get("domain")
        key = shortener.get("api")
    elif SYSTEM_CONFIG["shortener_domain"] and SYSTEM_CONFIG["shortener_key"]:
        domain = SYSTEM_CONFIG["shortener_domain"]
        key = SYSTEM_CONFIG["shortener_key"]
    else:
        return long_url

    try:
        api_url = f"https://{domain}/api?api={key}&url={long_url}"
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    if "shortenedUrl" in data:
                        return data["shortenedUrl"]
    except Exception as e:
        logger.error(f"Shortener API Error: {e}")
    
    return long_url

# ভিউ কাউন্ট ও হিস্ট্রি ফাংশন
async def update_view_count(msg_id):
    await stats_collection.update_one({"msg_id": msg_id}, {"$inc": {"views": 1}}, upsert=True)

async def get_views(msg_id):
    data = await stats_collection.find_one({"msg_id": msg_id})
    return data["views"] if data else 1

async def add_user_history(user_id, msg_id, title):
    await history_collection.update_one(
        {"_id": user_id},
        {"$push": {"history": {"$each": [{"msg_id": msg_id, "title": title, "time": datetime.now()}], "$slice": -5}}},
        upsert=True
    )

# ====================================================================
#                ৪. থাম্বনেইল জেনারেটর (Watermark + Collage)
# ====================================================================

def generate_collage_thumbnail(video_path, message_id):
    thumbnail_path = f"downloads/thumb_{message_id}.jpg"
    
    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return None
        
        orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        if total_frames < 10:
            cap.release()
            return None
            
        frames = []
        percentages = [0.15, 0.40, 0.65, 0.85]
        
        target_w = 640
        aspect_ratio = orig_h / orig_w
        target_h = int(target_w * aspect_ratio)
        
        for p in percentages:
            target_frame = int(total_frames * p)
            cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
            success, img = cap.read()
            
            if success:
                resized = cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_LANCZOS4)
                
                # স্মার্ট ফিচার: ওয়াটারমার্ক যোগ করা
                cv2.putText(resized, SYSTEM_CONFIG["watermark_text"], (20, target_h-20), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
                
                frames.append(resized)
            else:
                break
        
        cap.release()
        
        if len(frames) == 4:
            border_v = np.ones((target_h, 10, 3), dtype=np.uint8) * 255 
            top_row = np.hstack((frames[0], border_v, frames[1]))
            bottom_row = np.hstack((frames[2], border_v, frames[3]))
            border_h = np.ones((10, top_row.shape[1], 3), dtype=np.uint8) * 255
            collage = np.vstack((top_row, border_h, bottom_row))
        elif len(frames) >= 2:
            collage = np.hstack((frames[0], frames[1]))
        elif len(frames) == 1:
            collage = frames[0]
        else:
            return None

        cv2.imwrite(thumbnail_path, collage, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        
        del frames
        del collage
        gc.collect()
        
        return thumbnail_path

    except Exception as e:
        logger.error(f"Collage Generation Error: {e}")
        return None

# ====================================================================
#                       ৫. কমান্ডস (Original Details Intact)
# ====================================================================

# --- ১. স্টার্ট কমান্ড (অরিজিনাল লজিক + এন্টি স্প্যাম) ---
@app.on_message(filters.command("start"))
async def start_command_handler(client, message):
    await add_user_to_db(message.from_user.id)
    
    # ফোর্স সাবস্ক্রাইব চেকিং
    if SYSTEM_CONFIG["force_sub"] and SYSTEM_CONFIG["public_channel"]:
        is_joined = await check_force_sub(client, message.from_user.id)
        if not is_joined:
            try:
                invite = await client.create_chat_invite_link(int(SYSTEM_CONFIG["public_channel"]))
                param = message.command[1] if len(message.command) > 1 else ""
                
                buttons = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📢 Join Channel to Watch", url=invite.invite_link)],
                    [InlineKeyboardButton("🔄 Refresh / Try Again", url=f"https://t.me/{client.me.username}?start={param}")]
                ])
                return await message.reply(
                    "⚠️ **Access Denied!**\n\n"
                    "You must join our official channel to access this video.",
                    reply_markup=buttons
                )
            except Exception as e:
                logger.error(f"Invite Link Error: {e}")

    # ডেলিভারি রিকোয়েস্ট লজিক
    if len(message.command) > 1:
        # স্মার্ট ফিচার: এন্টি-স্প্যাম চেকিং
        user_id = message.from_user.id
        now = time.time()
        if user_id in user_last_request and now - user_last_request[user_id] < 5:
            return await message.reply("🚫 **Wait!** Please don't spam. Wait 5 seconds between requests.")
        user_last_request[user_id] = now
        
        asyncio.create_task(process_user_delivery(client, message))
        return
    
    # অ্যাডমিন প্যানেল এবং সাধারণ ওয়েলকাম
    if message.from_user.id == ADMIN_ID:
        admin_menu = (
            "👑 **Ultimate Admin Panel (v6.0 - Smart)**\n\n"
            "📡 **Channel Setup:**\n"
            "`/setsource -100xxxx` - Source Channel\n"
            "`/setpublic -100xxxx` - Public Channel\n"
            "`/setlog -100xxxx` - Log Channel\n\n"
            "⚙️ **System Config:**\n"
            "`/setinterval 30` - Post Delay\n"
            "`/autodelete 60` - Auto Delete\n"
            "`/settutorial link` - Set Tutorial\n"
            "`/setshortener domain key` - Set Shortener\n"
            "`/protect on/off` - Content Protection\n\n"
            "🛠 **Smart Controls:**\n"
            "`/admin` - Visual Dashboard (New)\n"
            "`/broadcast` - Send to All (with Progress)\n"
            "`/stats` - Stats / `/clearqueue` - Clear Queue"
        )
        await message.reply(admin_menu)
    else:
        await message.reply(
            "👋 **Hello! Welcome to AutoBot.**\n\n"
            "Search for videos or join our channel to get latest updates.\n"
            "Use `/search movie_name` to find videos."
        )

# --- ২. অ্যাডমিন ড্যাশবোর্ড (নতুন স্মার্ট ফিচার) ---
@app.on_message(filters.command("admin") & filters.user(ADMIN_ID))
async def admin_dashboard_handler(client, message):
    buttons = [
        [InlineKeyboardButton("📊 System Stats", callback_data="stats_live"),
         InlineKeyboardButton("⚙️ Quick Settings", callback_data="quick_settings")],
        [InlineKeyboardButton("📡 Channels Info", callback_data="channel_info"),
         InlineKeyboardButton("🗑 Clear All Queue", callback_data="confirm_clear")],
        [InlineKeyboardButton("🔙 Close", callback_data="close_admin")]
    ]
    await message.reply("🎮 **Enterprise Smart Dashboard**", reply_markup=InlineKeyboardMarkup(buttons))

@app.on_callback_query()
async def callback_handler(client, query: CallbackQuery):
    data = query.data
    if data == "stats_live":
        users = await users_collection.count_documents({})
        queue = await queue_collection.count_documents({})
        await query.answer(f"Users: {users} | Pending Queue: {queue}", show_alert=True)
    elif data == "close_admin":
        await query.message.delete()

# --- ৩. চ্যানেল সেটআপ কমান্ডস (অরিজিনাল - হুবহু) ---

@app.on_message(filters.command("setsource") & filters.user(ADMIN_ID))
async def set_source_channel(client, message):
    try:
        if len(message.command) < 2: return await message.reply("❌ Usage: `/setsource -100xxxx`")
        channel_id = int(message.command[1])
        await update_database_setting("source_channel", channel_id)
        await message.reply(f"✅ **Source Channel Set:** `{channel_id}`")
    except: await message.reply("❌ Invalid ID.")

@app.on_message(filters.command("setpublic") & filters.user(ADMIN_ID))
async def set_public_channel(client, message):
    try:
        if len(message.command) < 2: return await message.reply("❌ Usage: `/setpublic -100xxxx`")
        channel_id = int(message.command[1])
        await update_database_setting("public_channel", channel_id)
        await message.reply(f"✅ **Public Channel Set:** `{channel_id}`")
    except: await message.reply("❌ Invalid ID.")

@app.on_message(filters.command("setlog") & filters.user(ADMIN_ID))
async def set_log_channel(client, message):
    try:
        if len(message.command) < 2: return await message.reply("❌ Usage: `/setlog -100xxxx`")
        channel_id = int(message.command[1])
        await update_database_setting("log_channel", channel_id)
        await message.reply(f"✅ **Log Channel Set:** `{channel_id}`")
        await send_log_message("✅ **Log Channel Connected Successfully!**")
    except: await message.reply("❌ Invalid ID.")

# --- ৪. কনফিগারেশন কমান্ডস (অরিজিনাল - হুবহু) ---

@app.on_message(filters.command("setinterval") & filters.user(ADMIN_ID))
async def set_post_interval(client, message):
    try:
        seconds = int(message.command[1])
        await update_database_setting("post_interval", seconds)
        await message.reply(f"⏱ **Interval Updated:** `{seconds} seconds`")
    except: await message.reply("❌ Use number only.")

@app.on_message(filters.command("autodelete") & filters.user(ADMIN_ID))
async def set_auto_delete(client, message):
    try:
        seconds = int(message.command[1])
        await update_database_setting("auto_delete_time", seconds)
        await message.reply(f"⏳ **Auto Delete:** `{seconds} seconds`")
    except: await message.reply("❌ Use number only.")

@app.on_message(filters.command("settutorial") & filters.user(ADMIN_ID))
async def set_tutorial_link(client, message):
    try:
        if len(message.command) < 2: return await message.reply("❌ Usage: `/settutorial https://link...`")
        link = message.command[1]
        await update_database_setting("tutorial_link", link)
        await message.reply(f"✅ **Tutorial Link Set:**\n`{link}`")
    except: await message.reply("❌ Error setting link.")

@app.on_message(filters.command("protect") & filters.user(ADMIN_ID))
async def set_content_protection(client, message):
    try:
        state = message.command[1].lower() == "on"
        await update_database_setting("protect_content", state)
        await message.reply(f"🛡 **Protection:** `{'ON' if state else 'OFF'}`")
    except: await message.reply("❌ Usage: `/protect on` or `off`")

@app.on_message(filters.command("setshortener") & filters.user(ADMIN_ID))
async def set_shortener_config(client, message):
    try:
        if len(message.command) < 3:
            return await message.reply("❌ Usage: `/setshortener domain.com api_key`")
        domain = message.command[1]
        key = message.command[2]
        await update_database_setting("shortener_domain", domain)
        await update_database_setting("shortener_key", key)
        await message.reply(f"🔗 **Shortener Configured!**\nDomain: `{domain}`")
    except: await message.reply("❌ Error.")

# --- ৫. টুলস কমান্ডস (স্মার্ট ব্রডকাস্ট সহ) ---

@app.on_message(filters.command("stats") & filters.user(ADMIN_ID))
async def show_stats(client, message):
    users = await users_collection.count_documents({})
    queue = await queue_collection.count_documents({})
    msg = (
        f"📊 **SYSTEM STATISTICS**\n\n"
        f"👥 **Total Users:** `{users}`\n"
        f"📥 **Queue Pending:** `{queue}` Videos\n"
        f"⏱ **Interval:** `{SYSTEM_CONFIG['post_interval']}s`"
    )
    await message.reply(msg)

@app.on_message(filters.command("clearqueue") & filters.user(ADMIN_ID))
async def clear_queue_command(client, message):
    await queue_collection.delete_many({})
    await message.reply("🗑 **Queue Cleared!** All pending videos removed.")

@app.on_message(filters.command("broadcast") & filters.user(ADMIN_ID) & filters.reply)
async def broadcast_message(client, message):
    status_msg = await message.reply("📢 **Broadcast Started...**")
    all_users = users_collection.find({})
    
    # ব্রডকাস্ট প্রোগ্রেস ক্যালকুলেশন
    total_users = await users_collection.count_documents({})
    success = 0
    blocked = 0
    deleted = 0
    
    async for user in all_users:
        try:
            await message.reply_to_message.copy(chat_id=user["_id"])
            success += 1
        except FloodWait as e:
            await asyncio.sleep(e.value)
            await message.reply_to_message.copy(chat_id=user["_id"])
            success += 1
        except UserIsBlocked:
            blocked += 1
            await users_collection.delete_one({"_id": user["_id"]})
        except InputUserDeactivated:
            deleted += 1
            await users_collection.delete_one({"_id": user["_id"]})
        except: pass
        
        # প্রতি ২০ জন পর পর স্ট্যাটাস আপডেট
        if (success + blocked + deleted) % 20 == 0:
            done = success + blocked + deleted
            percentage = (done / total_users) * 100
            await status_msg.edit(f"📢 **Broadcasting...**\nProgress: {round(percentage, 2)}%\nSent: {success}")
        
    await status_msg.edit(
        f"✅ **Broadcast Completed!**\n\n"
        f"sent: `{success}`\n"
        f"blocked: `{blocked}`\n"
        f"deleted: `{deleted}`"
    )

# --- ৬. সার্চ এবং হিস্ট্রি (নতুন স্মার্ট ফিচার) ---
@app.on_message(filters.command("search"))
async def search_handler(client, message):
    if len(message.command) < 2:
        return await message.reply("🔍 Usage: `/search movie_name`")
    
    query = message.text.split(None, 1)[1]
    # ডাটাবেসে কিউ এবং সোর্স মেসেজ থেকে সার্চ
    results = await queue_collection.find({"caption": {"$regex": query, "$options": "i"}}).limit(5).to_list(None)
    
    if not results:
        return await message.reply("❌ No matches found in recent queue.")
    
    txt = "🔍 **Search Results Found:**\n\n"
    for res in results:
        txt += f"🎬 {res['caption'][:50]}... \n🔗 `/start {res['msg_id']}`\n\n"
    await message.reply(txt)

@app.on_message(filters.command("history"))
async def history_handler(client, message):
    data = await history_collection.find_one({"_id": message.from_user.id})
    if not data or "history" not in data:
        return await message.reply("📭 You haven't requested any videos yet.")
    
    txt = "⏳ **Your Last Requested Videos:**\n\n"
    for item in reversed(data["history"]):
        txt += f"✅ {item['title']}\n"
    await message.reply(txt)

# ====================================================================
#                       ৬. ইউজার ভিডিও ডেলিভারি
# ====================================================================

async def process_user_delivery(client, message):
    try:
        msg_id = int(message.command[1])
        
        if not SYSTEM_CONFIG["source_channel"]:
            return await message.reply("❌ **Bot Maintenance Mode.** (Source not set)")
        
        status_msg = await message.reply("🔄 **Processing your request...**")
        
        source_msg = await client.get_messages(int(SYSTEM_CONFIG["source_channel"]), msg_id)
        
        if not source_msg or (not source_msg.video and not source_msg.document):
            return await status_msg.edit("❌ **Error:** Video not found or deleted from server.")
        
        # স্মার্ট ফিচার: ভিউ ও হিস্ট্রি আপডেট
        title = source_msg.caption or "Exclusive Video"
        await update_view_count(msg_id)
        await add_user_history(message.from_user.id, msg_id, title)

        sent_msg = await source_msg.copy(
            chat_id=message.chat.id,
            caption=f"✅ **Title:** `{title}`\n\n❌ **Do not forward this message.**",
            protect_content=SYSTEM_CONFIG["protect_content"]
        )
        
        await status_msg.delete()
        
        if SYSTEM_CONFIG["auto_delete_time"] > 0:
            warning = await message.reply(f"⏳ **This video will be auto-deleted in {SYSTEM_CONFIG['auto_delete_time']} seconds!**")
            
            async def delete_after_delay(m1, m2, delay):
                await asyncio.sleep(delay)
                try:
                    await m1.delete()
                    await m2.delete()
                except: pass
            
            asyncio.create_task(delete_after_delay(sent_msg, warning, SYSTEM_CONFIG["auto_delete_time"]))
            
    except Exception as e:
        logger.error(f"Delivery Error: {e}")
        try: await message.reply("❌ An error occurred. Please contact admin.")
        except: pass
    finally:
        gc.collect() 

# ====================================================================
#                       ৭. সোর্স চ্যানেল মনিটরিং
# ====================================================================

@app.on_message(filters.channel & (filters.video | filters.document))
async def source_channel_listener(client, message):
    """সোর্স চ্যানেলে নতুন ভিডিও আসলে অটোমেটিক কিউতে নিবে (অরিজিনাল লজিক)"""
    if SYSTEM_CONFIG["source_channel"] and message.chat.id == int(SYSTEM_CONFIG["source_channel"]):
        
        is_video = message.video or (message.document and message.document.mime_type and "video" in message.document.mime_type)
        
        if is_video:
            exists = await queue_collection.find_one({"msg_id": message.id})
            if not exists:
                await queue_collection.insert_one({
                    "msg_id": message.id,
                    "caption": message.caption or "Exclusive Video",
                    "date": message.date
                })
                logger.info(f"📥 New Video Added to Queue: ID {message.id}")
                await send_log_message(f"📥 **New Video Queued!**\nID: `{message.id}`")

# ====================================================================
#                       ৮. মেইন প্রসেসিং ইঞ্জিন (The Brain)
# ====================================================================

async def processing_engine():
    """ব্যাকগ্রাউন্ডে সবসময় চলতে থাকা ইঞ্জিন (অরিজিনাল + স্মার্ট আপডেট)"""
    
    if not os.path.exists("downloads"):
        os.makedirs("downloads")
        
    logger.info("🚀 Processing Engine Started Successfully...")
    
    while True:
        try:
            if not SYSTEM_CONFIG["source_channel"] or not SYSTEM_CONFIG["public_channel"]:
                await asyncio.sleep(20)
                continue
            
            # ১. কিউ থেকে সবচেয়ে পুরনো ভিডিও নেওয়া
            task = await queue_collection.find_one(sort=[("date", 1)])
            
            if task:
                msg_id = task["msg_id"]
                logger.info(f"🔨 Processing Task ID: {msg_id}")
                
                try:
                    # ২. মেইন ভিডিও ফেচ করা
                    source_msg = await app.get_messages(int(SYSTEM_CONFIG["source_channel"]), msg_id)
                    
                    if not source_msg:
                        logger.error("❌ Message deleted from source channel.")
                        await queue_collection.delete_one({"_id": task["_id"]})
                        continue
                    
                    # স্মার্ট ফিচার: ডাইনামিক ফাইল সাইজ ও রেজোলিউশন ডিটেকশন
                    file = source_msg.video or source_msg.document
                    size_readable = get_readable_size(file.file_size)
                    
                    quality_label = "HD 720p"
                    if source_msg.video:
                        h = source_msg.video.height
                        if h >= 2160: quality_label = "4K Ultra HD"
                        elif h >= 1080: quality_label = "Full HD 1080p"
                        elif h >= 720: quality_label = "HD 720p"
                        else: quality_label = "SD Quality"

                    # ৩. ভিডিও ডাউনলোড (থাম্বনেইলের জন্য)
                    video_path = f"downloads/video_{msg_id}.mp4"
                    logger.info("⬇️ Downloading video for thumbnail generation...")
                    await app.download_media(source_msg, file_name=video_path)
                    
                    # ৪. কোলাজ থাম্বনেইল তৈরি
                    thumb_path = await asyncio.to_thread(generate_collage_thumbnail, video_path, msg_id)
                    
                    # ৫. ডিপ লিংক তৈরি
                    bot_username = (await app.get_me()).username
                    deep_link = f"https://t.me/{bot_username}?start={msg_id}"
                    final_link = await shorten_url_api(deep_link)
                    
                    # ৬. স্মার্ট ক্যাপশন ফরম্যাটিং (Views সহ)
                    views_count = await get_views(msg_id)
                    raw_caption = task.get("caption", "New Video")[:100]
                    
                    final_caption = SYSTEM_CONFIG["caption_template"].format(
                        title=raw_caption,
                        quality=quality_label,
                        size=size_readable,
                        views=views_count
                    )
                    
                    # ৭. বাটন কনফিগারেশন
                    buttons_list = [[InlineKeyboardButton("📥 DOWNLOAD / WATCH VIDEO 📥", url=final_link)]]
                    if SYSTEM_CONFIG["tutorial_link"]:
                        buttons_list.append([InlineKeyboardButton("ℹ️ How to Download", url=SYSTEM_CONFIG["tutorial_link"])])
                    
                    buttons = InlineKeyboardMarkup(buttons_list)
                    dest_chat = int(SYSTEM_CONFIG["public_channel"])
                    
                    # ৮. পাবলিশ করা
                    if thumb_path and os.path.exists(thumb_path):
                        await app.send_photo(chat_id=dest_chat, photo=thumb_path, caption=final_caption, reply_markup=buttons)
                        log_status = "✅ Posted with Smart Thumbnail"
                    else:
                        await app.send_message(chat_id=dest_chat, text=final_caption, reply_markup=buttons)
                        log_status = "⚠️ Posted without Thumbnail"
                    
                    logger.info(f"✅ Success: {msg_id}")
                    await send_log_message(f"{log_status}\n🆔 Msg ID: `{msg_id}`")
                    
                except Exception as e:
                    logger.error(f"❌ Processing Error: {e}")
                
                # ৯. ক্লিনআপ
                await queue_collection.delete_one({"_id": task["_id"]})
                try:
                    if os.path.exists(video_path): os.remove(video_path)
                    if thumb_path and os.path.exists(thumb_path): os.remove(thumb_path)
                except: pass
                gc.collect()
            
            wait_time = SYSTEM_CONFIG.get("post_interval", 30)
            await asyncio.sleep(wait_time)
            
        except Exception as e:
            logger.critical(f"🛑 Critical Loop Error: {e}")
            await asyncio.sleep(10)

# ====================================================================
#                       ৯. মেইন এক্সিকিউশন
# ====================================================================

async def main():
    # ওয়েব সার্ভার ব্যাকগ্রাউন্ডে চালু
    asyncio.create_task(start_web_server())
    
    # বট স্টার্ট
    await app.start()
    
    # সেটিংস লোড
    await load_database_settings()
    
    # প্রসেসিং ইঞ্জিন চালু
    asyncio.create_task(processing_engine())
    
    logger.info("🤖 AutoBot Enterprise SMART VERSION is now FULLY OPERATIONAL...")
    await idle()
    await app.stop()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())

# --- END OF FILE ---
