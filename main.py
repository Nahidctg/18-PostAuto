import asyncio
import os
import shutil
import time
import logging
import aiohttp
import cv2  # OpenCV for Thumbnails
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

# আপনার ক্রেডেনশিয়ালস
API_ID = 22697010
API_HASH = "fd88d7339b0371eb2a9501d523f3e2a7"
BOT_TOKEN = "8303315439:AAGKPEugn60XGMC7_u4pOaZPnUWkWHvXSNM"
MONGO_URL = "mongodb+srv://mewayo8672:mewayo8672@cluster0.ozhvczp.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
ADMIN_ID = 8172129114  # আপনার টেলিগ্রাম আইডি

# লগিং সেটআপ
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("AutoBot_Enterprise")

# ডাটাবেস সেটআপ
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client["Enterprise_Bot_DB"]
queue_collection = db["video_queue"]
config_collection = db["bot_settings"]
users_collection = db["users_list"]  # ইউজারের লিস্ট রাখার জন্য নতুন কালেকশন

# গ্লোবাল মেমোরি কনফিগারেশন (ডিফল্ট ভ্যালু)
SYSTEM_CONFIG = {
    "source_channel": None,
    "public_channel": None,
    "post_interval": 30,
    "shortener_domain": None,
    "shortener_key": None,
    "auto_delete_time": 0,
    "protect_content": False,
    "tutorial_link": None,        # নতুন: টিউটোরিয়াল লিংক
    "force_sub": True,            # নতুন: ফোর্স সাবস্ক্রাইব
    "caption_template": "🎬 **{caption}**\n\n✨ **Quality:** HD 720p\n🔥 **Exclusive Content**"
}

