import asyncio
import os
import shutil
import time
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from motor.motor_asyncio import AsyncIOMotorClient
from aiohttp import web

# ------------------- কনফিগারেশন -------------------
API_ID = 22697010
API_HASH = "fd88d7339b0371eb2a9501d523f3e2a7"
BOT_TOKEN = "8303315439:AAGKPEugn60XGMC7_u4pOaZPnUWkWHvXSNM"
MONGO_URL = "mongodb+srv://mewayo8672:mewayo8672@cluster0.ozhvczp.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
ADMIN_ID = 8172129114  # আপনার আইডি

# ডাটাবেস
mongo = AsyncIOMotorClient(MONGO_URL)
db = mongo["SimpleAutoBot"]
queue_col = db["queue"]
config_col = db["config"]

# গ্লোবাল ভেরিয়েবল
CONFIG = {
    "source": None,
    "public": None,
    "caption": "🎬 **{caption}**\n\n✨ **Join Us:** {link}"
}

app = Client("simple_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ------------------- ১. ওয়েব সার্ভার (বট সচল রাখার জন্য) -------------------
async def web_server():
    async def handle(req): return web.Response(text="Bot is Alive")
    app_web = web.Application()
    app_web.add_routes([web.get('/', handle)])
    runner = web.AppRunner(app_web)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 8080))).start()

# ------------------- ২. সেটিংস লোড/সেভ -------------------
async def load_settings():
    data = await config_col.find_one({"_id": "main"})
    if not data:
        await config_col.insert_one({"_id": "main", "source": None, "public": None})
    else:
        CONFIG["source"] = data.get("source")
        CONFIG["public"] = data.get("public")
    print(f"⚙️ Settings Loaded: SRC={CONFIG['source']} | PUB={CONFIG['public']}")

async def save_setting(key, val):
    await config_col.update_one({"_id": "main"}, {"$set": {key: val}}, upsert=True)
    CONFIG[key] = val

