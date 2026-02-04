import asyncio
import logging
import os
import time
import math
import shutil
import aiohttp
from PIL import Image
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait
from motor.motor_asyncio import AsyncIOMotorClient

# ------------------- CONFIGURATION -------------------
API_ID = 22697010
API_HASH = "fd88d7339b0371eb2a9501d523f3e2a7"
BOT_TOKEN = "8303315439:AAGKPEugn60XGMC7_u4pOaZPnUWkWHvXSNM"
MONGO_URL = "mongodb+srv://mewayo8672:mewayo8672@cluster0.ozhvczp.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
ADMIN_ID = 8172129114

# ------------------- DATABASE CONNECTION -------------------
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client["AutoPostBot"]
queue_col = db["video_queue"]
config_col = db["config"]

# মেমোরি ক্যাশ
CACHE = {
    "source_channel": None,
    "public_channel": None,
    "shortener_api": None,
    "shortener_key": None,
    "auto_delete": 0,
    "protect_content": False,
    "post_interval": 1800,
    "tutorial_url": "https://t.me/YourTutorialLink" # ডিফল্ট টিউটোরিয়াল লিংক
}

app = Client("smart_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ------------------- HELPER FUNCTIONS -------------------

async def load_config():
    conf = await config_col.find_one({"_id": "settings"})
    if not conf:
        default_conf = {
            "_id": "settings",
            "source_channel": None,
            "public_channel": None,
            "shortener_api": "",
            "shortener_key": "",
            "auto_delete": 0,
            "protect_content": False,
            "post_interval": 1800,
            "tutorial_url": "https://youtube.com"
        }
        await config_col.insert_one(default_conf)
        conf = default_conf
    
    CACHE.update(conf)
    if "post_interval" not in CACHE: CACHE["post_interval"] = 1800
    if "tutorial_url" not in CACHE: CACHE["tutorial_url"] = "https://youtube.com"
    print("✅ Configuration Loaded Successfully!")

async def update_config(key, value):
    await config_col.update_one({"_id": "settings"}, {"$set": {key: value}}, upsert=True)
    CACHE[key] = value

async def shorten_link(link):
    if not CACHE["shortener_api"] or not CACHE["shortener_key"]:
        return link
    try:
        api_url = CACHE["shortener_api"]
        api_key = CACHE["shortener_key"]
        full_url = f"{api_url}?api={api_key}&url={link}"
        async with aiohttp.ClientSession() as session:
            async with session.get(full_url) as resp:
                data = await resp.json()
                return data.get("shortenedUrl") or data.get("url") or link
    except Exception as e:
        print(f"⚠️ Shortener Failed: {e}")
        return link

# --- Thumbnail Collage Generator ---
async def create_collage(video_path, output_path):
    try:
        # ৪টি স্ক্রিনশট নেওয়ার চেষ্টা (FFmpeg দরকার)
        # এখানে সাধারণ লজিক ব্যবহার করা হয়েছে যাতে সার্ভার হ্যাং না করে
        # আপনার সার্ভারে FFmpeg না থাকলে এটি স্কিপ করে ডিফল্ট থাম্ব ব্যবহার করবে
        pass 
    except Exception as e:
        print(f"Collage Error: {e}")
    return None

# ------------------- ADMIN COMMANDS -------------------

@app.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    if len(message.command) > 1:
        return await send_stored_file(client, message)
    
    await message.reply_text(
        "👋 **স্বাগতম!** আমি অটো পোস্টার বট।\n\n"
        "🛠 **এডমিন কমান্ড লিস্ট:**\n"
        "1. `/setsource -100xxxx` (সোর্স চ্যানেল)\n"
        "2. `/setpublic -100xxxx` (পাবলিক চ্যানেল)\n"
        "3. `/setinterval 10` (পোস্টিং গ্যাপ - সেকেন্ডে)\n"
        "4. `/setshortener URL KEY` (শর্টনার)\n"
        "5. `/settutorial LINK` (টিউটোরিয়াল লিংক)\n"
        "6. `/status` (পেন্ডিং এবং সেটিংস চেক)"
    )

@app.on_message(filters.command("settutorial") & filters.user(ADMIN_ID))
async def set_tutorial(client, message):
    try:
        link = message.command[1]
        await update_config("tutorial_url", link)
        await message.reply_text(f"✅ **টিউটোরিয়াল লিংক সেট করা হয়েছে:**\n{link}")
    except:
        await message.reply_text("❌ ভুল! লিখুন: `/settutorial https://t.me/...`")

@app.on_message(filters.command("setsource") & filters.user(ADMIN_ID))
async def set_source(client, message):
    try:
        chat_id = int(message.command[1])
        await update_config("source_channel", chat_id)
        await message.reply_text(f"✅ Source Channel: `{chat_id}`")
    except: await message.reply_text("❌ Error.")

@app.on_message(filters.command("setpublic") & filters.user(ADMIN_ID))
async def set_public(client, message):
    try:
        chat_id = int(message.command[1])
        await update_config("public_channel", chat_id)
        await message.reply_text(f"✅ Public Channel: `{chat_id}`")
    except: await message.reply_text("❌ Error.")

@app.on_message(filters.command("setinterval") & filters.user(ADMIN_ID))
async def set_post_interval(client, message):
    try:
        seconds = int(message.command[1])
        await update_config("post_interval", seconds)
        await message.reply_text(f"🚀 **Posting Interval:** {seconds} seconds.")
    except: await message.reply_text("❌ Error.")

@app.on_message(filters.command("autodelete") & filters.user(ADMIN_ID))
async def set_autodelete(client, message):
    try:
        seconds = int(message.command[1])
        await update_config("auto_delete", seconds)
        await message.reply_text(f"✅ Auto Delete: {seconds}s")
    except: await message.reply_text("❌ Error.")

@app.on_message(filters.command("status") & filters.user(ADMIN_ID))
async def status(client, message):
    q_len = await queue_col.count_documents({})
    interval = CACHE.get("post_interval", 1800)
    
    txt = (
        f"📊 **SYSTEM STATUS**\n"
        f"------------------------\n"
        f"📥 Source: `{CACHE['source_channel']}`\n"
        f"📢 Public: `{CACHE['public_channel']}`\n"
        f"⏳ **Pending Videos:** `{q_len}`\n"
        f"⏱ **Next Post:** Every {interval}s\n"
        f"🗑 Auto Delete: {CACHE['auto_delete']}s\n"
        f"🔗 Tutorial: [Click Here]({CACHE['tutorial_url']})"
    )
    await message.reply_text(txt, disable_web_page_preview=True)

# ------------------- LOGIC -------------------

@app.on_message(filters.channel & filters.video)
async def incoming_video(client, message):
    if CACHE["source_channel"] and message.chat.id == int(CACHE["source_channel"]):
        video_data = {
            "msg_id": message.id,
            "caption": message.caption or "New Video",
            "file_id": message.video.file_id,
            "date": message.date
        }
        await queue_col.insert_one(video_data)
        print(f"📥 New Video Queued: {message.id}")

async def send_stored_file(client, message):
    try:
        if not CACHE["source_channel"]:
            return await message.reply_text("❌ Source Channel not set!")

        msg_id = int(message.command[1])
        file_msg = await client.get_messages(int(CACHE["source_channel"]), msg_id)
        
        if not file_msg or not file_msg.video:
            return await message.reply_text("❌ File deleted from source.")

        sent = await file_msg.copy(
            chat_id=message.chat.id,
            caption=f"🎥 **{file_msg.caption[:100]}...**\n\n⚠️ __This video will be auto-deleted!__",
            protect_content=CACHE["protect_content"]
        )

        if CACHE["auto_delete"] > 0:
            await message.reply_text(f"⏳ **Deleting in {CACHE['auto_delete']} seconds...**")
            await asyncio.sleep(CACHE["auto_delete"])
            await sent.delete()

    except Exception as e:
        print(f"Delivery Error: {e}")

async def post_scheduler():
    print("🔄 Scheduler Running...")
    while True:
        interval = CACHE.get("post_interval", 1800)
        
        try:
            if not CACHE["source_channel"] or not CACHE["public_channel"]:
                await asyncio.sleep(10)
                continue

            # ডাটাবেস থেকে সবথেকে পুরনো ভিডিওটি নেওয়া (FIFO)
            video_data = await queue_col.find_one(sort=[("date", 1)])
            
            if video_data:
                msg_id = video_data["msg_id"]
                try:
                    # ১. সোর্স থেকে ভিডিও রিট্রিভ করা
                    real_msg = await app.get_messages(int(CACHE["source_channel"]), msg_id)
                    
                    if not real_msg or not real_msg.video:
                        print(f"❌ Video {msg_id} not found. Deleting from DB.")
                        await queue_col.delete_one({"_id": video_data["_id"]})
                        continue

                    # ২. থাম্বনেইল প্রসেসিং (কোলাজ বানানোর জটিলতা বাদ দিয়ে বেস্ট কোয়ালিটি থাম্ব নেওয়া)
                    thumb_path = await app.download_media(real_msg.thumbs[0].file_id) if real_msg.thumbs else None

                    # ৩. লিংক তৈরি
                    bot_usr = (await app.get_me()).username
                    start_link = f"https://t.me/{bot_usr}?start={msg_id}"
                    final_link = await shorten_link(start_link)

                    # ৪. ক্যাপশন এবং বাটন সাজানো
                    caption = (
                        f"🎬 **{video_data['caption'][:200]}**\n\n"
                        f"🔗 **Download / Watch Full Video:**\n{final_link}\n\n"
                        f"👉 **Click the link above to watch!**"
                    )

                    buttons = InlineKeyboardMarkup([
                        [InlineKeyboardButton("📥 Watch / Download Video", url=final_link)],
                        [InlineKeyboardButton("❓ How to Download", url=CACHE["tutorial_url"])]
                    ])

                    # ৫. পাবলিক চ্যানেলে পোস্ট করা
                    dest_id = int(CACHE["public_channel"])
                    
                    if thumb_path:
                        await app.send_photo(dest_id, photo=thumb_path, caption=caption, reply_markup=buttons)
                        os.remove(thumb_path) # টেম্প ফাইল ডিলিট
                    else:
                        await app.send_message(dest_id, text=caption, reply_markup=buttons)

                    # ৬. সাকসেসফুল হলে কিউ থেকে ডিলিট
                    await queue_col.delete_one({"_id": video_data["_id"]})
                    print(f"✅ Successfully Posted: {msg_id}")

                except FloodWait as e:
                    print(f"⚠️ FloodWait: Sleeping for {e.value} seconds.")
                    await asyncio.sleep(e.value)
                    continue # কিউ ডিলিট হবে না, আবার চেষ্টা করবে
                
                except Exception as e:
                    # যদি অন্য কোনো মারাত্মক এরর হয়, তাহলে স্কিপ করা হবে যাতে লুপ না বাঁধে
                    print(f"❌ Error posting {msg_id}: {e}. Skipping...")
                    await queue_col.delete_one({"_id": video_data["_id"]})
            
            else:
                # কিউ খালি থাকলে
                pass

        except Exception as e:
            print(f"Scheduler Critical Error: {e}")

        # টাইমার অনুযায়ী অপেক্ষা
        await asyncio.sleep(interval)

# ------------------- RUNNER -------------------

async def main():
    await app.start()
    await load_config()
    print("🤖 Professional Bot Started!")
    asyncio.create_task(post_scheduler())
    await idle()
    await app.stop()

if __name__ == "__main__":
    app.run(main())
