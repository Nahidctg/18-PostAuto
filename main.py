import asyncio
import os
import subprocess
import aiohttp
import time
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait, ChatWriteForbidden, ChatAdminRequired
from motor.motor_asyncio import AsyncIOMotorClient

# ------------------- CONFIGURATION -------------------
API_ID = 22697010
API_HASH = "fd88d7339b0371eb2a9501d523f3e2a7"
BOT_TOKEN = "8303315439:AAGKPEugn60XGMC7_u4pOaZPnUWkWHvXSNM"
MONGO_URL = "mongodb+srv://mewayo8672:mewayo8672@cluster0.ozhvczp.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
ADMIN_ID = 8172129114

# ------------------- DATABASE & CACHE -------------------
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client["AutoPostBot"]
queue_col = db["video_queue"]
config_col = db["config"]

# ডিফল্ট সেটিংস (মেমোরিতে রাখার জন্য)
CACHE = {
    "source_channel": None,
    "public_channel": None,
    "shortener_api": None,
    "shortener_key": None,
    "auto_delete": 0,
    "protect_content": False,
    "post_interval": 30,
    "tutorial_url": "https://t.me/YourChannel"
}

app = Client("final_bot_v4", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ------------------- HELPER FUNCTIONS -------------------

async def load_config():
    """ডাটাবেস থেকে সেটিংস লোড করা"""
    conf = await config_col.find_one({"_id": "settings"})
    if not conf:
        default_conf = {
            "_id": "settings",
            "source_channel": None,
            "public_channel": None,
            "auto_delete": 0,
            "post_interval": 30,
            "tutorial_url": "https://t.me/YourChannel"
        }
        await config_col.insert_one(default_conf)
        conf = default_conf
    CACHE.update(conf)
    print(f"✅ Config Loaded! Interval: {CACHE['post_interval']}s")

async def update_config(key, value):
    """সেটিংস আপডেট করা"""
    await config_col.update_one({"_id": "settings"}, {"$set": {key: value}}, upsert=True)
    CACHE[key] = value

async def shorten_link(link):
    """লিংক শর্ট করা"""
    if not CACHE.get("shortener_api") or not CACHE.get("shortener_key"):
        return link
    try:
        api_url = CACHE["shortener_api"]
        api_key = CACHE["shortener_key"]
        full_url = f"{api_url}?api={api_key}&url={link}"
        async with aiohttp.ClientSession() as session:
            async with session.get(full_url) as resp:
                data = await resp.json()
                return data.get("shortenedUrl") or data.get("url") or link
    except:
        return link

async def generate_thumbnail(video_path):
    """
    ভিডিওর ১০ সেকেন্ড বা ১০% পজিশন থেকে থাম্বনেইল জেনারেট করে।
    """
    thumb_path = f"{video_path}.jpg"
    try:
        # ভিডিওর ডিউরেশন বের করার দরকার নেই, সরাসরি ১০ সেকেন্ডের মাথায় ফ্রেম নেওয়ার চেষ্টা করি
        # যদি ভিডিও ১০ সেকেন্ডের ছোট হয়, তবে ffmpeg অটোমেটিক অ্যাডজাস্ট করবে বা ফেইল করবে
        cmd = [
            "ffmpeg", 
            "-i", video_path, 
            "-ss", "00:00:05",  # ৫ সেকেন্ডের মাথা থেকে স্ন্যাপশট
            "-vframes", "1", 
            "-q:v", "2", 
            thumb_path, 
            "-y"
        ]
        
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()
        
        if os.path.exists(thumb_path):
            return thumb_path
        else:
            print(f"⚠️ FFmpeg Log: {stderr.decode()}")
            return None
    except Exception as e:
        print(f"❌ Thumb Error: {e}")
        return None

# ------------------- ALL ADMIN COMMANDS (FIXED) -------------------

@app.on_message(filters.command("start") & filters.private)
async def start_cmd(c, m):
    if len(m.command) > 1: return # Ignore if deep link
    await m.reply_text(
        "👋 **Bot is Ready!**\n\n"
        "🛠 **Commands:**\n"
        "`/setsource ID` - Source Channel\n"
        "`/setpublic ID` - Target Channel\n"
        "`/setinterval 30` - Post Gap (Seconds)\n"
        "`/autodelete 0` - Auto Delete Time (0 to disable)\n"
        "`/settutorial LINK` - How to Download Link\n"
        "`/setshortener API URL` - Add Shortener\n"
        "`/status` - Check Queue"
    )

@app.on_message(filters.command("setsource") & filters.user(ADMIN_ID))
async def set_src(c, m):
    try:
        cid = int(m.command[1])
        await update_config("source_channel", cid)
        await m.reply_text(f"✅ Source Channel Set: `{cid}`")
    except: await m.reply_text("❌ Example: `/setsource -1001234567890`")

@app.on_message(filters.command("setpublic") & filters.user(ADMIN_ID))
async def set_pub(c, m):
    try:
        cid = int(m.command[1])
        await update_config("public_channel", cid)
        await m.reply_text(f"✅ Public Channel Set: `{cid}`")
    except: await m.reply_text("❌ Example: `/setpublic -1001234567890`")

@app.on_message(filters.command("setinterval") & filters.user(ADMIN_ID))
async def set_int(c, m):
    try:
        sec = int(m.command[1])
        await update_config("post_interval", sec)
        await m.reply_text(f"⏱ Post Interval Set: `{sec} seconds`")
    except: await m.reply_text("❌ Example: `/setinterval 60`")

@app.on_message(filters.command("autodelete") & filters.user(ADMIN_ID))
async def set_del(c, m):
    try:
        sec = int(m.command[1])
        await update_config("auto_delete", sec)
        await m.reply_text(f"🗑 Auto Delete Set: `{sec} seconds` (0 = Off)")
    except: await m.reply_text("❌ Example: `/autodelete 300`")

@app.on_message(filters.command("settutorial") & filters.user(ADMIN_ID))
async def set_tut(c, m):
    try:
        link = m.text.split(None, 1)[1]
        await update_config("tutorial_url", link)
        await m.reply_text(f"🔗 Tutorial Link Set!")
    except: await m.reply_text("❌ Example: `/settutorial https://youtube.com/...`")

@app.on_message(filters.command("setshortener") & filters.user(ADMIN_ID))
async def set_short(c, m):
    try:
        parts = m.text.split()
        if len(parts) < 3: return await m.reply("❌ Use: `/setshortener API_URL API_KEY`")
        await update_config("shortener_api", parts[1])
        await update_config("shortener_key", parts[2])
        await m.reply_text("✅ Shortener Configured!")
    except: await m.reply_text("❌ Error.")

@app.on_message(filters.command("status") & filters.user(ADMIN_ID))
async def status_cmd(c, m):
    q = await queue_col.count_documents({})
    interval = CACHE.get("post_interval", 30)
    d = CACHE.get("auto_delete", 0)
    await m.reply_text(
        f"📊 **BOT STATUS**\n"
        f"📩 Queue Size: `{q}`\n"
        f"⏱ Interval: `{interval}s`\n"
        f"🗑 Auto Del: `{d}s`\n"
        f"📢 Source: `{CACHE['source_channel']}`\n"
        f"📢 Public: `{CACHE['public_channel']}`"
    )

# ------------------- VIDEO CAPTURE LOGIC -------------------

@app.on_message(filters.channel & (filters.video | filters.document))
async def incoming_handler(c, m):
    # সোর্স চ্যানেল ম্যাচিং
    if CACHE["source_channel"] and m.chat.id == int(CACHE["source_channel"]):
        # ভিডিও বা ভিডিও ফাইল চেক
        file_id = None
        if m.video:
            file_id = m.video.file_id
        elif m.document and m.document.mime_type and "video" in m.document.mime_type:
            file_id = m.document.file_id
        
        if file_id:
            await queue_col.insert_one({
                "msg_id": m.id,
                "caption": m.caption or "Video",
                "file_id": file_id,
                "date": m.date
            })
            print(f"➕ Added to Queue: MsgID {m.id}")

# ------------------- MAIN POSTING LOOP -------------------

async def post_scheduler():
    print("🔄 Scheduler Started...")
    
    while True:
        try:
            if not CACHE["source_channel"] or not CACHE["public_channel"]:
                await asyncio.sleep(10)
                continue
            
            # ১. কিউ থেকে ভিডিও নেওয়া
            video_data = await queue_col.find_one(sort=[("date", 1)])
            
            if video_data:
                msg_id = video_data["msg_id"]
                print(f"🚀 Processing: {msg_id}")
                
                # ২. মেসেজ ডাউনলোড করা (থাম্বনেইল বানানোর জন্য)
                dl_path = None
                thumb_path = None
                
                try:
                    real_msg = await app.get_messages(int(CACHE["source_channel"]), msg_id)
                    if not real_msg:
                        await queue_col.delete_one({"_id": video_data["_id"]}); continue
                    
                    print("⬇️ Downloading video (Please wait)...")
                    dl_path = await app.download_media(real_msg)
                    
                    if dl_path:
                        print("🎨 Generating Thumbnail...")
                        thumb_path = await generate_thumbnail(dl_path)
                except Exception as e:
                    print(f"❌ Download/Thumb Error: {e}")
                
                # ৩. লিংক এবং ক্যাপশন তৈরি
                bot_usr = (await app.get_me()).username
                start_link = f"https://t.me/{bot_usr}?start={msg_id}"
                final_link = await shorten_link(start_link)
                
                caption_text = video_data.get('caption', 'Video')
                final_caption = (
                    f"🎬 **{caption_text[:150]}**\n\n"
                    f"🔗 **Download Link:** {final_link}"
                )
                
                buttons = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📥 Fast Download / Watch", url=final_link)],
                    [InlineKeyboardButton("⁉️ How to Download", url=CACHE["tutorial_url"])]
                ])

                # ৪. পাবলিক চ্যানেলে পোস্ট করা
                dest_id = int(CACHE["public_channel"])
                try:
                    if thumb_path:
                        # যদি কাস্টম থাম্বনেইল তৈরি হয়
                        await app.send_photo(dest_id, photo=thumb_path, caption=final_caption, reply_markup=buttons)
                    else:
                        # যদি থাম্বনেইল না হয়, তবে সাধারণ মেসেজ
                        print("⚠️ Posting without custom thumbnail.")
                        await app.send_message(dest_id, text=final_caption, reply_markup=buttons)

                    # ৫. সফল হলে কিউ থেকে ডিলিট
                    print(f"✅ Posted Successfully: {msg_id}")
                    await queue_col.delete_one({"_id": video_data["_id"]})

                except FloodWait as e:
                    print(f"⏳ FloodWait: {e.value}s")
                    await asyncio.sleep(e.value)
                except Exception as e:
                    print(f"❌ Posting Failed: {e}")
                    # এরর হলে স্কিপ করা (না হলে লুপে আটকে থাকবে)
                    await queue_col.delete_one({"_id": video_data["_id"]})

                # ৬. ক্লিন আপ (ফাইল ডিলিট)
                try:
                    if dl_path and os.path.exists(dl_path): os.remove(dl_path)
                    if thumb_path and os.path.exists(thumb_path): os.remove(thumb_path)
                except: pass

            else:
                pass # Queue Empty

        except Exception as e:
            print(f"Critical Error: {e}")
            await asyncio.sleep(5)
        
        # Interval Wait
        await asyncio.sleep(CACHE.get("post_interval", 30))

# ------------------- STARTUP -------------------

async def main():
    await app.start()
    await load_config()
    print("✅ Bot Started. Waiting for videos...")
    asyncio.create_task(post_scheduler())
    await idle()
    await app.stop()

if __name__ == "__main__":
    app.run(main())
