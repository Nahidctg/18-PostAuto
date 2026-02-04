import asyncio
import os
import shutil
import time
import logging
import aiohttp
import cv2
import functools  # For blocking code
from concurrent.futures import ThreadPoolExecutor
from pyrogram import Client, filters, idle
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, 
    InputMediaPhoto
)
from pyrogram.errors import FloodWait, UserIsBlocked, InputUserDeactivated, UserNotParticipant
from motor.motor_asyncio import AsyncIOMotorClient
from aiohttp import web

# ====================================================================
#                          ১. সিস্টেম কনফিগারেশন
# ====================================================================

API_ID = 22697010
API_HASH = "fd88d7339b0371eb2a9501d523f3e2a7"
BOT_TOKEN = "8303315439:AAGKPEugn60XGMC7_u4pOaZPnUWkWHvXSNM"
MONGO_URL = "mongodb+srv://mewayo8672:mewayo8672@cluster0.ozhvczp.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
ADMIN_ID = 8172129114

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("AutoBot_Pro_V2")

# ডাটাবেস সেটআপ
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client["Enterprise_Bot_DB"]
queue_collection = db["video_queue"]
config_collection = db["bot_settings"]
users_collection = db["users_list"]  # নতুন: ইউজার ডাটাবেস

# থ্রেড পুল (Non-blocking অপারেশনের জন্য)
thread_pool = ThreadPoolExecutor(max_workers=4)

SYSTEM_CONFIG = {
    "source_channel": None,
    "public_channel": None,
    "post_interval": 30,
    "shortener_domain": None,
    "shortener_key": None,
    "auto_delete_time": 0,
    "protect_content": False,
    "force_sub": True,  # নতুন: ফোর্স সাবস্ক্রাইব ডিফল্ট অন
    "caption_template": "🎬 **{caption}**\n\n✨ **Quality:** HD 720p\n🔥 **Exclusive Content**"
}

app = Client("Enterprise_Session_V2", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ====================================================================
#                       ২. ওয়েব সার্ভার (Keep Alive)
# ====================================================================

async def web_server_handler(request):
    return web.Response(text="✅ Bot is Running with V2 Updates!")

async def start_web_server():
    app_runner = web.Application()
    app_runner.add_routes([web.get('/', web_server_handler)])
    runner = web.AppRunner(app_runner)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"🌍 Web Server started on port {port}")

# ====================================================================
#                       ৩. হেল্পার ফাংশনস (আপডেটেড)
# ====================================================================

async def load_database_settings():
    settings = await config_collection.find_one({"_id": "global_settings"})
    if not settings:
        await config_collection.insert_one({"_id": "global_settings"})
    else:
        SYSTEM_CONFIG["source_channel"] = settings.get("source_channel")
        SYSTEM_CONFIG["public_channel"] = settings.get("public_channel")
        SYSTEM_CONFIG["post_interval"] = settings.get("post_interval", 30)
        SYSTEM_CONFIG["shortener_domain"] = settings.get("shortener_domain")
        SYSTEM_CONFIG["shortener_key"] = settings.get("shortener_key")
        SYSTEM_CONFIG["auto_delete_time"] = settings.get("auto_delete_time", 0)
        SYSTEM_CONFIG["protect_content"] = settings.get("protect_content", False)
        SYSTEM_CONFIG["force_sub"] = settings.get("force_sub", True)
        logger.info("⚙️ Settings Loaded Successfully.")

async def update_database_setting(key, value):
    await config_collection.update_one(
        {"_id": "global_settings"},
        {"$set": {key: value}},
        upsert=True
    )
    SYSTEM_CONFIG[key] = value

async def add_user_to_db(user_id):
    """নতুন ইউজার ডাটাবেসে এড করবে"""
    if not await users_collection.find_one({"_id": user_id}):
        await users_collection.insert_one({"_id": user_id})

