import asyncio
import os
import shutil
import subprocess
import time
from pyrogram import Client, filters, idle
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, 
    InputMediaPhoto
)
from pyrogram.errors import FloodWait, ChatWriteForbidden
from motor.motor_asyncio import AsyncIOMotorClient

# ------------------- ১. সিস্টেম কনফিগারেশন -------------------
API_ID = 22697010
API_HASH = "fd88d7339b0371eb2a9501d523f3e2a7"
BOT_TOKEN = "8303315439:AAGKPEugn60XGMC7_u4pOaZPnUWkWHvXSNM"
MONGO_URL = "mongodb+srv://mewayo8672:mewayo8672@cluster0.ozhvczp.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
ADMIN_ID = 8172129114

# ডাটাবেস সেটআপ
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client["AutoVideoBot_Pro"]
queue_col = db["queue"]
config_col = db["config"]

# ক্যাশ মেমোরি
CACHE = {
    "source_channel": None,
    "public_channel": None,
    "auto_delete": 0,          # 0 মানে অফ
    "post_interval": 60,       # ডিফল্ট ৬০ সেকেন্ড
    "caption_template": "🔥 **NEW VIDEO UPLOADED** 🔥\n\n🎬 **Title:** {caption}\n📺 **Quality:** HD Streaming",
    "tutorial_url": "https://t.me/YourChannel"
}

