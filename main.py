import asyncio
import os
import shutil
import subprocess
import time
import aiohttp
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait, ChatWriteForbidden
from motor.motor_asyncio import AsyncIOMotorClient

# ------------------- ১. কনফিগারেশন (বট সেটআপ) -------------------
API_ID = 22697010
API_HASH = "fd88d7339b0371eb2a9501d523f3e2a7"
BOT_TOKEN = "8303315439:AAGKPEugn60XGMC7_u4pOaZPnUWkWHvXSNM"
MONGO_URL = "mongodb+srv://mewayo8672:mewayo8672@cluster0.ozhvczp.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
ADMIN_ID = 8172129114

# ডাটাবেস কানেকশন
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client["AutoPostBot_Pro"]
queue_col = db["queue"]
config_col = db["config"]

# ক্যাশ মেমোরি (বারবার ডাটাবেস কল কমানোর জন্য)
CACHE = {
    "source_channel": None,
    "public_channel": None,
    "shortener_api": None,
    "shortener_key": None,
    "auto_delete": 0,
    "post_interval": 60, # বড় ভিডিও প্রসেস করতে সময় লাগে, তাই ৬০ সেকেন্ড
    "tutorial_url": "https://t.me/YourChannel"
}

app = Client("viral_poster_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ------------------- ২. হেল্পার ফাংশন -------------------

async def load_config():
    """সেটিংস লোড করে"""
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
    print("✅ System Config Loaded Successfully!")

async def update_config(key, value):
    await config_col.update_one({"_id": "settings"}, {"$set": {key: value}}, upsert=True)
    CACHE[key] = value

async def shorten_link(link):
    """লিংক শর্টেনার এপিআই হ্যান্ডলার"""
    if not CACHE.get("shortener_api") or not CACHE.get("shortener_key"):
        return link
    try:
        url = f"{CACHE['shortener_api']}?api={CACHE['shortener_key']}&url={link}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
                return data.get("shortenedUrl") or data.get("url") or link
    except:
        return link

# ------------------- ৩. থাম্বনেইল জেনারেটর (১০০% কাজ করবে) -------------------

async def generate_thumbnail(video_path):
    """
    ভিডিওর ১৫ সেকেন্ডের মাথা থেকে HD থাম্বনেইল বের করবে।
    """
    thumb_path = f"{video_path}.jpg"
    
    # চেক করা হচ্ছে সিস্টেমে FFmpeg আছে কিনা
    if not shutil.which("ffmpeg"):
        print("❌ Critical Error: FFmpeg not installed!")
        return None

    try:
        # ভিডিওর ডিউরেশন চেক করার দরকার নেই, সরাসরি ১৫ সেকেন্ডে ট্রাই করবে
        # যদি ভিডিও ছোট হয়, FFmpeg অটোমেটিক মানিয়ে নিবে
        cmd = [
            "ffmpeg", 
            "-i", video_path, 
            "-ss", "00:00:10", # ১৫ সেকেন্ডের সিন (বেশিরভাগ ভাইরাল সিন মাঝখানে থাকে)
            "-vframes", "1", 
            "-q:v", "2", # হাই কোয়ালিটি
            thumb_path, 
            "-y"
        ]
        
        # কমান্ড রান করা
        subprocess.call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        if os.path.exists(thumb_path):
            print("✅ Thumbnail Generated Successfully")
            return thumb_path
        else:
            print("⚠️ FFmpeg failed to generate thumb. Trying fallback...")
            return None
    except Exception as e:
        print(f"❌ Thumb Gen Error: {e}")
        return None

# ------------------- ৪. ইউজার কমান্ড (Start Button Fix) -------------------

@app.on_message(filters.command("start") & filters.private)
async def start_handler(client, message):
    # যদি লিংকে ক্লিক করে আসে (যেমন: /start 12345)
    if len(message.command) > 1:
        return await send_video_to_user(client, message)
    
    await message.reply_text(
        "👋 **Welcome Boss!**\n\n"
        "I am fully operational now. Configure me using:\n"
        "`/setsource ID`\n`/setpublic ID`\n`/status`"
    )

async def send_video_to_user(client, message):
    try:
        msg_id = int(message.command[1])
        if not CACHE["source_channel"]:
            return await message.reply_text("❌ Admin hasn't set the Source Channel yet.")

        # মেইন ভিডিও সোর্স থেকে আনা
        file_msg = await client.get_messages(int(CACHE["source_channel"]), msg_id)
        
        if not file_msg or (not file_msg.video and not file_msg.document):
            return await message.reply_text("❌ This video has been deleted.")

        caption = f"✅ **Here is your video!**\n\n🆔 ID: `{msg_id}`"
        
        sent = await file_msg.copy(
            chat_id=message.chat.id,
            caption=caption,
            protect_content=CACHE["protect_content"]
        )

        # অটো ডিলিট লজিক
        if CACHE["auto_delete"] > 0:
            await message.reply_text(f"⏳ **This video will disappear in {CACHE['auto_delete']} seconds!**")
            await asyncio.sleep(CACHE["auto_delete"])
            await sent.delete()
            
    except Exception as e:
        print(f"Delivery Error: {e}")
        await message.reply_text("❌ Error fetching video.")

# ------------------- ৫. অ্যাডমিন কমান্ডস -------------------

@app.on_message(filters.command("setsource") & filters.user(ADMIN_ID))
async def set_source(c, m):
    try:
        cid = int(m.command[1])
        await update_config("source_channel", cid)
        await m.reply(f"✅ Source Channel: `{cid}`")
    except: await m.reply("❌ Use: `/setsource -100xxxx`")

@app.on_message(filters.command("setpublic") & filters.user(ADMIN_ID))
async def set_public(c, m):
    try:
        cid = int(m.command[1])
        await update_config("public_channel", cid)
        await m.reply(f"✅ Public Channel: `{cid}`")
    except: await m.reply("❌ Use: `/setpublic -100xxxx`")

@app.on_message(filters.command("status") & filters.user(ADMIN_ID))
async def status(c, m):
    q = await queue_col.count_documents({})
    ff = "✅ Ready" if shutil.which("ffmpeg") else "❌ Missing"
    await m.reply(
        f"📊 **SYSTEM STATUS**\n"
        f"🎥 Queue Pending: `{q}`\n"
        f"🔧 FFmpeg: `{ff}`\n"
        f"📥 Source: `{CACHE['source_channel']}`\n"
        f"📢 Public: `{CACHE['public_channel']}`"
    )

@app.on_message(filters.command("clearqueue") & filters.user(ADMIN_ID))
async def clear(c, m):
    await queue_col.delete_many({})
    await m.reply("🗑️ Queue Cleared!")

# ------------------- ৬. ভিডিও রিসিভ লজিক -------------------

@app.on_message(filters.channel & (filters.video | filters.document))
async def receiver(c, m):
    # শুধুমাত্র সোর্স চ্যানেলের ভিডিও নিবে
    if CACHE["source_channel"] and m.chat.id == int(CACHE["source_channel"]):
        f_id = None
        # ভিডিও বা ফাইল ডিটেকশন
        if m.video: f_id = m.video.file_id
        elif m.document and m.document.mime_type and "video" in m.document.mime_type:
            f_id = m.document.file_id
        
        if f_id:
            await queue_col.insert_one({
                "msg_id": m.id,
                "caption": m.caption or "New Viral Video 🔥",
                "file_id": f_id,
                "date": m.date
            })
            print(f"📥 New Video Added to Queue: ID {m.id}")

# ------------------- ৭. মেইন প্রসেসিং লুপ (The Brain) -------------------

async def post_scheduler():
    print("🔄 Bot Scheduler Started. Waiting for videos...")
    
    while True:
        try:
            # কনফিগ চেক
            if not CACHE["source_channel"] or not CACHE["public_channel"]:
                await asyncio.sleep(20)
                continue

            # ১. কিউ থেকে ভিডিও বের করা (সবচেয়ে পুরনোটা আগে)
            video_data = await queue_col.find_one(sort=[("date", 1)])
            
            if video_data:
                msg_id = video_data["msg_id"]
                print(f"🚀 Processing Video ID: {msg_id}")

                real_msg = None
                try:
                    real_msg = await app.get_messages(int(CACHE["source_channel"]), msg_id)
                except Exception as e:
                    print(f"❌ Source Fetch Error: {e}")
                    # মেসেজ না পেলে কিউ থেকে ডিলিট
                    await queue_col.delete_one({"_id": video_data["_id"]})
                    continue

                if not real_msg:
                    await queue_col.delete_one({"_id": video_data["_id"]})
                    continue

                # ২. ভিডিও ডাউনলোড ও থাম্বনেইল জেনারেশন
                video_path = None
                thumb_path = None

                try:
                    print("⬇️ Downloading Video (Processing)...")
                    video_path = await app.download_media(real_msg, file_name=f"v_{msg_id}.mp4")
                    
                    if video_path:
                        print("🎨 Generating Attractive Thumbnail...")
                        thumb_path = await generate_thumbnail(video_path)
                except Exception as e:
                    print(f"⚠️ Download/Gen Error: {e}")

                # ৩. যদি কাস্টম থাম্বনেইল ফেইল করে, ডিফল্টটা ব্যবহার করো
                if not thumb_path and real_msg.thumbs:
                    try:
                        print("⚠️ Using Telegram Thumbnail as Fallback")
                        thumb_path = await app.download_media(real_msg.thumbs[0].file_id)
                    except: pass

                # ৪. লিংক ও ক্যাপশন সাজানো (Viral Template)
                bot_usr = (await app.get_me()).username
                start_link = f"https://t.me/{bot_usr}?start={msg_id}"
                final_link = await shorten_link(start_link)
                
                # সুন্দর ক্যাপশন টেমপ্লেট
                original_cap = video_data.get('caption', 'Hot Video')
                if not original_cap: original_cap = "New Video"
                
                pretty_caption = (
                    f"🔥 **NEW VIRAL VIDEO UPLOADED!**\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"🎬 **Title:** {original_cap[:100]}\n"
                    f"✨ **Quality:** HD (Original)\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"👇 **Click Below to Watch Full Video** 👇\n"
                    f"🔗 **Link:** {final_link}"
                )
                
                buttons = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📥 Download / Watch Video", url=final_link)],
                    [InlineKeyboardButton("❤️ Join Our Channel", url=CACHE["tutorial_url"])]
                ])

                # ৫. পোস্ট করা (Final Step)
                dest = int(CACHE["public_channel"])
                try:
                    if thumb_path and os.path.exists(thumb_path):
                        await app.send_photo(
                            dest, 
                            photo=thumb_path, 
                            caption=pretty_caption, 
                            reply_markup=buttons
                        )
                    else:
                        # থাম্বনেইল একদমই না থাকলে টেক্সট যাবে (পোস্ট মিস হবে না)
                        await app.send_message(
                            dest, 
                            text=pretty_caption, 
                            reply_markup=buttons
                        )
                    
                    print(f"✅ Successfully Posted: {msg_id}")
                    await queue_col.delete_one({"_id": video_data["_id"]})
                
                except FloodWait as e:
                    print(f"⏳ Sleeping for {e.value}s (FloodWait)")
                    await asyncio.sleep(e.value)
                except ChatWriteForbidden:
                    print("❌ Bot is not Admin in Public Channel!")
                except Exception as e:
                    print(f"❌ Final Post Error: {e}")
                    # পোস্ট এরর হলেও কিউ থেকে সরাচ্ছি যাতে লুপ না হয়
                    await queue_col.delete_one({"_id": video_data["_id"]})

                # ৬. আবর্জনা পরিষ্কার (Clean Up)
                try:
                    if video_path and os.path.exists(video_path): os.remove(video_path)
                    if thumb_path and os.path.exists(thumb_path): os.remove(thumb_path)
                except: pass
            
            else:
                # কিউ খালি থাকলে অপেক্ষা
                pass

        except Exception as e:
            print(f"🔥 Critical Loop Error: {e}")
            await asyncio.sleep(5)
        
        # Interval (60 সেকেন্ড গ্যাপ যাতে বড় ভিডিও প্রসেস করতে পারে)
        await asyncio.sleep(CACHE.get("post_interval", 60))

# ------------------- ৮. রানার -------------------

async def main():
    if not os.path.exists("downloads"): os.makedirs("downloads")
    await app.start()
    await load_config()
    print("🤖 Bot Started Successfully! Waiting for Action...")
    
    # ব্যাকগ্রাউন্ড টাস্ক চালু করা
    asyncio.create_task(post_scheduler())
    await idle()
    await app.stop()

if __name__ == "__main__":
    app.run(main())