async def check_force_sub(client, user_id):
    """ফোর্স সাবস্ক্রাইব চেক"""
    if not SYSTEM_CONFIG["force_sub"] or not SYSTEM_CONFIG["public_channel"]:
        return True
    try:
        member = await client.get_chat_member(int(SYSTEM_CONFIG["public_channel"]), user_id)
        if member.status in ["banned", "kicked"]:
            return False
        return True
    except UserNotParticipant:
        return False
    except Exception as e:
        logger.error(f"FSub Error: {e}")
        return True # এরর হলে বাইপাস

async def shorten_url(long_url):
    if not SYSTEM_CONFIG["shortener_domain"] or not SYSTEM_CONFIG["shortener_key"]:
        return long_url
    try:
        api_url = f"https://{SYSTEM_CONFIG['shortener_domain']}/api?api={SYSTEM_CONFIG['shortener_key']}&url={long_url}"
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    if "shortenedUrl" in data: return data["shortenedUrl"]
    except Exception as e:
        logger.error(f"Shortener Failed: {e}")
    return long_url

# 🔥 ব্লকিং কোড থ্রেডে রান করার জন্য র্যাপার
def run_in_thread(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(thread_pool, functools.partial(func, *args, **kwargs))
    return wrapper

@run_in_thread
def generate_thumbnail_opencv(video_path, message_id):
    """Blocking OpenCV Code running in Thread"""
    thumbnail_path = f"downloads/thumb_{message_id}.jpg"
    try:
        video_cap = cv2.VideoCapture(video_path)
        if not video_cap.isOpened(): return None
        
        total_frames = video_cap.get(cv2.CAP_PROP_FRAME_COUNT)
        fps = video_cap.get(cv2.CAP_PROP_FPS)
        duration = total_frames / fps if fps > 0 else 0
        
        target_time = 10 if duration > 15 else (duration / 2)
        target_frame = int(target_time * fps)
        
        video_cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        success, image = video_cap.read()
        
        if success:
            cv2.imwrite(thumbnail_path, image, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
            video_cap.release()
            return thumbnail_path
        video_cap.release()
    except Exception as e:
        logger.error(f"Thumbnail Generation Error: {e}")
    return None

# ====================================================================
#                       ৪. অ্যাডমিন কমান্ডস (Broadcast সহ)
# ====================================================================

@app.on_message(filters.command("start"))
async def start_handler(client, message):
    await add_user_to_db(message.from_user.id)
    
    # Force Subscribe Check
    if SYSTEM_CONFIG["force_sub"] and SYSTEM_CONFIG["public_channel"]:
        is_joined = await check_force_sub(client, message.from_user.id)
        if not is_joined:
            try:
                invite_link = await client.create_chat_invite_link(int(SYSTEM_CONFIG["public_channel"]))
                buttons = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📢 Join Channel First", url=invite_link.invite_link)],
                    [InlineKeyboardButton("🔄 Try Again", url=f"https://t.me/{client.me.username}?start={message.command[1] if len(message.command)>1 else ''}")]
                ])
                return await message.reply("⚠️ **You must join our channel to view this video!**", reply_markup=buttons)
            except Exception as e:
                logger.error(f"Invite Link Error: {e}")

    # Video Delivery
    if len(message.command) > 1:
        return await process_user_delivery(client, message)
    
    # Admin Panel
    if message.from_user.id == ADMIN_ID:
        admin_text = (
            "👑 **Admin Control Panel (V2.0)**\n\n"
            "📡 **Config:**\n"
            "`/setsource -100xxxx`, `/setpublic -100xxxx`\n"
            "`/setinterval 30`, `/autodelete 60`\n"
            "`/protect on`, `/fsub on`\n"
            "`/setshortener domain key`\n\n"
            "📢 **Action:**\n"
            "`/broadcast` - Send message to all users\n"
            "`/stats` - Check User Base"
        )
        await message.reply(admin_text)
    else:
        await message.reply("👋 **Hello!** I am an Auto Post & Delivery Bot.")

# --- নতুন অ্যাডমিন কমান্ড ---

