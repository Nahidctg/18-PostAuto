import asyncio
import os
import shutil
import time
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from motor.motor_asyncio import AsyncIOMotorClient
from aiohttp import web

# ------------------- ১. কনফিগারেশন -------------------
API_ID = 22697010
API_HASH = "fd88d7339b0371eb2a9501d523f3e2a7"
BOT_TOKEN = "8303315439:AAGKPEugn60XGMC7_u4pOaZPnUWkWHvXSNM"
MONGO_URL = "mongodb+srv://mewayo8672:mewayo8672@cluster0.ozhvczp.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
ADMIN_ID = 8172129114

# ডাটাবেস সেটআপ
mongo = AsyncIOMotorClient(MONGO_URL)
db = mongo["IncomeBot_Pro"]
queue_col = db["queue"]
config_col = db["config"]

# গ্লোবাল কনফিগ
CONFIG = {
    "source": None,
    "public": None
}

app = Client("traffic_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ------------------- ২. ওয়েব সার্ভার (বট যাতে বন্ধ না হয়) -------------------
async def web_server():
    async def handle(req): return web.Response(text="Bot is Running & Ready for Traffic!")
    app_web = web.Application()
    app_web.add_routes([web.get('/', handle)])
    runner = web.AppRunner(app_web)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 8080))).start()

# ------------------- ৩. সেটিংস লোড/সেভ -------------------
async def load_settings():
    data = await config_col.find_one({"_id": "main"})
    if not data:
        await config_col.insert_one({"_id": "main", "source": None, "public": None})
    else:
        CONFIG["source"] = data.get("source")
        CONFIG["public"] = data.get("public")
    print(f"⚙️ Settings: SRC={CONFIG['source']} | PUB={CONFIG['public']}")

async def save_setting(key, val):
    await config_col.update_one({"_id": "main"}, {"$set": {key: val}}, upsert=True)
    CONFIG[key] = val

