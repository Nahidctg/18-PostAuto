import asyncio
import os
import shutil
import time
from pyrogram import Client, filters, idle
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, 
    InputMediaPhoto
)
from pyrogram.errors import FloodWait, RPCError
from motor.motor_asyncio import AsyncIOMotorClient

# ------------------- ১. সিস্টেম কনফিগারেশন -------------------
API_ID = 22697010
API_HASH = "fd88d7339b0371eb2a9501d523f3e2a7"
BOT_TOKEN = "8303315439:AAGKPEugn60XGMC7_u4pOaZPnUWkWHvXSNM"
MONGO_URL = "mongodb+srv://mewayo8672:mewayo8672@cluster0.ozhvczp.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
ADMIN_ID = 8172129114  # আপনার টেলিগ্রাম আইডি (Integer হতে হবে)

# ডাটাবেস সেটআপ
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client["AutoVideoBot_Pro"]
queue_col = db["queue"]
config_col = db["config"]

# ক্যাশ মেমোরি (ভেরিয়েবল স্টোরেজ)
CACHE = {
    "source_channel": None,
    "public_channel": None,
    "post_interval": 30,       # কত সেকেন্ড পর পর পোস্ট করবে
    "caption_template": "🎬 **{title}**\n\n✨ **Quality:** HD Streaming\n🔥 **Exclusive Content**",
    "tutorial_url": "https://t.me/YourChannel" # আপনার মেইন চ্যানেলের লিংক
}