@app.on_message(filters.command("fsub") & filters.user(ADMIN_ID))
async def set_fsub_command(client, message):
    try:
        state = message.command[1].lower() == "on"
        await update_database_setting("force_sub", state)
        await message.reply(f"🔒 **Force Subscribe:** `{'ENABLED' if state else 'DISABLED'}`")
    except: await message.reply("❌ Use: `/fsub on` or `/fsub off`")

@app.on_message(filters.command("stats") & filters.user(ADMIN_ID))
async def stats_command(client, message):
    users = await users_collection.count_documents({})
    queue = await queue_collection.count_documents({})
    await message.reply(f"📊 **Bot Statistics**\n\n👥 **Total Users:** `{users}`\n📥 **Queue Pending:** `{queue}`")

@app.on_message(filters.command("broadcast") & filters.user(ADMIN_ID) & filters.reply)
async def broadcast_command(client, message):
    await message.reply("📢 **Broadcast Started...**")
    users = users_collection.find({})
    success = 0
    blocked = 0
    deleted = 0
    
    async for user in users:
        try:
            await message.reply_to_message.copy(chat_id=user["_id"])
            success += 1
            await asyncio.sleep(0.1) # FloodWait প্রতিরোধে
        except FloodWait as e:
            await asyncio.sleep(e.value)
            await message.reply_to_message.copy(chat_id=user["_id"])
        except UserIsBlocked:
            blocked += 1
            await users_collection.delete_one({"_id": user["_id"]})
        except InputUserDeactivated:
            deleted += 1
            await users_collection.delete_one({"_id": user["_id"]})
        except: pass
        
    await message.reply(f"✅ **Broadcast Completed**\nSuccess: `{success}`\nBlocked: `{blocked}`\nDeleted: `{deleted}`")

# বাকী অ্যাডমিন কমান্ডস (setsource, setpublic etc.) আগের মতই থাকবে...
# (স্থান বাঁচানোর জন্য এখানে পুনরাবৃত্তি করলাম না, আপনার আগের কোডের কমান্ডগুলো এখানে বসবে)
@app.on_message(filters.command("setsource") & filters.user(ADMIN_ID))
async def set_source_command(client, message):
    try:
        channel_id = int(message.command[1])
        await update_database_setting("source_channel", channel_id)
        await message.reply(f"✅ **Source Channel Updated:** `{channel_id}`")
    except:
        await message.reply("❌ **Error:** Usage: `/setsource -100123456789`")

@app.on_message(filters.command("setpublic") & filters.user(ADMIN_ID))
async def set_public_command(client, message):
    try:
        channel_id = int(message.command[1])
        await update_database_setting("public_channel", channel_id)
        await message.reply(f"✅ **Public Channel Updated:** `{channel_id}`")
    except:
        await message.reply("❌ **Error:** Usage: `/setpublic -100123456789`")
        
@app.on_message(filters.command("setshortener") & filters.user(ADMIN_ID))
async def set_shortener_command(client, message):
    try:
        if len(message.command) < 3:
            return await message.reply("❌ Usage: `/setshortener domain.com api_key`")
        domain = message.command[1]
        api_key = message.command[2]
        await update_database_setting("shortener_domain", domain)
        await update_database_setting("shortener_key", api_key)
        await message.reply(f"🔗 **Shortener Configured:**\nDomain: `{domain}`\nKey: `{api_key}`")
    except Exception as e:
        await message.reply(f"❌ Error: {e}")

# ====================================================================
#                       ৫. ইউজার ডেলিভারি লজিক
# ====================================================================