app = Client("project_video_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ------------------- ২. হেল্পার ফাংশন -------------------

async def load_config():
    """ডাটাবেস থেকে সেটিংস লোড করা"""
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
    print("✅ System Config Loaded")

async def update_config(key, value):
    await config_col.update_one({"_id": "settings"}, {"$set": {key: value}}, upsert=True)
    CACHE[key] = value

# ------------------- ৩. থাম্বনেইল প্রসেসিং (FFmpeg) -------------------

async def generate_thumbnails(video_path):
    """
    ভিডিও থেকে ৩টি স্ক্রিনশট নিবে (Start, Middle, End দিকে)
    """
    if not shutil.which("ffmpeg"):
        print("❌ FFmpeg not found!")
        return []

    thumbs = []
    # ৫ সেকেন্ড, ১৫ সেকেন্ড এবং ৩০ সেকেন্ডের মাথা থেকে স্ন্যাপশট
    timestamps = ["00:00:05", "00:00:15", "00:00:30"]
    
    for i, t in enumerate(timestamps):
        out_file = f"{video_path}_thumb_{i}.jpg"
        try:
            # -ss (seek), -vframes 1 (একটাই ছবি)
            subprocess.call([
                "ffmpeg", "-ss", t, "-i", video_path,
                "-vframes", "1", "-q:v", "2", out_file, "-y"
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            if os.path.exists(out_file):
                thumbs.append(out_file)
        except Exception as e:
            print(f"Thumb Gen Error: {e}")
            
    return thumbs

# ------------------- ৪. ইউজার ডেলিভারি সিস্টেম (/start) -------------------

@app.on_message(filters.command("start") & filters.private)
async def start_delivery(client, message):
    # যদি ডিপ লিংক থাকে (যেমন: /start 12345)
    if len(message.command) > 1:
        return await send_video_to_user(client, message)
    
    await message.reply_text(
        "👋 **Welcome to Auto Video Bot!**\n\n"
        "This bot delivers videos from the channel.\n"
        "Only Admins can control me."
    )

async def send_video_to_user(client, message):
    try:
        msg_id = int(message.command[1])
        if not CACHE["source_channel"]:
            return await message.reply("❌ Source Channel Not Configured.")
        
        # সোর্স থেকে ভিডিও কপি করা
        file_msg = await client.get_messages(int(CACHE["source_channel"]), msg_id)
        
        if not file_msg or (not file_msg.video and not file_msg.document):
            return await message.reply("❌ Video not found (maybe deleted).")

        caption = f"✅ **Here is your requested video!**\n🆔 ID: `{msg_id}`"
        
        # ইউজারকে পাঠানো
        sent = await file_msg.copy(
            chat_id=message.chat.id,
            caption=caption,
            protect_content=True # ফরোয়ার্ড রেস্ট্রিকশন (অপশনাল)
        )

        # অটো ডিলিট ফিচার
        if CACHE["auto_delete"] > 0:
            await message.reply(f"⏳ This video will be auto-deleted in {CACHE['auto_delete']} seconds.")
            await asyncio.sleep(CACHE["auto_delete"])
            await sent.delete()
            
    except Exception as e:
        print(f"Delivery Error: {e}")
        await message.reply("❌ Error fetching video.")

# ------------------- ৫. অ্যাডমিন কন্ট্রোল প্যানেল -------------------

@app.on_message(filters.command("setsource") & filters.user(ADMIN_ID))
async def set_src(c, m):
    try:
        cid = int(m.command[1])
        await update_config("source_channel", cid)
        await m.reply(f"✅ Source Channel Set: `{cid}`")
    except: await m.reply("Usage: `/setsource -100xxxx`")

@app.on_message(filters.command("setpublic") & filters.user(ADMIN_ID))
async def set_pub(c, m):
    try:
        cid = int(m.command[1])
        await update_config("public_channel", cid)
        await m.reply(f"✅ Public Channel Set: `{cid}`")
    except: await m.reply("Usage: `/setpublic -100xxxx`")

@app.on_message(filters.command("status") & filters.user(ADMIN_ID))
async def sys_status(c, m):
    q = await queue_col.count_documents({})
    await m.reply(
        f"📊 **SYSTEM STATUS**\n"
        f"📥 Queue Pending: `{q}`\n"
        f"⏱ Interval: `{CACHE['post_interval']}s`\n"
        f"📂 Source: `{CACHE['source_channel']}`\n"
        f"📢 Public: `{CACHE['public_channel']}`"
    )

@app.on_message(filters.command("clearqueue") & filters.user(ADMIN_ID))
async def clear_q(c, m):
    await queue_col.delete_many({})
    await m.reply("🗑️ Queue Cleared Successfully!")

# ------------------- ৬. ভিডিও ডিটেকশন (Listener) -------------------

@app.on_message(filters.channel & (filters.video | filters.document))
async def queue_manager(c, m):
    # শুধুমাত্র সোর্স চ্যানেলের ভিডিও মনিটর করবে
    if CACHE["source_channel"] and m.chat.id == int(CACHE["source_channel"]):
        # ভিডিও ফাইল কিনা চেক
        is_video = m.video or (m.document and m.document.mime_type and "video" in m.document.mime_type)
        
        if is_video:
            await queue_col.insert_one({
                "msg_id": m.id,
                "caption": m.caption or "Untitled Video",
                "date": m.date
            })
            print(f"📥 New Video Queued: ID {m.id}")

# ------------------- ৭. অটো পোস্ট শিডিউলার (Main Engine) -------------------

async def post_processor():
    print("🔄 Automation Engine Started...")
    
    while True:
        try:
            # কনফিগারেশন চেক
            if not CACHE["source_channel"] or not CACHE["public_channel"]:
                await asyncio.sleep(10); continue

            # ১. কিউ থেকে ডাটা নেওয়া
            task = await queue_col.find_one(sort=[("date", 1)])
            
            if task:
                msg_id = task["msg_id"]
                print(f"🚀 Processing Task: {msg_id}")

                real_msg = None
                try:
                    real_msg = await app.get_messages(int(CACHE["source_channel"]), msg_id)
                except: pass

                if not real_msg:
                    print("❌ Message missing in source.")
                    await queue_col.delete_one({"_id": task["_id"]}); continue

                # ২. ভিডিও ডাউনলোড ও থাম্বনেইল জেনারেশন
                video_path = None
                thumbs = []
                
                try:
                    print("⬇️ Downloading Video for processing...")
                    video_path = await app.download_media(real_msg, file_name=f"temp_{msg_id}.mp4")
                    
                    if video_path:
                        print("🎨 Generating Album Thumbnails...")
                        thumbs = await generate_thumbnails(video_path)
                except Exception as e:
                    print(f"Download/Process Error: {e}")

                # ৩. লিংক ও ক্যাপশন তৈরি
                bot_username = (await app.get_me()).username
                deep_link = f"https://t.me/{bot_username}?start={msg_id}"
                
                # সুন্দর ক্যাপশন টেমপ্লেট
                raw_caption = task.get('caption', 'Video')
                final_caption = CACHE["caption_template"].format(caption=raw_caption[:100])
                final_caption += f"\n\n👇 **Click Below to Watch Full Video** 👇"

                buttons = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📥 Download / Watch Video", url=deep_link)],
                    [InlineKeyboardButton("❤️ Join Our Channel", url=CACHE["tutorial_url"])]
                ])

                # ৪. পাবলিক চ্যানেলে পোস্ট করা (Album + Message)
                dest = int(CACHE["public_channel"])
                try:
                    # A. যদি থাম্বনেইল জেনারেট হয়, তাহলে অ্যালবাম পাঠাবো
                    if thumbs and len(thumbs) >= 2:
                        media_group = [InputMediaPhoto(t) for t in thumbs]
                        await app.send_media_group(dest, media=media_group)
                        
                        # অ্যালবামের নিচে বাটন সহ মেসেজ
                        await app.send_message(dest, text=final_caption, reply_markup=buttons)
                    
                    # B. যদি থাম্বনেইল না হয় (ব্যাকআপ), তাহলে নরমাল ফটো/মেসেজ
                    else:
                        print("⚠️ Sending Standard Post (No Album)")
                        # টেলিগ্রামের অরিজিনাল থাম্বনেইল ট্রাই করা
                        t_path = None
                        if real_msg.thumbs:
                            t_path = await app.download_media(real_msg.thumbs[0].file_id)
                        
                        if t_path:
                            await app.send_photo(dest, t_path, caption=final_caption, reply_markup=buttons)
                            os.remove(t_path)
                        else:
                            await app.send_message(dest, text=final_caption, reply_markup=buttons)

                    print(f"✅ Posted Successfully: {msg_id}")
                    await queue_col.delete_one({"_id": task["_id"]})

                except FloodWait as e:
                    print(f"⏳ Sleeping {e.value}s (FloodWait)")
                    await asyncio.sleep(e.value)
                except Exception as e:
                    print(f"❌ Post Failed: {e}")
                    await queue_col.delete_one({"_id": task["_id"]})

                # ৫. ফাইল ক্লিনআপ (স্টোরেজ বাঁচানোর জন্য)
                try:
                    if video_path and os.path.exists(video_path): os.remove(video_path)
                    for t in thumbs:
                        if os.path.exists(t): os.remove(t)
                except: pass

            else:
                # কিউ খালি থাকলে
                pass

        except Exception as e:
            print(f"Critical Engine Error: {e}")
            await asyncio.sleep(5)
        
        # পোস্ট ইন্টারভাল
        await asyncio.sleep(CACHE.get("post_interval", 60))

# ------------------- ৮. রানার -------------------

async def main():
    # ডাউনলোড ফোল্ডার তৈরি
    if not os.path.exists("downloads"): os.makedirs("downloads")
    
    await app.start()
    await load_config()
    print("🤖 Auto Video Poster & Delivery Bot STARTED!")
    
    # ব্যাকগ্রাউন্ড টাস্ক চালু করা
    asyncio.create_task(post_processor())
    await idle()
    await app.stop()

if __name__ == "__main__":
    app.run(main())