# ------------------- ৩. একটি থাম্বনেইল জেনারেটর -------------------
async def get_thumbnail(video_path, msg_id):
    """ভিডিওর ৫ সেকেন্ড থেকে ১টি ছবি নিবে"""
    thumb_path = f"downloads/thumb_{msg_id}.jpg"
    
    # FFmpeg আছে কিনা চেক
    if not shutil.which("ffmpeg"):
        return None

    try:
        # -ss 00:00:05 মানে ৫ সেকেন্ডের মাথার ছবি
        cmd = [
            "ffmpeg", "-ss", "00:00:05", "-i", video_path,
            "-vframes", "1", "-q:v", "2", thumb_path, "-y"
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        await proc.wait()
        
        if os.path.exists(thumb_path):
            return thumb_path
    except Exception as e:
        print(f"Thumb Error: {e}")
    
    return None

# ------------------- ৪. অ্যাডমিন কমান্ড -------------------

# /start কমান্ড (Admin & User)
@app.on_message(filters.command("start"))
async def start_cmd(c, m):
    # ইউজার ডেলিভারি সিস্টেম
    if len(m.command) > 1:
        try:
            msg_id = int(m.command[1])
            if CONFIG["source"]:
                original = await c.get_messages(CONFIG["source"], msg_id)
                if original and (original.video or original.document):
                    await original.copy(m.chat.id, caption="✅ **Here is your video!**")
                    return
        except: pass
        return await m.reply("❌ Video not found.")

    # অ্যাডমিন প্যানেল মেসেজ
    if m.from_user.id == ADMIN_ID:
        await m.reply(
            "👋 **Admin Menu**\n\n"
            "1️⃣ `/setsource -100xxxx` (যেখান থেকে ভিডিও নিবে)\n"
            "2️⃣ `/setpublic -100xxxx` (যেখানে পোস্ট করবে)\n"
            "3️⃣ `/status` (অবস্থা দেখুন)\n"
            "4️⃣ `/clear` (লাইন ক্লিয়ার করুন)"
        )
    else:
        await m.reply("🤖 Bot is running.")

@app.on_message(filters.command("setsource") & filters.user(ADMIN_ID))
async def set_s(c, m):
    try:
        cid = int(m.command[1])
        await save_setting("source", cid)
        await m.reply(f"✅ Source Channel: `{cid}`")
    except: await m.reply("ভুল! ব্যবহার: `/setsource -100123456`")

@app.on_message(filters.command("setpublic") & filters.user(ADMIN_ID))
async def set_p(c, m):
    try:
        cid = int(m.command[1])
        await save_setting("public", cid)
        await m.reply(f"✅ Public Channel: `{cid}`")
    except: await m.reply("ভুল! ব্যবহার: `/setpublic -100123456`")

@app.on_message(filters.command("status") & filters.user(ADMIN_ID))
async def stats(c, m):
    cnt = await queue_col.count_documents({})
    await m.reply(f"📊 **Status**\nPending: {cnt}\nSource: `{CONFIG['source']}`\nPublic: `{CONFIG['public']}`")

@app.on_message(filters.command("clear") & filters.user(ADMIN_ID))
async def clear_q(c, m):
    await queue_col.delete_many({})
    await m.reply("🗑 Queue Cleared!")

# ------------------- ৫. ভিডিও ডিটেকশন -------------------
@app.on_message(filters.channel & (filters.video | filters.document))
async def watcher(c, m):
    # সোর্স চ্যানেল চেক
    if CONFIG["source"] and m.chat.id == int(CONFIG["source"]):
        # ফাইলটি ভিডিও কিনা নিশ্চিত হওয়া
        is_vid = m.video or (m.document and "video" in m.document.mime_type)
        if is_vid:
            # ডাটাবেসে সেভ
            await queue_col.insert_one({
                "msg_id": m.id,
                "caption": m.caption or "New Video",
                "date": m.date
            })
            print(f"📥 New Video Detected: {m.id}")

# ------------------- ৬. মেইন প্রসেসর (ইঞ্জিন) -------------------
async def processor():
    print("🚀 Processor Started...")
    if not os.path.exists("downloads"): os.makedirs("downloads")

    while True:
        try:
            # সেটিংস চেক
            if not CONFIG["source"] or not CONFIG["public"]:
                await asyncio.sleep(10); continue

            # ১. কিউ থেকে ডাটা নেওয়া
            task = await queue_col.find_one(sort=[("date", 1)])
            if not task:
                await asyncio.sleep(5); continue

            msg_id = task["msg_id"]
            print(f"🔄 Processing: {msg_id}")

            try:
                # ২. অরিজিনাল মেসেজ আনা
                msg = await app.get_messages(int(CONFIG["source"]), msg_id)
                if not msg or (not msg.video and not msg.document):
                    print("❌ Message missing/deleted")
                    await queue_col.delete_one({"_id": task["_id"]}); continue

                # ৩. ডাউনলোড করা
                vid_path = f"downloads/v_{msg_id}.mp4"
                dl = await app.download_media(msg, file_name=vid_path)
                
                # ৪. থাম্বনেইল জেনারেট (১টি ছবি)
                thumb_path = await get_thumbnail(vid_path, msg_id)

                # ৫. ক্যাপশন ও বাটন
                bot_usr = (await app.get_me()).username
                link = f"https://t.me/{bot_usr}?start={msg_id}"
                my_caption = f"🎬 **{task.get('caption', 'Video')[:80]}**\n\n👇 **Download / Watch Below**"
                
                btn = InlineKeyboardMarkup([[InlineKeyboardButton("📥 Download Video", url=link)]])

                # ৬. পোস্ট করা (সরাসরি ভিডিও সেন্ড)
                dest = int(CONFIG["public"])
                
                # থাম্বনেইল সহ পাঠানো (যদি জেনারেট হয়ে থাকে)
                if thumb_path:
                    await app.send_video(
                        dest, video=vid_path, thumb=thumb_path, 
                        caption=my_caption, reply_markup=btn
                    )
                else:
                    # থাম্বনেইল ফেইল করলে নরমাল পাঠানো
                    await app.send_video(
                        dest, video=vid_path, 
                        caption=my_caption, reply_markup=btn
                    )

                print(f"✅ Posted Success: {msg_id}")
                
            except Exception as ex:
                print(f"⚠️ Task Failed: {ex}")
            
            # কাজ শেষ, ডিলিট এবং ক্লিনআপ
            await queue_col.delete_one({"_id": task["_id"]})
            
            if os.path.exists(vid_path): os.remove(vid_path)
            if thumb_path and os.path.exists(thumb_path): os.remove(thumb_path)
            
            # ৩০ সেকেন্ড বিরতি (যাতে সার্ভার হ্যাং না হয়)
            await asyncio.sleep(30)

        except Exception as e:
            print(f"Critical Error: {e}")
            await asyncio.sleep(10)

# ------------------- ৭. রানার -------------------
async def main():
    asyncio.create_task(web_server()) # ওয়েব সার্ভার চালু
    await app.start()
    await load_settings()
    
    print("✅ Bot is Online & Ready!")
    asyncio.create_task(processor()) # ইঞ্জিন চালু
    
    await idle()
    await app.stop()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