# অ্যাপ ইনিশিলাইজেশন
app = Client("project_video_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ------------------- ২. হেল্পার ফাংশন -------------------

async def load_config():
    """ডাটাবেস থেকে সেটিংস লোড করা"""
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
        CACHE["post_interval"] = conf.get("post_interval", 30)
        print(f"✅ Config Loaded: Source={CACHE['source_channel']}, Public={CACHE['public_channel']}")
    except Exception as e:
        print(f"❌ Config Error: {e}")

async def update_config(key, value):
    await config_col.update_one({"_id": "settings"}, {"$set": {key: value}}, upsert=True)
    CACHE[key] = value

async def get_video_duration(video_path):
    """ভিডিওর ডিউরেশন বের করা"""
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
    """ভিডিও থেকে ৩টি স্ক্রিনশট নিবে (Async Way)"""
    if not shutil.which("ffmpeg"):
        print("❌ FFmpeg not found! Install FFmpeg on server.")
        return []

    thumbs = []
    duration = await get_video_duration(video_path)
    
    if duration == 0: duration = 30 # ডিফল্ট ডিউরেশন যদি রিড না করা যায়

    # ভিডিওর ১০%, ৫০% এবং ৮০% সময় থেকে ছবি নিবে
    timestamps = [duration*0.1, duration*0.5, duration*0.8]
    
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

# ------------------- ৩. ইউজার কমান্ড হ্যান্ডলার -------------------

@app.on_message(filters.command("start") & filters.private)
async def start_delivery(client, message):
    # ডিপ লিংক চেক (/start 123)
    if len(message.command) > 1:
        return await send_video_to_user(client, message)
    
    await message.reply_text(
        "👋 **Welcome!**\nI am an Auto Video Bot.\n\n"
        "Wait for new posts in our channel!"
    )

async def send_video_to_user(client, message):
    try:
        msg_id = int(message.command[1])
        if not CACHE["source_channel"]:
            return await message.reply("❌ Source Channel Not Set.")

        # "Processing" মেসেজ
        sts = await message.reply("🔄 Fetching Video...")

        file_msg = await client.get_messages(int(CACHE["source_channel"]), msg_id)
        
        if not file_msg or (not file_msg.video and not file_msg.document):
            return await sts.edit("❌ Video deleted or not found.")

        caption = f"🎬 **Watch Video**\n🆔 ID: `{msg_id}`"
        
        await file_msg.copy(
            chat_id=message.chat.id,
            caption=caption,
            protect_content=True
        )
        await sts.delete()
            
    except Exception as e:
        print(f"Delivery Error: {e}")
        await message.reply("❌ Error fetching video.")

# ------------------- ৪. অ্যাডমিন কমান্ডস -------------------

@app.on_message(filters.command("setsource") & filters.user(ADMIN_ID))
async def set_src(c, m):
    try:
        if len(m.command) < 2: return await m.reply("Usage: `/setsource -100xxxx`")
        cid = int(m.command[1])
        await update_config("source_channel", cid)
        await m.reply(f"✅ Source Channel Set to: `{cid}`")
    except Exception as e: await m.reply(f"Error: {e}")

@app.on_message(filters.command("setpublic") & filters.user(ADMIN_ID))
async def set_pub(c, m):
    try:
        if len(m.command) < 2: return await m.reply("Usage: `/setpublic -100xxxx`")
        cid = int(m.command[1])
        await update_config("public_channel", cid)
        await m.reply(f"✅ Public Channel Set to: `{cid}`")
    except Exception as e: await m.reply(f"Error: {e}")

@app.on_message(filters.command("status") & filters.user(ADMIN_ID))
async def sys_status(c, m):
    q = await queue_col.count_documents({})
    src = CACHE['source_channel'] if CACHE['source_channel'] else "Not Set"
    pub = CACHE['public_channel'] if CACHE['public_channel'] else "Not Set"
    
    await m.reply(
        f"📊 **BOT STATUS**\n"
        f"📥 Queue Pending: `{q}`\n"
        f"📂 Source: `{src}`\n"
        f"📢 Public: `{pub}`\n"
        f"⚡ FFmpeg: {'Installed' if shutil.which('ffmpeg') else 'Not Found'}"
    )

@app.on_message(filters.command("clean") & filters.user(ADMIN_ID))
async def clean_files(c, m):
    try:
        shutil.rmtree("downloads")
        os.makedirs("downloads")
        await m.reply("🗑️ Download folder cleaned.")
    except: await m.reply("❌ Error cleaning.")

# ------------------- ৫. ভিডিও ডিটেকশন (Listener) -------------------

@app.on_message(filters.channel & (filters.video | filters.document))
async def queue_manager(c, m):
    # শুধুমাত্র সোর্স চ্যানেল থেকে নিবে
    if CACHE["source_channel"] and m.chat.id == int(CACHE["source_channel"]):
        # ডকুমেন্ট হলে সেটা ভিডিও কিনা চেক করা
        is_video = m.video or (m.document and m.document.mime_type and "video" in m.document.mime_type)
        
        if is_video:
            # ডুপ্লিকেট চেক
            exist = await queue_col.find_one({"msg_id": m.id})
            if not exist:
                await queue_col.insert_one({
                    "msg_id": m.id,
                    "caption": m.caption or "New Video",
                    "date": m.date
                })
                print(f"📥 Queued: {m.id}")

# ------------------- ৬. অটোমেশন ইঞ্জিন -------------------

async def post_processor():
    print("🔄 Automation Engine Started...")
    if not os.path.exists("downloads"): os.makedirs("downloads")

    while True:
        try:
            # কনফিগারেশন চেক
            if not CACHE["source_channel"] or not CACHE["public_channel"]:
                await asyncio.sleep(10)
                continue

            # ডাটাবেস থেকে পুরাতন ভিডিও আগে নিবে
            task = await queue_col.find_one(sort=[("date", 1)])
            
            if task:
                msg_id = task["msg_id"]
                print(f"🚀 Processing: {msg_id}")

                try:
                    # ১. মেসেজ ফেচ করা
                    real_msg = await app.get_messages(int(CACHE["source_channel"]), msg_id)
                    if not real_msg or (not real_msg.video and not real_msg.document):
                        print("❌ Source message deleted.")
                        await queue_col.delete_one({"_id": task["_id"]})
                        continue

                    # ২. ডাউনলোড করা
                    video_path = f"downloads/vid_{msg_id}.mp4"
                    dl_msg = await app.download_media(real_msg, file_name=video_path)
                    
                    if not dl_msg:
                        raise Exception("Download Failed")

                    # ৩. থাম্বনেইল জেনারেট করা
                    thumbs = await generate_thumbnails(video_path, msg_id)

                    # ৪. ক্যাপশন এবং লিংক তৈরি
                    bot_username = (await app.get_me()).username
                    deep_link = f"https://t.me/{bot_username}?start={msg_id}"
                    
                    clean_caption = task.get('caption', 'Video').split('\n')[0][:50] # প্রথম লাইন বা ৫০ ক্যারেক্টার
                    text_body = CACHE["caption_template"].format(title=clean_caption)
                    
                    button_markup = InlineKeyboardMarkup([
                        [InlineKeyboardButton("📥 Click To Watch / Download", url=deep_link)],
                        [InlineKeyboardButton("🔗 Official Channel", url=CACHE["tutorial_url"])]
                    ])

                    dest = int(CACHE["public_channel"])

                    # ৫. পোস্ট করা (Album + Text)
                    if thumbs and len(thumbs) >= 2:
                        # প্রথমে অ্যালবাম
                        media_group = [InputMediaPhoto(t) for t in thumbs]
                        await app.send_media_group(dest, media=media_group)
                        
                        # পরে বাটন সহ টেক্সট
