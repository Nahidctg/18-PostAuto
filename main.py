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
from pyrogram.errors import FloodWait, MessageNotModified
from motor.motor_asyncio import AsyncIOMotorClient
from aiohttp import web
import cv2  # ভিডিও প্রসেসিং লাইব্রেরি (No FFmpeg needed)

# ------------------- ১. সিস্টেম ও একাউন্ট কনফিগারেশন -------------------
API_ID = 22697010
API_HASH = "fd88d7339b0371eb2a9501d523f3e2a7"
BOT_TOKEN = "8303315439:AAGKPEugn60XGMC7_u4pOaZPnUWkWHvXSNM"
MONGO_URL = "mongodb+srv://mewayo8672:mewayo8672@cluster0.ozhvczp.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
ADMIN_ID = 8172129114  # আপনার টেলিগ্রাম অ্যাডমিন আইডি

# ডাটাবেস কানেকশন সেটআপ
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client["AutoPost_Pro_v2"]
queue_col = db["queue"]      # পেন্ডিং ভিডিওর লিস্ট
config_col = db["config"]    # সেটিংস সেভ রাখার জন্য

# গ্লোবাল ভেরিয়েবল (মেমোরিতে রাখার জন্য)
CONFIG = {
    "source_channel": None,
    "public_channel": None,
    "caption_template": "🎬 **{caption}**\n\n✨ **Quality:** HD 720p\n🔥 **Exclusive Content**\n\n👇 **Click Button to Watch Full Video** 👇"
}

# পাইরোগ্রাম ক্লায়েন্ট সেটআপ
app = Client(
    "OpenCV_Bot_Pro", 
    api_id=API_ID, 
    api_hash=API_HASH, 
    bot_token=BOT_TOKEN
)

# ------------------- ২. ওয়েব সার্ভার (বট যাতে স্লিপ মোডে না যায়) -------------------
async def web_server():
    async def handle(request):
        return web.Response(text="✅ Bot is Running Smoothly!")

    web_app = web.Application()
    web_app.add_routes([web.get('/', handle)])
    runner = web.AppRunner(web_app)
    await runner.setup()
    # সার্ভারের পোর্ট ডিটেক্ট করা (ডিফল্ট 8080)
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"🌍 Web Server Started on Port {port}")

# ------------------- ৩. সেটিংস লোড ও সেভ ফাংশন -------------------
async def load_config():
    """বট চালু হওয়ার সময় ডাটাবেস থেকে সেটিংস লোড করবে"""
    try:
        data = await config_col.find_one({"_id": "settings"})
        if not data:
            # ডিফল্ট সেটিংস তৈরি
            default_data = {"_id": "settings", "source": None, "public": None}
            await config_col.insert_one(default_data)
            data = default_data
        
        CONFIG["source_channel"] = data.get("source")
        CONFIG["public_channel"] = data.get("public")
        
        print(f"⚙️ Config Loaded:\n   Source Channel: {CONFIG['source_channel']}\n   Public Channel: {CONFIG['public_channel']}")
    except Exception as e:
        print(f"❌ Config Loading Error: {e}")

async def save_config(key, value):
    """সেটিংস আপডেট করে ডাটাবেসে সেভ করবে"""
    await config_col.update_one({"_id": "settings"}, {"$set": {key: value}}, upsert=True)
    if key == "source": CONFIG["source_channel"] = value
    if key == "public": CONFIG["public_channel"] = value

