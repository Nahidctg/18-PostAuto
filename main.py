import asyncio
import os
import shutil
import time
import sys
from pyrogram import Client, filters, idle
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, 
    InputMediaPhoto
)
from pyrogram.errors import FloodWait
from motor.motor_asyncio import AsyncIOMotorClient
from aiohttp import web  # ওয়েব সার্ভারের জন্য

# ------------------- ১. সিস্টেম কনফিগারেশন -------------------
API_ID = 22697010
API_HASH = "fd88d7339b0371eb2a9501d523f3e2a7"
BOT_TOKEN = "8303315439:AAGKPEugn60XGMC7_u4pOaZPnUWkWHvXSNM"
MONGO_URL = "mongodb+srv://mewayo8672:mewayo8672@cluster0.ozhvczp.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
ADMIN_ID = 8172129114  # আপনার টেলিগ্রাম আইডি

# ডাটাবেস সেটআপ
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client["AutoVideoBot_Pro"]
queue_col = db["queue"]
config_col = db["config"]

# ক্যাশ মেমোরি
CACHE = {
    "source_channel": None,
    "public_channel": None,
    "post_interval": 30,
    "caption_template": "🎬 **{title}**\n\n✨ **Quality:** HD Streaming",
    "tutorial_url": "https://t.me/YourChannel"
}

app = Client("project_video_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ------------------- ২. ওয়েব সার্ভার (Deployment Fix) -------------------
async def web_server():
    async def handle(request):
        return web.Response(text="Bot is Running Successfully!")

    web_app = web.Application()
    web_app.add_routes([web.get('/', handle)])
    runner = web.AppRunner(web_app)
    await runner.setup()
    # Koyeb/Render পোর্টের জন্য ENV চেক করবে, ডিফল্ট 8080
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"🌍 Web Server Started on Port {port}")

# ------------------- ৩. হেল্পার ফাংশন -------------------

async def load_config():
    try:
        conf = await config_col.find_one({"_id": "settings"})
        if not conf:
            default = {
                "_id": "settings",
                "source_channel": None,
                "public_channel": None,
                "post_interval": 30
            }
            await config_col.insert_one(default)
            conf = default
        
        CACHE["source_channel"] = conf.get("source_channel")
        CACHE["public_channel"] = conf.get("public_channel")
        print(f"✅ Config Loaded: Source={CACHE['source_channel']}, Public={CACHE['public_channel']}")
    except Exception as e:
        print(f"❌ Config Error: {e}")

async def update_config(key, value):
    await config_col.update_one({"_id": "settings"}, {"$set": {key: value}}, upsert=True)
    CACHE[key] = value

async def get_video_duration(video_path):
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", video_path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        return float(stdout.decode().strip())
    except:
        return 0