# পাইরোগ্রাম ক্লায়েন্ট
app = Client(
    "Enterprise_Session",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# ====================================================================
#                       ২. ওয়েব সার্ভার (Keep Alive)
# ====================================================================

async def web_server_handler(request):
    return web.Response(text="✅ Bot is Running in Enterprise Mode (Updated)!")

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
#                       ৩. হেল্পার ফাংশনস (টুলস)
# ====================================================================

async def load_database_settings():
    """বট স্টার্ট হওয়ার সময় ডাটাবেস থেকে সেটিংস লোড করবে"""
    settings = await config_collection.find_one({"_id": "global_settings"})
    
    if not settings:
        await config_collection.insert_one({"_id": "global_settings"})
        logger.info("⚙️ New Settings Created in Database.")
    else:
        SYSTEM_CONFIG["source_channel"] = settings.get("source_channel")
        SYSTEM_CONFIG["public_channel"] = settings.get("public_channel")
        SYSTEM_CONFIG["post_interval"] = settings.get("post_interval", 30)
        SYSTEM_CONFIG["shortener_domain"] = settings.get("shortener_domain")
        SYSTEM_CONFIG["shortener_key"] = settings.get("shortener_key")
        SYSTEM_CONFIG["auto_delete_time"] = settings.get("auto_delete_time", 0)
        SYSTEM_CONFIG["protect_content"] = settings.get("protect_content", False)
        SYSTEM_CONFIG["tutorial_link"] = settings.get("tutorial_link", None) # টিউটোরিয়াল লোড
        SYSTEM_CONFIG["force_sub"] = settings.get("force_sub", True)
        logger.info("⚙️ Settings Loaded Successfully.")

async def update_database_setting(key, value):
    """যেকোনো সেটিং পরিবর্তন হলে ডাটাবেসে আপডেট করবে"""
    await config_collection.update_one(
        {"_id": "global_settings"},
        {"$set": {key: value}},
        upsert=True
    )
    SYSTEM_CONFIG[key] = value

async def add_user(user_id):
    """ব্রডকাস্টের জন্য ইউজার সেভ করা"""
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
    except Exception:
        return True  # এরর হলে বাইপাস

async def shorten_url(long_url):
    """লিংক শর্টনার API হ্যান্ডলিং"""
    if not SYSTEM_CONFIG["shortener_domain"] or not SYSTEM_CONFIG["shortener_key"]:
        return long_url

    try:
        api_url = f"https://{SYSTEM_CONFIG['shortener_domain']}/api?api={SYSTEM_CONFIG['shortener_key']}&url={long_url}"
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    if "shortenedUrl" in data:
                        return data["shortenedUrl"]
    except Exception as e:
        logger.error(f"Shortener Failed: {e}")
    
    return long_url

def generate_thumbnail_opencv(video_path, message_id):
    """OpenCV ব্যবহার করে ভিডিও থেকে থাম্বনেইল জেনারেট"""
    thumbnail_path = f"downloads/thumb_{message_id}.jpg"
    
    try:
        video_cap = cv2.VideoCapture(video_path)
        if not video_cap.isOpened():
            return None
        
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
#                       ৪. অ্যাডমিন কমান্ডস (আপডেটেড)
# ====================================================================

@app.on_message(filters.command("start"))
async def start_handler(client, message):
    # ইউজার ডাটাবেসে সেভ করা
    await add_user(message.from_user.id)
    
    # পার্ট ১: ফোর্স সাবস্ক্রাইব চেক
    if SYSTEM_CONFIG["force_sub"] and SYSTEM_CONFIG["public_channel"]:
        is_joined = await check_force_sub(client, message.from_user.id)
        if not is_joined:
            try:
                invite_link = await client.create_chat_invite_link(int(SYSTEM_CONFIG["public_channel"]))
                # স্টার্ট কমান্ডে প্যারামিটার থাকলে সেটা রাখার ব্যবস্থা
                start_param = message.command[1] if len(message.command) > 1 else ""
                
                buttons = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📢 Join Our Channel", url=invite_link.invite_link)],
                    [InlineKeyboardButton("🔄 Try Again", url=f"https://t.me/{client.me.username}?start={start_param}")]
                ])
                return await message.reply("⚠️ **You must join our channel to view this content!**", reply_markup=buttons)
            except Exception as e:
                logger.error(f"FSub Error: {e}")

    # পার্ট ২: ইউজার ভিডিও ডেলিভারি (যদি প্যারামিটার থাকে)
    if len(message.command) > 1:
        return await process_user_delivery(client, message)
    
    # পার্ট ৩: অ্যাডমিন প্যানেল ও ওয়েলকাম
    if message.from_user.id == ADMIN_ID:
        admin_text = (
            "👑 **Admin Control Panel (Full Version)**\n\n"
            "📡 **Channels:**\n"
            "`/setsource -100xxxx` - Source Channel\n"
            "`/setpublic -100xxxx` - Public Channel\n\n"
            "⚙️ **Settings:**\n"
            "`/settutorial https://t.me/xx` - Set Tutorial Link\n"
            "`/setinterval 30` - Post Delay\n"
            "`/autodelete 60` - Auto Delete Timer\n"
            "`/protect on` - Content Protection\n"
            "`/setshortener domain key` - Link Shortener\n\n"
            "📢 **Broadcast:**\n"
            "`/broadcast` (Reply to message)\n"
            "`/stats` - Check Users"
        )
        await message.reply(admin_text)
    else:
        await message.reply(
            "👋 **Hello!**\n"
            "I am an Auto Post & Delivery Bot.\n"
            "Please join our main channel to get content."
        )

# --- নতুন অ্যাডমিন কমান্ড: টিউটোরিয়াল সেট করা ---
@app.on_message(filters.command("settutorial") & filters.user(ADMIN_ID))
async def set_tutorial_command(client, message):
    try:
        if len(message.command) < 2:
            return await message.reply("❌ Usage: `/settutorial https://youtube.com/yourlink`")
        
        link = message.command[1]
        await update_database_setting("tutorial_link", link)
        await message.reply(f"✅ **Tutorial Button Link Set:**\n`{link}`")
    except Exception as e:
        await message.reply(f"❌ Error: {e}")

# --- নতুন অ্যাডমিন কমান্ড: ব্রডকাস্ট ---
@app.on_message(filters.command("broadcast") & filters.user(ADMIN_ID) & filters.reply)
async def broadcast_command(client, message):
    await message.reply("📢 **Broadcast Started...**")
    all_users = users_collection.find({})
    success = 0
    blocked = 0
    deleted = 0
    
    async for user in all_users:
        try:
            await message.reply_to_message.copy(chat_id=user["_id"])
            success += 1
            await asyncio.sleep(0.1) # FloodWait এড়ানোর জন্য
        except FloodWait as e:
            await asyncio.sleep(e.value)
            await message.reply_to_message.copy(chat_id=user["_id"])
        except UserIsBlocked:
            blocked += 1
            await users_collection.delete_one({"_id": user["_id"]})
        except InputUserDeactivated:
            deleted += 1
            await users_collection.delete_one({"_id": user["_id"]})
        except Exception:
            pass
            
    await message.reply(f"✅ **Broadcast Done!**\nSuccess: {success}\nBlocked: {blocked}\nDeleted: {deleted}")

