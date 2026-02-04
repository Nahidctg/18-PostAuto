import asyncio
import os
import shutil
import subprocess
import aiohttp
from pyrogram import Client, filters, idle
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
)
from pyrogram.errors import FloodWait, ChatWriteForbidden
from motor.motor_asyncio import AsyncIOMotorClient

# ------------------- ১. কনফিগারেশন -------------------
API_ID = 22697010
API_HASH = "fd88d7339b0371eb2a9501d523f3e2a7"
BOT_TOKEN = "8303315439:AAGKPEugn60XGMC7_u4pOaZPnUWkWHvXSNM"
MONGO_URL = "mongodb+srv://mewayo8672:mewayo8672@cluster0.ozhvczp.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
ADMIN_ID = 8172129114

mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client["AutoPostBot_Viral"]
queue_col = db["queue"]
config_col = db["config"]

CACHE = {
    "source_channel": None,
    "public_channel": None,
    "shortener_api": None,
    "shortener_key": None,
    "auto_delete": 0,
    "post_interval": 60,
    "tutorial_url": "https://t.me/YourChannel"
}

app = Client("viral_bot_pro", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ------------------- ২. হেল্পার ফাংশন -------------------

async def load_config():
    conf = await config_col.find_one({"_id": "settings"})
    if not conf:
        default = {
            "_id": "settings",
            "source_channel": None,
            "public_channel": None,
            "auto_delete": 0,
            "post_interval": 60,
            "tutorial_url": "https://t.me/"
        }
        await config_col.insert_one(default)
        conf = default
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

# ------------------- ৩. ভাইরাল থাম্বনেইল জেনারেটর -------------------

async def generate_screenshots(video_path):
    """
    ভিডিও থেকে ৩টি স্ক্রিনশট নিবে (শুরু, মাঝ, শেষ)
    """
    if not shutil.which("ffmpeg"):
        return []

    thumbs = []
    # ৩টি ভিন্ন টাইমফ্রেম (ভিডিওর ৫ সেকেন্ড, ১৫ সেকেন্ড, ২৫ সেকেন্ড)
    # আপনার ভিডিও ছোট হলে এটি প্রথম ফ্রেমগুলোই নিবে
    timestamps = ["00:00:05", "00:00:15", "00:00:30"]
    
    for i, time in enumerate(timestamps):
        out_file = f"{video_path}_thumb_{i}.jpg"
        try:
            subprocess.call([
                "ffmpeg", "-ss", time, "-i", video_path,
                "-vframes", "1", "-q:v", "2", out_file, "-y"
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            if os.path.exists(out_file):
                thumbs.append(out_file)
        except: pass
    
    return thumbs

# ------------------- ৪. কমান্ডস (Start & Admin) -------------------

@app.on_message(filters.command("start") & filters.private)
async def start_handler(client, message):
    if len(message.command) > 1:
        return await send_video_to_user(client, message)
    await message.reply_text("👋 **Viral Bot is Ready!**\nUse /setsource & /setpublic to setup.")

async def send_video_to_user(client, message):
    try:
        msg_id = int(message.command[1])
        if not CACHE["source_channel"]: return await message.reply("❌ Channel not set")
        
        file_msg = await client.get_messages(int(CACHE["source_channel"]), msg_id)
        if not file_msg: return await message.reply("❌ Video Deleted")

        caption = f"✅ **Here is your video!**\n🆔 ID: `{msg_id}`"
        sent = await file_msg.copy(message.chat.id, caption=caption, protect_content=True)

        if CACHE["auto_delete"] > 0:
            await message.reply(f"⏳ Deleting in {CACHE['auto_delete']}s...")
            await asyncio.sleep(CACHE["auto_delete"])
            await sent.delete()
    except Exception as e:
        await message.reply(f"❌ Error: {e}")

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

@app.on_message(filters.command("status") & filters.user(ADMIN_ID))
async def stat(c, m):
    q = await queue_col.count_documents({})
    await m.reply(f"📊 Queue: {q}\nConfig: Source={CACHE['source_channel']}")

@app.on_message(filters.command("clearqueue") & filters.user(ADMIN_ID))
async def clr(c, m):
    await queue_col.delete_many({})
    await m.reply("🗑 Cleared")

# ------------------- ৫. রিসিভার -------------------

@app.on_message(filters.channel & (filters.video | filters.document))
async def incoming(c, m):
    if CACHE["source_channel"] and m.chat.id == int(CACHE["source_channel"]):
        f_id = m.video.file_id if m.video else (m.document.file_id if m.document else None)
        if f_id:
            await queue_col.insert_one({
                "msg_id": m.id,
                "caption": m.caption or "Viral Video",
                "date": m.date
            })
            print(f"➕ Added: {m.id}")

# ------------------- ৬. মেইন শিডিউলার (Viral Logic) -------------------

async def post_scheduler():
    print("🔄 Scheduler Started...")
    while True:
        try:
            if not CACHE["source_channel"] or not CACHE["public_channel"]:
                await asyncio.sleep(10); continue

            data = await queue_col.find_one(sort=[("date", 1)])
            if data:
                msg_id = data["msg_id"]
                print(f"🚀 Processing: {msg_id}")

                real_msg = None
                try:
                    real_msg = await app.get_messages(int(CACHE["source_channel"]), msg_id)
                except: pass

                if not real_msg:
                    await queue_col.delete_one({"_id": data["_id"]}); continue

                # ভিডিও ডাউনলোড এবং স্ক্রিনশট নেওয়া
                video_path = None
                thumbs = []
                try:
                    print("⬇️ Downloading Video...")
                    video_path = await app.download_media(real_msg, file_name=f"v_{msg_id}.mp4")
                    if video_path:
                        print("🎨 Generating Screenshots...")
                        thumbs = await generate_screenshots(video_path)
                except Exception as e:
                    print(f"Download Error: {e}")

                # লিংক ও ক্যাপশন
                bot_usr = (await app.get_me()).username
                link = await shorten_link(f"https://t.me/{bot_usr}?start={msg_id}")
                
                caption_text = data.get('caption', 'Video')
                pretty_caption = (
                    f"🔥 **{caption_text[:100]}**\n\n"
                    f"✨ **Quality:** HD Streaming\n"
                    f"🔗 **Download Link:** {link}"
                )
                
                buttons = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📥 Download / Watch Video", url=link)],
                    [InlineKeyboardButton("🔞 Join Premium Channel", url=CACHE["tutorial_url"])]
                ])

                # পোস্টিং লজিক (অ্যালবাম + বাটন)
                dest = int(CACHE["public_channel"])
                try:
                    # ১. যদি স্ক্রিনশট জেনারেট হয়, তাহলে অ্যালবাম হিসেবে পাঠাবে
                    if thumbs:
                        media_group = [InputMediaPhoto(t) for t in thumbs]
                        await app.send_media_group(dest, media=media_group)
                        # অ্যালবাম পাঠানোর পর নিচে বাটন সহ টেক্সট
                        await app.send_message(dest, text=pretty_caption, reply_markup=buttons)
                    
                    # ২. যদি স্ক্রিনশট না হয় (FFmpeg ফেইল), তাহলে সাধারণ পোস্ট
                    else:
                        print("⚠️ No thumbs generated, sending normal post")
                        # অরিজিনাল থাম্বনেইল ট্রাই করা
                        t_path = None
                        if real_msg.thumbs:
                            t_path = await app.download_media(real_msg.thumbs[0].file_id)
                        
                        if t_path:
                            await app.send_photo(dest, t_path, caption=pretty_caption, reply_markup=buttons)
                            os.remove(t_path)
                        else:
                            await app.send_message(dest, text=pretty_caption, reply_markup=buttons)

                    print(f"✅ Posted: {msg_id}")
                    await queue_col.delete_one({"_id": data["_id"]})

                except Exception as e:
                    print(f"❌ Post Failed: {e}")
                    # এরর হলেও কিউ থেকে সরাচ্ছি
                    await queue_col.delete_one({"_id": data["_id"]})

                # ক্লিনআপ
                try:
                    if video_path and os.path.exists(video_path): os.remove(video_path)
                    for t in thumbs:
                        if os.path.exists(t): os.remove(t)
                except: pass
            
            else: pass

        except Exception as e:
            print(f"Loop Error: {e}")
            await asyncio.sleep(5)
        
        await asyncio.sleep(CACHE.get("post_interval", 60))

# ------------------- রানার -------------------
async def main():
    if not os.path.exists("downloads"): os.makedirs("downloads")
    await app.start()
    await load_config()
    asyncio.create_task(post_scheduler())
    await idle()
    await app.stop()

if __name__ == "__main__":
    app.run(main())