# ------------------- ৪. থাম্বনেইল জেনারেটর (OpenCV ম্যাজিক) -------------------
def generate_thumbnail_cv2(video_path, msg_id):
    """
    FFmpeg ছাড়া সরাসরি পাইথন দিয়ে ভিডিও থেকে ছবি বের করবে।
    """
    thumb_path = f"downloads/thumb_{msg_id}.jpg"
    
    try:
        # ভিডিও ফাইল রিড করা
        video_capture = cv2.VideoCapture(video_path)
        
        if not video_capture.isOpened():
            print("❌ OpenCV Error: Could not open video file.")
            return None

        # ভিডিওর ডিউরেশন বের করা
        fps = video_capture.get(cv2.CAP_PROP_FPS)
        total_frames = int(video_capture.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if fps > 0 else 0
        
        # কোন সময় থেকে ছবি নিবে? (ডিফল্ট ১০ সেকেন্ড, ভিডিও ছোট হলে মাঝখান থেকে)
        target_timestamp = 10
        if duration < 15:
            target_timestamp = duration / 2

        # নির্দিষ্ট ফ্রেমে জাম্প করা
        target_frame = int(target_timestamp * fps)
        video_capture.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        
        # ছবি ক্যাপচার করা
        success, frame = video_capture.read()
        
        if success:
            # ইমেজ সেভ করা (Quality 90%)
            cv2.imwrite(thumb_path, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
            video_capture.release()
            print(f"✅ Thumbnail Generated via OpenCV: {thumb_path}")
            return thumb_path
        else:
            print("⚠️ Failed to extract frame.")
            video_capture.release()
            return None

    except Exception as e:
        print(f"❌ Thumbnail Generation Error: {e}")
        return None

# ------------------- ৫. ইউজার কমান্ড ও ডেলিভারি হ্যান্ডলার -------------------

@app.on_message(filters.command("start"))
async def start_handler(client, message):
    # যদি লিংকের সাথে কোনো প্যারামিটার থাকে (যেমন: /start 12345)
    if len(message.command) > 1:
        return await deliver_video(client, message)
    
    # সাধারণ ওয়েলকাম মেসেজ
    if message.from_user.id == ADMIN_ID:
        await message.reply_text(
            "👑 **Admin Control Panel**\n\n"
            "1️⃣ `/setsource -100xxxx` - সেট সোর্স চ্যানেল\n"
            "2️⃣ `/setpublic -100xxxx` - সেট পাবলিক চ্যানেল\n"
            "3️⃣ `/status` - সিস্টেম স্ট্যাটাস\n"
            "4️⃣ `/clearqueue` - পেন্ডিং লিস্ট ডিলিট"
        )
    else:
        await message.reply_text(
            "👋 **Welcome!**\n\n"
            "I am a video delivery bot.\n"
            "Please join our main channel to get video links."
        )

async def deliver_video(client, message):
    """ইউজারকে ভিডিও পৌঁছে দেওয়ার ফাংশন"""
    try:
        # প্যারামিটার থেকে মেসেজ আইডি বের করা
        msg_id_str = message.command[1]
        msg_id = int(msg_id_str)

        if not CONFIG["source_channel"]:
            return await message.reply("❌ System Error: Source Channel Not Configured.")

        status_msg = await message.reply("🔄 **Processing your request...**")

        # সোর্স চ্যানেল থেকে ভিডিও আনা
        original_msg = await client.get_messages(int(CONFIG["source_channel"]), msg_id)
        
        if not original_msg or (not original_msg.video and not original_msg.document):
            return await status_msg.edit("❌ **Video Not Found!**\nMaybe it was deleted from the server.")

        # কপি করে ইউজারকে পাঠানো
        caption = "✅ **Here is your requested video!**\n\n🔥 **Join our Backup Channel for more!**"
        await original_msg.copy(
            chat_id=message.chat.id,
            caption=caption,
            protect_content=True  # ফরোয়ার্ড বন্ধ রাখা (অপশনাল)
        )
        await status_msg.delete()

    except Exception as e:
        print(f"Delivery Error: {e}")
        await message.reply("❌ An error occurred while fetching the video.")

# ------------------- ৬. অ্যাডমিন কমান্ডস -------------------

@app.on_message(filters.command("setsource") & filters.user(ADMIN_ID))
async def set_source_channel(c, m):
    try:
        channel_id = int(m.command[1])
        await save_config("source", channel_id)
        await m.reply(f"✅ **Source Channel Set Successfully!**\n🆔 ID: `{channel_id}`")
    except:
        await m.reply("❌ **Error!**\nUsage: `/setsource -100123456789`")

@app.on_message(filters.command("setpublic") & filters.user(ADMIN_ID))
async def set_public_channel(c, m):
    try:
        channel_id = int(m.command[1])
        await save_config("public", channel_id)
        await m.reply(f"✅ **Public Channel Set Successfully!**\n🆔 ID: `{channel_id}`")
    except:
        await m.reply("❌ **Error!**\nUsage: `/setpublic -100123456789`")

@app.on_message(filters.command("status") & filters.user(ADMIN_ID))
async def check_status(c, m):
    queue_count = await queue_col.count_documents({})
    
    status_text = (
        f"📊 **SYSTEM STATUS**\n\n"
        f"📥 **Pending Videos:** `{queue_count}`\n"
        f"📂 **Source Channel:** `{CONFIG['source_channel']}`\n"
        f"📢 **Public Channel:** `{CONFIG['public_channel']}`\n"
        f"🖼 **Thumbnail Engine:** `OpenCV (Active)`"
    )
    await m.reply(status_text)

@app.on_message(filters.command("clearqueue") & filters.user(ADMIN_ID))
async def clear_queue_data(c, m):
    await queue_col.delete_many({})
    await m.reply("🗑️ **Queue Cleared Successfully!**")

# ------------------- ৭. ভিডিও ডিটেকশন (Listener) -------------------

@app.on_message(filters.channel & (filters.video | filters.document))
async def incoming_video_watcher(client, message):
    # শুধুমাত্র সোর্স চ্যানেলের মেসেজ দেখবে
    if CONFIG["source_channel"] and message.chat.id == int(CONFIG["source_channel"]):
        
        # ফাইলটি ভিডিও কিনা চেক করা
        is_video = message.video or (message.document and message.document.mime_type and "video" in message.document.mime_type)
        
        if is_video:
            # ডাটাবেসে ডুপ্লিকেট চেক
            existing = await queue_col.find_one({"msg_id": message.id})
            if not existing:
                # নতুন ভিডিও কিউতে যুক্ত করা
                await queue_col.insert_one({
                    "msg_id": message.id,
                    "caption": message.caption or "New Exclusive Video",
                    "date": message.date
                })
                print(f"📥 New Video Detected & Queued: ID {message.id}")

# ------------------- ৮. অটোমেশন প্রসেসর (Main Engine) -------------------

async def post_processing_engine():
    print("🚀 Auto Post Engine Started...")
    
    # ডাউনলোড ফোল্ডার তৈরি
    if not os.path.exists("downloads"):
        os.makedirs("downloads")

    while True:
        try:
            # কনফিগারেশন চেক
            if not CONFIG["source_channel"] or not CONFIG["public_channel"]:
                print("⚠️ Channels not set. Waiting 20s...")
                await asyncio.sleep(20)
                continue

            # ১. কিউ থেকে সবচেয়ে পুরনো ভিডিও নেওয়া
            task = await queue_col.find_one(sort=[("date", 1)])
            
            if task:
                msg_id = task["msg_id"]
                print(f"🔨 Processing Task ID: {msg_id}")

                try:
                    # ২. সোর্স থেকে ভিডিও ডাউনলোড করা
                    message = await app.get_messages(int(CONFIG["source_channel"]), msg_id)
                    
                    if not message or (not message.video and not message.document):
                        print("❌ Message missing in source. Skipping.")
                        await queue_col.delete_one({"_id": task["_id"]})
                        continue

                    print("⬇️ Downloading Video...")
                    video_path = f"downloads/video_{msg_id}.mp4"
                    downloaded_file = await app.download_media(message, file_name=video_path)
                    
                    if not downloaded_file:
                        raise Exception("Download Failed")

                    # ৩. থাম্বনেইল জেনারেট (OpenCV দিয়ে)
                    print("🎨 Generating Thumbnail...")
                    thumb_path = generate_thumbnail_cv2(video_path, msg_id)

                    # ৪. ক্যাপশন এবং বাটন তৈরি
                    bot_username = (await app.get_me()).username
                    deep_link = f"https://t.me/{bot_username}?start={msg_id}"
                    
                    raw_caption = task.get("caption", "Video")[:100] # ক্যাপশন বেশি বড় হলে কেটে ছোট করা
                    final_caption = CONFIG["caption_template"].format(caption=raw_caption)

                    buttons = InlineKeyboardMarkup([
                        [InlineKeyboardButton("📥 DOWNLOAD / WATCH VIDEO 📥", url=deep_link)],
                        [InlineKeyboardButton("🔗 Join Main Channel", url="https://t.me/YourChannel")]
                    ])

                    dest_chat = int(CONFIG["public_channel"])

                    # ৫. পাবলিক চ্যানেলে পোস্ট পাঠানো (শুধুমাত্র ফটো + বাটন)
                    if thumb_path and os.path.exists(thumb_path):
                        await app.send_photo(
                            chat_id=dest_chat,
                            photo=thumb_path,
                            caption=final_caption,
                            reply_markup=buttons
                        )
                        print(f"✅ Posted Successfully with Thumbnail: {msg_id}")
                    else:
                        # যদি কোনো কারণে থাম্বনেইল না হয়, টেক্সট মেসেজ পাঠানো
                        print("⚠️ Thumbnail failed. Sending Text Message.")
                        await app.send_message(
                            chat_id=dest_chat,
                            text=final_caption + "\n\n⚠️ *Preview Not Available*",
                            reply_markup=buttons
                        )

                    # ৬. টাস্ক কমপ্লিট - কিউ থেকে ডিলিট
                    await queue_col.delete_one({"_id": task["_id"]})

                    # ৭. ফাইল ক্লিনআপ (স্টোরেজ বাঁচানোর জন্য)
                    if os.path.exists(video_path): os.remove(video_path)
                    if thumb_path and os.path.exists(thumb_path): os.remove(thumb_path)

                except FloodWait as e:
                    print(f"⏳ FloodWait: Sleeping for {e.value} seconds.")
                    await asyncio.sleep(e.value)
                except Exception as e:
                    print(f"❌ Processing Error: {e}")
                    # এরর হলেও কিউ থেকে ডিলিট করা হবে যাতে লুপে আটকে না থাকে
                    await queue_col.delete_one({"_id": task["_id"]})
                    # ক্লিনআপ
                    try:
                        if os.path.exists(video_path): os.remove(video_path)
                        if thumb_path and os.path.exists(thumb_path): os.remove(thumb_path)
                    except: pass
            
            else:
                # কিউ খালি থাকলে
                pass

            # পোস্টিং ইন্টারভাল (৩০ সেকেন্ড পর পর চেক করবে)
            await asyncio.sleep(30)

        except Exception as e:
            print(f"🛑 Critical Engine Loop Error: {e}")
            await asyncio.sleep(10)

# ------------------- ৯. মেইন এক্সিকিউশন পয়েন্ট -------------------

async def main():
    # ওয়েব সার্ভার চালু (ব্যাকগ্রাউন্ডে)
    server = asyncio.create_task(web_server())
    
    # বট চালু
    await app.start()
    
    # কনফিগারেশন লোড
    await load_config()
    
    print("🤖 -------------------------------------------")
    print("🤖 Auto Video Bot (Pro OpenCV Version) Started!")
    print("🤖 -------------------------------------------")
    
    # প্রসেসিং ইঞ্জিন চালু (ব্যাকগ্রাউন্ডে)
    engine = asyncio.create_task(post_processing_engine())
    
    # বটকে আইডল রাখা
    await idle()
    
    # বন্ধ করার সময়
    await app.stop()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        pass