@app.on_message(filters.command("stats") & filters.user(ADMIN_ID))
async def stats_command(client, message):
    users = await users_collection.count_documents({})
    queue = await queue_collection.count_documents({})
    await message.reply(f"📊 **Statistics:**\n👥 Total Users: `{users}`\n📥 Queue Pending: `{queue}`")

# --- আগের কমান্ডগুলো (অপরিবর্তিত) ---

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

@app.on_message(filters.command("setinterval") & filters.user(ADMIN_ID))
async def set_interval_command(client, message):
    try:
        seconds = int(message.command[1])
        await update_database_setting("post_interval", seconds)
        await message.reply(f"⏱ **Post Interval Set:** `{seconds} seconds`")
    except:
        await message.reply("❌ **Error:** Usage: `/setinterval 30`")

@app.on_message(filters.command("autodelete") & filters.user(ADMIN_ID))
async def set_autodelete_command(client, message):
    try:
        seconds = int(message.command[1])
        await update_database_setting("auto_delete_time", seconds)
        await message.reply(f"⏳ **Auto Delete Timer:** `{seconds} seconds`")
    except:
        await message.reply("❌ **Error:** Usage: `/autodelete 60` (Use 0 to disable)")

@app.on_message(filters.command("protect") & filters.user(ADMIN_ID))
async def set_protection_command(client, message):
    try:
        state = message.command[1].lower()
        if state == "on":
            await update_database_setting("protect_content", True)
            await message.reply("🛡 **Content Protection:** `ENABLED`")
        elif state == "off":
            await update_database_setting("protect_content", False)
            await message.reply("🛡 **Content Protection:** `DISABLED`")
        else:
            await message.reply("❌ Use: `/protect on` or `/protect off`")
    except:
        await message.reply("❌ Usage: `/protect on` or `/protect off`")

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
#                       ৫. ইউজার ডেলিভারি লজিক (অরিজিনাল)
# ====================================================================

async def process_user_delivery(client, message):
    try:
        msg_id = int(message.command[1])
        
        # কনফিগারেশন চেক
        if not SYSTEM_CONFIG["source_channel"]:
            return await message.reply("❌ **Bot is under maintenance.** (Source not set)")
        
        status_msg = await message.reply("🔄 **Fetching your video... Please wait.**")
        
        # সোর্স থেকে ভিডিও কপি করা
        source_msg = await client.get_messages(int(SYSTEM_CONFIG["source_channel"]), msg_id)
        
        if not source_msg or (not source_msg.video and not source_msg.document):
            return await status_msg.edit("❌ **Error:** Video not found or deleted.")
        
        # ভিডিও পাঠানো
        sent_msg = await source_msg.copy(
            chat_id=message.chat.id,
            caption="✅ **Here is your requested video!**\n❌ **Do not forward this message.**",
            protect_content=SYSTEM_CONFIG["protect_content"]
        )
        
        await status_msg.delete()
        
        # অটো ডিলিট লজিক
        if SYSTEM_CONFIG["auto_delete_time"] > 0:
            warning = await message.reply(f"⚠️ **Note:** This video will be auto-deleted in {SYSTEM_CONFIG['auto_delete_time']} seconds!")
            await asyncio.sleep(SYSTEM_CONFIG["auto_delete_time"])
            await sent_msg.delete()
            await warning.delete()
            
    except Exception as e:
        logger.error(f"User Delivery Error: {e}")
        await message.reply("❌ An error occurred. Please try again.")

# ====================================================================
#                       ৬. ভিডিও মনিটরিং (Source Listener)
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
                logger.info(f"📥 New Video Queued: ID {message.id}")

# ====================================================================
#                       ৭. মেইন প্রসেসিং ইঞ্জিন (With Tutorial Button)
# ====================================================================