async def process_user_delivery(client, message):
    try:
        msg_id = int(message.command[1])
        if not SYSTEM_CONFIG["source_channel"]:
            return await message.reply("❌ Maintenance Mode.")
        
        status_msg = await message.reply("🔄 **Fetching...**")
        source_msg = await client.get_messages(int(SYSTEM_CONFIG["source_channel"]), msg_id)
        
        if not source_msg or (not source_msg.video and not source_msg.document):
            return await status_msg.edit("❌ **Video not found.**")
        
        sent_msg = await source_msg.copy(
            chat_id=message.chat.id,
            caption="✅ **Requested Video**\n❌ **Do not forward**",
            protect_content=SYSTEM_CONFIG["protect_content"]
        )
        await status_msg.delete()
        
        if SYSTEM_CONFIG["auto_delete_time"] > 0:
            warning = await message.reply(f"⚠️ Auto-delete in {SYSTEM_CONFIG['auto_delete_time']}s!")
            await asyncio.sleep(SYSTEM_CONFIG["auto_delete_time"])
            await sent_msg.delete()
            await warning.delete()
            
    except Exception as e:
        logger.error(f"Delivery Error: {e}")
        await message.reply("❌ Error occurred.")

# ====================================================================
#                       ৬. ভিডিও মনিটরিং
# ====================================================================

@app.on_message(filters.channel & (filters.video | filters.document))
async def source_channel_listener(client, message):
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
                logger.info(f"📥 Queued ID: {message.id}")

# ====================================================================
#                       ৭. অপ্টিমাইজড প্রসেসিং ইঞ্জিন
# ====================================================================

async def processing_engine():
    if not os.path.exists("downloads"): os.makedirs("downloads")
    logger.info("🚀 V2 Engine Started...")
    
    while True:
        try:
            if not SYSTEM_CONFIG["source_channel"] or not SYSTEM_CONFIG["public_channel"]:
                await asyncio.sleep(20)
                continue
            
            task = await queue_collection.find_one(sort=[("date", 1)])
            if task:
                msg_id = task["msg_id"]
                try:
                    source_msg = await app.get_messages(int(SYSTEM_CONFIG["source_channel"]), msg_id)
                    if not source_msg:
                        await queue_collection.delete_one({"_id": task["_id"]})
                        continue
                    
                    video_path = f"downloads/video_{msg_id}.mp4"
                    # ডাউনলোড (বড় ফাইলের জন্য টাইমআউট বাড়ানো যেতে পারে)
                    await app.download_media(source_msg, file_name=video_path)
                    
                    # 🔥 থ্রেডে থাম্বনেইল জেনারেট (Non-blocking)
                    thumb_path = await generate_thumbnail_opencv(video_path, msg_id)
                    
                    bot_username = (await app.get_me()).username
                    deep_link = f"https://t.me/{bot_username}?start={msg_id}"
                    final_link = await shorten_url(deep_link)
                    
                    caption = SYSTEM_CONFIG["caption_template"].format(caption=task.get("caption", "")[:100])
                    buttons = InlineKeyboardMarkup([[InlineKeyboardButton("📥 DOWNLOAD VIDEO 📥", url=final_link)]])
                    dest_chat = int(SYSTEM_CONFIG["public_channel"])
                    
                    if thumb_path and os.path.exists(thumb_path):
                        await app.send_photo(dest_chat, thumb_path, caption=caption, reply_markup=buttons)
                    else:
                        await app.send_message(dest_chat, caption + "\n\n⚠️ No Preview", reply_markup=buttons)
                    
                    logger.info(f"✅ Processed: {msg_id}")
                    
                except Exception as e:
                    logger.error(f"Engine Error: {e}")
                
                await queue_collection.delete_one({"_id": task["_id"]})
                # ক্লিনআপ
                if os.path.exists(video_path): os.remove(video_path)
                if thumb_path and os.path.exists(thumb_path): os.remove(thumb_path)
            
            await asyncio.sleep(SYSTEM_CONFIG.get("post_interval", 30))
            
        except Exception as e:
            logger.critical(f"Loop Error: {e}")
            await asyncio.sleep(10)

# ====================================================================
#                       ৮. অ্যাপ রানার
# ====================================================================

async def main():
    asyncio.create_task(start_web_server())
    await app.start()
    await load_database_settings()
    asyncio.create_task(processing_engine())
    logger.info("🤖 Enterprise Bot V2 is Running...")
    await idle()
    await app.stop()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
