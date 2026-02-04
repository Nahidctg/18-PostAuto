import asyncio
import os
import shutil
import subprocess
import aiohttp
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait, ChatWriteForbidden
from motor.motor_asyncio import AsyncIOMotorClient

# ------------------- CONFIGURATION -------------------
API_ID = 22697010
API_HASH = "fd88d7339b0371eb2a9501d523f3e2a7"
BOT_TOKEN = "8303315439:AAGKPEugn60XGMC7_u4pOaZPnUWkWHvXSNM"
MONGO_URL = "mongodb+srv://mewayo8672:mewayo8672@cluster0.ozhvczp.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
ADMIN_ID = 8172129114

# ------------------- DATABASE -------------------
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client["AutoPostBot"]
queue_col = db["video_queue"]
config_col = db["config"]

CACHE = {
    "source_channel": None,
    "public_channel": None,
    "shortener_api": None,
    "shortener_key": None,
    "auto_delete": 0,
    "post_interval": 30,
    "tutorial_url": "https://t.me/YourChannel"
}

app = Client("fix_bot_final", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ------------------- HELPER FUNCTIONS -------------------

async def notify_admin(text):
    try: await app.send_message(ADMIN_ID, text)
    except: pass

async def load_config():
    conf = await config_col.find_one({"_id": "settings"})
    if not conf:
        default_conf = {
            "_id": "settings",
            "source_channel": None,
            "public_channel": None,
            "auto_delete": 0,
            "post_interval": 30,
            "tutorial_url": "https://t.me/"
        }
        await config_col.insert_one(default_conf)
        conf = default_conf
    CACHE.update(conf)
    print("✅ Config Loaded")

async def update_config(key, value):
    await config_col.update_one({"_id": "settings"}, {"$set": {key: value}}, upsert=True)
    CACHE[key] = value

async def shorten_link(link):
    if not CACHE.get("shortener_api") or not CACHE.get("shortener_key"): return link
    try:
        url = f"{CACHE['shortener_api']}?api={CACHE['shortener_key']}&url={link}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
                return data.get("shortenedUrl") or data.get("url") or link
    except: return link

# ------------------- THUMBNAIL LOGIC (IMP) -------------------

async def get_thumbnail(message, download_video=False):
    """
    ১. প্রথমে চেষ্টা করবে FFmpeg দিয়ে ভিডিও থেকে থাম্বনেইল বানাতে।
    ২. যদি FFmpeg না থাকে বা ফেইল করে, তাহলে টেলিগ্রামের অরিজিনাল থাম্বনেইল নামাবে।
    """
    thumb_path = None
    video_path = None
    
    # Check if FFmpeg exists in system
    ffmpeg_exists = shutil.which("ffmpeg") is not None

    try:
        # পদ্ধতি ১: FFmpeg দিয়ে কাস্টম থাম্বনেইল (যদি FFmpeg থাকে)
        if ffmpeg_exists and download_video:
            print("⏳ Downloading video for custom thumbnail...")
            video_path = await app.download_media(message, file_name=f"temp_{message.id}.mp4")
            
            if video_path:
                gen_thumb = f"{video_path}.jpg"
                # ৫ সেকেন্ডের মাথা থেকে স্ক্রিনশট নিবে
                subprocess.call([
                    "ffmpeg", "-i", video_path, "-ss", "00:00:05", "-vframes", "1", "-q:v", "2", gen_thumb, "-y"
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                
                if os.path.exists(gen_thumb):
                    print("✅ Custom Thumbnail Generated")
                    return gen_thumb, video_path  # থাম্ব এবং ভিডিও পাথ রিটার্ন করবে
                
        # পদ্ধতি ২: যদি উপরেরটা ফেইল করে, টেলিগ্রাম থাম্বনেইল ব্যবহার করবে
        print("⚠️ Using Original Telegram Thumbnail")
        if message.video and message.video.thumbs:
            thumb_path = await app.download_media(message.video.thumbs[0].file_id)
        elif message.document and message.document.thumbs:
            thumb_path = await app.download_media(message.document.thumbs[0].file_id)
            
    except Exception as e:
        print(f"Thumbnail Error: {e}")

    return thumb_path, video_path

# ------------------- COMMANDS (FIXED) -------------------

@app.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    # ফিক্স: আগে এখানে return ছিল, তাই ভিডিও দিত না। এখন ঠিক করা হয়েছে।
    if len(message.command) > 1:
        return await send_stored_file(client, message)
    
    await message.reply_text("👋 Bot is Ready!\n\nUse admin commands to manage.")

async def send_stored_file(client, message):
    try:
        msg_id = int(message.command[1])
        if not CACHE["source_channel"]:
            return await message.reply_text("❌ Source Channel Not Set")

        file_msg = await client.get_messages(int(CACHE["source_channel"]), msg_id)
        
        if not file_msg or (not file_msg.video and not file_msg.document):
            return await message.reply_text("❌ File Deleted or Not Found")

        caption = f"🎥 **{file_msg.caption[:50] if file_msg.caption else 'Video'}...**"
        
        # অটো ডিলিট মেসেজ
        sent_msg = await file_msg.copy(
            chat_id=message.chat.id,
            caption=caption,
            protect_content=CACHE["protect_content"]
        )

        if CACHE["auto_delete"] > 0:
            await message.reply_text(f"⚠️ This video will be deleted in {CACHE['auto_delete']} seconds!")
            await asyncio.sleep(CACHE["auto_delete"])
            await sent_msg.delete()
            
    except Exception as e:
        await message.reply_text(f"❌ Error: {e}")

# Admin Commands
@app.on_message(filters.command("setsource") & filters.user(ADMIN_ID))
async def set_s(c, m): 
    try:
        await update_config("source_channel", int(m.command[1]))
        await m.reply("✅ Source Set")
    except: await m.reply("Error")

@app.on_message(filters.command("setpublic") & filters.user(ADMIN_ID))
async def set_p(c, m):
    try:
        await update_config("public_channel", int(m.command[1]))
        await m.reply("✅ Public Set")
    except: await m.reply("Error")

@app.on_message(filters.command("setinterval") & filters.user(ADMIN_ID))
async def set_i(c, m):
    try:
        await update_config("post_interval", int(m.command[1]))
        await m.reply("✅ Interval Set")
    except: await m.reply("Error")

@app.on_message(filters.command("autodelete") & filters.user(ADMIN_ID))
async def set_d(c, m):
    try:
        await update_config("auto_delete", int(m.command[1]))
        await m.reply("✅ Auto Delete Set")
    except: await m.reply("Error")

@app.on_message(filters.command("status") & filters.user(ADMIN_ID))
async def stat(c, m):
    q = await queue_col.count_documents({})
    ff = "Installed" if shutil.which("ffmpeg") else "Not Installed (Using Default Thumbs)"
    await m.reply(f"📊 **Status**\nQueue: {q}\nFFmpeg: `{ff}`\nSource: `{CACHE['source_channel']}`")

# ------------------- INPUT -------------------

@app.on_message(filters.channel & (filters.video | filters.document))
async def incoming(c, m):
    if CACHE["source_channel"] and m.chat.id == int(CACHE["source_channel"]):
        f_id = m.video.file_id if m.video else (m.document.file_id if m.document else None)
        if f_id:
            await queue_col.insert_one({
                "msg_id": m.id,
                "caption": m.caption or "Video",
                "file_id": f_id,
                "date": m.date
            })
            print(f"Added: {m.id}")

# ------------------- SCHEDULER -------------------

async def post_scheduler():
    print("🔄 Scheduler Running...")
    while True:
        try:
            if not CACHE["source_channel"] or not CACHE["public_channel"]:
                await asyncio.sleep(10); continue

            video_data = await queue_col.find_one(sort=[("date", 1)])
            
            if video_data:
                msg_id = video_data["msg_id"]
                print(f"🚀 Processing: {msg_id}")

                real_msg = None
                try:
                    real_msg = await app.get_messages(int(CACHE["source_channel"]), msg_id)
                except: pass

                if not real_msg:
                    await queue_col.delete_one({"_id": video_data["_id"]}); continue

                # থাম্বনেইল লজিক
                thumb_path, video_path = await get_thumbnail(real_msg, download_video=True)

                # লিংক মেকিং
                bot_usr = (await app.get_me()).username
                link = await shorten_link(f"https://t.me/{bot_usr}?start={msg_id}")
                caption = f"🎬 **{video_data.get('caption', 'Video')[:150]}**\n\n🔗 **Download:** {link}"
                btn = InlineKeyboardMarkup([[InlineKeyboardButton("📥 Download Video", url=link)]])

                # পোস্টিং
                dest = int(CACHE["public_channel"])
                try:
                    if thumb_path:
                        await app.send_photo(dest, thumb_path, caption=caption, reply_markup=btn)
                    else:
                        await app.send_message(dest, caption, reply_markup=btn)
                    
                    print(f"✅ Posted: {msg_id}")
                    await queue_col.delete_one({"_id": video_data["_id"]})
                
                except FloodWait as e:
                    await asyncio.sleep(e.value)
                except Exception as e:
                    print(f"Post Error: {e}")
                    await queue_col.delete_one({"_id": video_data["_id"]})

                # ক্লিনআপ
                try:
                    if thumb_path: os.remove(thumb_path)
                    if video_path: os.remove(video_path)
                except: pass
            
            else: pass

        except Exception as e:
            print(f"Loop Error: {e}")
            await asyncio.sleep(5)
        
        await asyncio.sleep(CACHE.get("post_interval", 30))

if __name__ == "__main__":
    app.run()