# ------------------- ৪. থাম্বনেইল জেনারেটর -------------------
async def get_thumbnail(video_path, msg_id):
    """ভিডিওর ১০ সেকেন্ড মাথা থেকে ১টি এইচডি স্ক্রিনশট নিবে"""
    thumb_path = f"downloads/thumb_{msg_id}.jpg"
    
    if not shutil.which("ffmpeg"):
        print("❌ FFmpeg not installed!")
        return None

    try:
        # -ss 00:00:10 (১০ সেকেন্ড) -q:v 2 (High Quality)
        cmd = [
            "ffmpeg", "-ss", "00:00:10", "-i", video_path,
            "-vframes", "1", "-q:v", "2", thumb_path, "-y"
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        await proc.wait()
        
        if os.path.exists(thumb_path):
            return thumb_path
    except Exception as e:
        print(f"Thumb Gen Error: {e}")
    
    return None

# ------------------- ৫. বট ও ইউজার হ্যান্ডলিং (/start) -------------------

@app.on_message(filters.command("start"))
async def start_cmd(c, m):
    # ১. ইউজার যখন ভিডিও লিংক এ ক্লিক করে বটে আসবে
    if len(m.command) > 1:
        try:
            msg_id = int(m.command[1])
            if CONFIG["source"]:
                # প্রসেসিং মেসেজ
                sts = await m.reply("🔄 Fetching your video...")
                
                # সোর্স চ্যানেল থেকে ভিডিও কপি করে ইউজারকে দিবে
                original = await c.get_messages(CONFIG["source"], msg_id)
                if original and (original.video or original.document):
                    await original.copy(
                        chat_id=m.chat.id,
                        caption="✅ **Here is the video you requested!**\n\n🔥 Join our channel for more!"
                    )
                    await sts.delete()
                else:
                    await sts.edit("❌ Video deleted or not found.")
        except Exception as e:
            print(f"Delivery Error: {e}")
            await m.reply("❌ Error occurred.")
        return

    # ২. অ্যাডমিন প্যানেল
    if m.from_user.id == ADMIN_ID:
        await m.reply(
            "👮‍♂️ **Owner Control Panel**\n\n"
            "1️⃣ `/setsource -100xxxx` (Source Channel)\n"
            "2️⃣ `/setpublic -100xxxx` (Public Channel)\n"
            "3️⃣ `/status` (Check Queue)"
        )
    else:
        await m.reply("👋 I am a video delivery bot. Wait for links in the main channel!")

# অ্যাডমিন কমান্ডস
@app.on_message(filters.command("setsource") & filters.user(ADMIN_ID))
async def set_s(c, m):
    try:
        await save_setting("source", int(m.command[1]))
        await m.reply(f"✅ Source Set: `{m.command[1]}`")
    except: await m.reply("Usage: `/setsource -100xxxx`")

@app.on_message(filters.command("setpublic") & filters.user(ADMIN_ID))
async def set_p(c, m):
    try:
        await save_setting("public", int(m.command[1]))
        await m.reply(f"✅ Public Set: `{m.command[1]}`")
    except: await m.reply("Usage: `/setpublic -100xxxx`")

@app.on_message(filters.command("status") & filters.user(ADMIN_ID))
async def stats(c, m):
    q = await queue_col.count_documents({})
    await m.reply(f"📊 Queue: {q}\nSrc: {CONFIG['source']}\nPub: {CONFIG['public']}")

@app.on_message(filters.command("clear") & filters.user(ADMIN_ID))
async def clr(c, m):
    await queue_col.delete_many({})
    await m.reply("🗑 Queue Cleared!")

# ------------------- ৬. ভিডিও ডিটেকশন (Listener) -------------------
@app.on_message(filters.channel & (filters.video | filters.document))
async def watcher(c, m):
    if CONFIG["source"] and m.chat.id == int(CONFIG["source"]):
        is_vid = m.video or (m.document and "video" in m.document.mime_type)
        if is_vid:
            # ডুপ্লিকেট চেক
            if not await queue_col.find_one({"msg_id": m.id}):
                await queue_col.insert_one({
                    "msg_id": m.id,
                    "caption": m.caption or "Exclusive Video",
                    "date": m.date
                })
                print(f"📥 Video Queued: {m.id}")

# ------------------- ৭. মেইন প্রসেসর (Traffic Logic) -------------------
async def processor():
    print("🚀 Traffic Engine Started...")
    if not os.path.exists("downloads"): os.makedirs("downloads")

    while True:
        try:
            if not CONFIG["source"] or not CONFIG["public"]:
                await asyncio.sleep(10); continue

            task = await queue_col.find_one(sort=[("date", 1)])
            if not task:
                await asyncio.sleep(5); continue

            msg_id = task["msg_id"]
            print(f"🔨 Processing ID: {msg_id}")

            try:
                # মেসেজ আনা
                msg = await app.get_messages(int(CONFIG["source"]), msg_id)
                if not msg:
                    await queue_col.delete_one({"_id": task["_id"]}); continue

                # ১. ভিডিও ডাউনলোড (শুধুমাত্র থাম্বনেইল বানানোর জন্য)
                vid_path = f"downloads/v_{msg_id}.mp4"
                await app.download_media(msg, file_name=vid_path)
                
                # ২. থাম্বনেইল জেনারেট
                thumb_path = await get_thumbnail(vid_path, msg_id)

                # ৩. ডিপ লিংক তৈরি (ইনকামের রাস্তা)
                bot_usr = (await app.get_me()).username
                deep_link = f"https://t.me/{bot_usr}?start={msg_id}"
                
                # ৪. পাবলিক চ্যানেলে পোস্ট (শুধুমাত্র ফটো)
                caption_text = (
                    f"🎬 **{task.get('caption', 'New Video')[:100]}**\n\n"
                    f"📺 **Video Quality:** HD 720p\n"
                    f"⏳ **Duration:** Full Video\n\n"
                    f"👇 **Click Below to Watch Video** 👇"
                )
                
                btn = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📥 DOWNLOAD / WATCH VIDEO 📥", url=deep_link)],
                    [InlineKeyboardButton("🔥 Join Backup Channel", url="https://t.me/YourChannel")]
                ])

                dest = int(CONFIG["public"])

                # যদি থাম্বনেইল জেনারেট হয়, সেটা আপলোড করবে
                if thumb_path and os.path.exists(thumb_path):
                    await app.send_photo(
                        chat_id=dest,
                        photo=thumb_path,
                        caption=caption_text,
                        reply_markup=btn
                    )
                # থাম্বনেইল ফেইল হলে, সোর্সের ডিফল্ট থাম্ব বা টেক্সট দিবে (ভিডিও দিবে না)
                else:
                    await app.send_message(
                        chat_id=dest,
                        text=f"{caption_text}\n\n⚠️ *No Thumbnail Available*",
                        reply_markup=btn
                    )

                print(f"✅ Post Successful (Photo Only): {msg_id}")

            except Exception as e:
                print(f"❌ Task Failed: {e}")
            
            # ক্লিনআপ
            await queue_col.delete_one({"_id": task["_id"]})
            try:
                if os.path.exists(vid_path): os.remove(vid_path)
                if thumb_path and os.path.exists(thumb_path): os.remove(thumb_path)
            except: pass
            
            # পোস্ট ইন্টারভাল (৩০ সেকেন্ড)
            await asyncio.sleep(30)

        except Exception as e:
            print(f"Engine Crash: {e}")
            await asyncio.sleep(5)

# ------------------- ৮. রানার -------------------
async def main():
    asyncio.create_task(web_server())
    await app.start()
    await load_settings()
    print("✅ Bot Started in Traffic Mode!")
    asyncio.create_task(processor())
    await idle()
    await app.stop()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