async def generate_thumbnails(video_path, msg_id):
    if not shutil.which("ffmpeg"):
        print("❌ FFmpeg Not Found!")
        return []

    thumbs = []
    duration = await get_video_duration(video_path)
    if duration == 0: duration = 30 

    timestamps = [duration*0.2, duration*0.5, duration*0.8] # ২০%, ৫০%, ৮০%
    
    for i, t in enumerate(timestamps):
        out_file = f"downloads/thumb_{msg_id}_{i}.jpg"
        time_str = time.strftime('%H:%M:%S', time.gmtime(t))
        
        cmd = [
            "ffmpeg", "-ss", time_str, "-i", video_path,
            "-vframes", "1", "-q:v", "2", out_file, "-y"
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        await process.wait()

        if os.path.exists(out_file):
            thumbs.append(out_file)
    return thumbs

# ------------------- ৪. বট কমান্ডস -------------------

@app.on_message(filters.command("start") & filters.private)
async def start_handler(c, m):
    if len(m.command) > 1:
        return await send_video_to_user(c, m)
    await m.reply_text("👋 **Bot is Online!**")

async def send_video_to_user(client, message):
    try:
        msg_id = int(message.command[1])
        if not CACHE["source_channel"]:
            return await message.reply("❌ Source Channel Not Set.")
        
        sts = await message.reply("🔄 Processing...")
        file_msg = await client.get_messages(int(CACHE["source_channel"]), msg_id)
        
        if not file_msg or (not file_msg.video and not file_msg.document):
            return await sts.edit("❌ Content Deleted.")

        caption = f"🎬 **Your Video**\n🆔 ID: `{msg_id}`"
        await file_msg.copy(chat_id=message.chat.id, caption=caption)
        await sts.delete()
    except Exception as e:
        print(f"Send Error: {e}")

@app.on_message(filters.command("setsource") & filters.user(ADMIN_ID))
async def set_src(c, m):
    try:
        cid = int(m.command[1])
        await update_config("source_channel", cid)
        await m.reply(f"✅ Source Set: `{cid}`")
    except: await m.reply("Error! Usage: /setsource -100xxx")

@app.on_message(filters.command("setpublic") & filters.user(ADMIN_ID))
async def set_pub(c, m):
    try:
        cid = int(m.command[1])
        await update_config("public_channel", cid)
        await m.reply(f"✅ Public Set: `{cid}`")
    except: await m.reply("Error! Usage: /setpublic -100xxx")

# ------------------- ৫. লিসেনার ও প্রসেসর -------------------

@app.on_message(filters.channel & (filters.video | filters.document))
async def queue_manager(c, m):
    if CACHE["source_channel"] and m.chat.id == int(CACHE["source_channel"]):
        is_vid = m.video or (m.document and "video" in m.document.mime_type)
        if is_vid:
            if not await queue_col.find_one({"msg_id": m.id}):
                await queue_col.insert_one({"msg_id": m.id, "caption": m.caption or "Video", "date": m.date})
                print(f"📥 Queued ID: {m.id}")

async def post_processor():
    print("🔄 Engine Started...")
    if not os.path.exists("downloads"): os.makedirs("downloads")

    while True:
        try:
            if not CACHE["source_channel"] or not CACHE["public_channel"]:
                await asyncio.sleep(10); continue

            task = await queue_col.find_one(sort=[("date", 1)])
            if task:
                msg_id = task["msg_id"]
                try:
                    real_msg = await app.get_messages(int(CACHE["source_channel"]), msg_id)
                    if not real_msg:
                        await queue_col.delete_one({"_id": task["_id"]}); continue
                    
                    # ডাউনলোড
                    f_path = f"downloads/vid_{msg_id}.mp4"
                    d_msg = await app.download_media(real_msg, file_name=f_path)
                    
                    # থাম্বনেইল
                    thumbs = await generate_thumbnails(f_path, msg_id)
                    
                    # পোস্ট
                    caption = CACHE["caption_template"].format(title=task.get("caption", "Video")[:50])
                    bot_uname = (await app.get_me()).username
                    link = f"https://t.me/{bot_uname}?start={msg_id}"
                    
                    btn = InlineKeyboardMarkup([[InlineKeyboardButton("📥 Download / Watch", url=link)]])
                    dest = int(CACHE["public_channel"])

                    if thumbs and len(thumbs) >= 2:
                        media = [InputMediaPhoto(t) for t in thumbs]
                        await app.send_media_group(dest, media=media)
                        await app.send_message(dest, text=caption, reply_markup=btn)
                    else:
                        # থাম্বনেইল না থাকলে ডিফল্ট
                        await app.send_video(dest, f_path, caption=caption, reply_markup=btn)

                    print(f"✅ Posted: {msg_id}")
                    await queue_col.delete_one({"_id": task["_id"]})
                    
                    # ক্লিনআপ
                    if os.path.exists(f_path): os.remove(f_path)
                    for t in thumbs: 
                        if os.path.exists(t): os.remove(t)

                except Exception as e:
                    print(f"Process Error: {e}")
                    # ফেইল হলেও কিউ থেকে ডিলিট করা হবে যাতে লুপ না হয়
                    await queue_col.delete_one({"_id": task["_id"]})

            await asyncio.sleep(CACHE["post_interval"])

        except Exception as e:
            print(f"Engine Error: {e}")
            await asyncio.sleep(5)

# ------------------- ৬. মেইন রানার -------------------

async def main():
    # ওয়েব সার্ভার ব্যাকগ্রাউন্ডে চালু হবে
    asyncio.create_task(web_server())
    
    await app.start()
    await load_config()
    print("🤖 Bot Started Successfully!")
    
    # প্রসেসিং টাস্ক চালু
    asyncio.create_task(post_processor())
    await idle()
    await app.stop()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