async def processing_engine():
    # ডাউনলোড ফোল্ডার তৈরি
    if not os.path.exists("downloads"):
        os.makedirs("downloads")
        
    logger.info("🚀 Processing Engine Started Successfully...")
    
    while True:
        try:
            if not SYSTEM_CONFIG["source_channel"] or not SYSTEM_CONFIG["public_channel"]:
                logger.warning("⚠️ Source or Public Channel not set. Waiting 20s...")
                await asyncio.sleep(20)
                continue
            
            task = await queue_collection.find_one(sort=[("date", 1)])
            
            if task:
                msg_id = task["msg_id"]
                logger.info(f"🔨 Processing Message ID: {msg_id}")
                
                try:
                    # ভিডিও ফেচ করা
                    source_msg = await app.get_messages(int(SYSTEM_CONFIG["source_channel"]), msg_id)
                    
                    if not source_msg:
                        logger.error("❌ Message deleted from source.")
                        await queue_collection.delete_one({"_id": task["_id"]})
                        continue
                    
                    # ভিডিও ডাউনলোড
                    video_path = f"downloads/video_{msg_id}.mp4"
                    logger.info("⬇️ Downloading Video for Thumbnail Generation...")
                    await app.download_media(source_msg, file_name=video_path)
                    
                    # থাম্বনেইল জেনারেট (OpenCV)
                    logger.info("🎨 Generating Thumbnail with OpenCV...")
                    thumb_path = generate_thumbnail_opencv(video_path, msg_id)
                    
                    # ডিপ লিংক তৈরি ও শর্ট করা
                    bot_username = (await app.get_me()).username
                    deep_link = f"https://t.me/{bot_username}?start={msg_id}"
                    final_link = await shorten_url(deep_link)
                    
                    # ক্যাপশন তৈরি
                    raw_caption = task.get("caption", "New Video")[:100]
                    final_caption = SYSTEM_CONFIG["caption_template"].format(caption=raw_caption)
                    
                    # ====================================================
                    # 🔥 বাটন কনফিগারেশন (এখানে টিউটোরিয়াল বাটন যোগ হবে)
                    # ====================================================
                    button_list = [
                        [InlineKeyboardButton("📥 DOWNLOAD / WATCH VIDEO 📥", url=final_link)]
                    ]
                    
                    # যদি টিউটোরিয়াল লিংক সেট করা থাকে, তবেই বাটন শো করবে
                    if SYSTEM_CONFIG["tutorial_link"]:
                        button_list.append([
                            InlineKeyboardButton("ℹ️ How to Download", url=SYSTEM_CONFIG["tutorial_link"])
                        ])
                    
                    buttons = InlineKeyboardMarkup(button_list)
                    
                    # পাবলিক চ্যানেলে পোস্ট
                    dest_chat = int(SYSTEM_CONFIG["public_channel"])
                    
                    if thumb_path and os.path.exists(thumb_path):
                        await app.send_photo(
                            chat_id=dest_chat,
                            photo=thumb_path,
                            caption=final_caption,
                            reply_markup=buttons
                        )
                    else:
                        await app.send_message(
                            chat_id=dest_chat,
                            text=final_caption + "\n\n⚠️ *No Preview Available*",
                            reply_markup=buttons
                        )
                    
                    logger.info(f"✅ Post Successful: ID {msg_id}")
                    
                except Exception as e:
                    logger.error(f"❌ Processing Error: {e}")
                
                # ক্লিনআপ
                await queue_collection.delete_one({"_id": task["_id"]})
                
                try:
                    if os.path.exists(video_path): os.remove(video_path)
                    if thumb_path and os.path.exists(thumb_path): os.remove(thumb_path)
                except: pass
            
            wait_time = SYSTEM_CONFIG.get("post_interval", 30)
            await asyncio.sleep(wait_time)
            
        except Exception as e:
            logger.critical(f"🛑 Critical Engine Loop Error: {e}")
            await asyncio.sleep(10)

# ====================================================================
#                       ৮. অ্যাপ রানার
# ====================================================================

async def main():
    asyncio.create_task(start_web_server())
    await app.start()
    await load_database_settings()
    asyncio.create_task(processing_engine())
    
    logger.info("🤖 Bot is now Idle and Waiting for Tasks...")
    await idle()
    await app.stop()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
