import asyncio
import logging
import aiohttp
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait
from motor.motor_asyncio import AsyncIOMotorClient

# ------------------- CONFIGURATION -------------------
# আপনার তথ্যগুলো এখানে বসান
API_ID = 1234567  # আপনার API ID
API_HASH = "your_api_hash_here"
BOT_TOKEN = "your_bot_token_here"
MONGO_URL = "your_mongodb_connection_string"
SOURCE_CHANNEL = -1001234567890  # প্রাইভেট চ্যানেলের ID
PUBLIC_CHANNEL = -1009876543210  # পাবলিক চ্যানেলের ID
ADMIN_ID = 123456789  # আপনার নিজের টেলিগ্রাম ID

# ------------------- DATABASE CONNECTION -------------------
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client["AutoPostBot"]
queue_col = db["video_queue"]  # ভিডিও কিউ বা লাইন
config_col = db["config"]      # সেটিংস স্টোর

# ডিফল্ট সেটিংস
DEFAULT_CONFIG = {
    "_id": "settings",
    "shortener_api": "",   # শর্টনার API URL
    "shortener_key": "",   # শর্টনার API Key
    "auto_delete": 0,      # 0 মানে অফ, অন্যথায় সেকেন্ড
    "protect_content": False, # ফরোয়ার্ড রেস্ট্রিকশন
    "caption_text": "🎬 **Watch the full video!**"
}

app = Client("smart_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ------------------- HELPER FUNCTIONS -------------------

# সেটিংস লোড করা
async def get_config():
    conf = await config_col.find_one({"_id": "settings"})
    if not conf:
        await config_col.insert_one(DEFAULT_CONFIG)
        return DEFAULT_CONFIG
    return conf

# সেটিংস আপডেট করা
async def update_config(key, value):
    await config_col.update_one({"_id": "settings"}, {"$set": {key: value}}, upsert=True)

# লিংক শর্ট করা
async def shorten_link(link):
    conf = await get_config()
    api_url = conf.get("shortener_api")
    api_key = conf.get("shortener_key")

    if not api_url or not api_key:
        return link  # শর্টনার সেট না থাকলে আসল লিংকই দেবে

    try:
        # সাপোর্ট করবে: ?api={key}&url={link} ফরম্যাট
        full_url = f"{api_url}?api={api_key}&url={link}"
        async with aiohttp.ClientSession() as session:
            async with session.get(full_url) as resp:
                data = await resp.json()
                # শর্টনার ভেদে রেস্পন্স আলাদা হতে পারে (ShortUrl/shortenedUrl)
                return data.get("shortenedUrl") or data.get("url") or link
    except Exception as e:
        print(f"Shortener Error: {e}")
        return link

# ------------------- ADMIN COMMANDS -------------------

@app.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    # যদি লিংকে কোনো প্যারামিটার থাকে (ফাইল এক্সেস করার জন্য)
    if len(message.command) > 1:
        return await send_stored_file(client, message)
    
    await message.reply_text(
        "👋 **স্বাগতম!** আমি অটো পোস্টিং এবং ফাইল স্টোর বট।\n\n"
        "শুধু এডমিন আমাকে নিয়ন্ত্রণ করতে পারবে।"
    )

@app.on_message(filters.command("setshortener") & filters.user(ADMIN_ID))
async def set_shortener(client, message):
    # ব্যবহার: /setshortener https://api.gplinks.com/api api_key_here
    try:
        _, url, key = message.text.split(" ")
        await update_config("shortener_api", url)
        await update_config("shortener_key", key)
        await message.reply_text("✅ **লিংক শর্টনার সফলভাবে সেট করা হয়েছে!**")
    except ValueError:
        await message.reply_text("❌ ভুল ফরম্যাট। লিখুন:\n`/setshortener API_URL API_KEY`")

@app.on_message(filters.command("autodelete") & filters.user(ADMIN_ID))
async def set_autodelete(client, message):
    # ব্যবহার: /autodelete 600 (সেকেন্ডে) অথবা 0 বন্ধ করতে
    try:
        seconds = int(message.command[1])
        await update_config("auto_delete", seconds)
        status = f"{seconds} সেকেন্ড" if seconds > 0 else "OFF"
        await message.reply_text(f"✅ **অটো ডিলিট টাইমার সেট করা হয়েছে:** {status}")
    except:
        await message.reply_text("❌ ভুল। লিখুন: `/autodelete 600` (১০ মিনিট)")

@app.on_message(filters.command("protect") & filters.user(ADMIN_ID))
async def toggle_protect(client, message):
    # ব্যবহার: /protect on অথবা /protect off
    try:
        state = message.command[1].lower()
        if state == "on":
            await update_config("protect_content", True)
            await message.reply_text("🔒 **ফরোয়ার্ড প্রটেকশন চালু করা হয়েছে।**")
        elif state == "off":
            await update_config("protect_content", False)
            await message.reply_text("🔓 **ফরোয়ার্ড প্রটেকশন বন্ধ করা হয়েছে।**")
    except:
        await message.reply_text("❌ লিখুন: `/protect on` অথবা `/protect off`")

@app.on_message(filters.command("status") & filters.user(ADMIN_ID))
async def check_status(client, message):
    queue_count = await queue_col.count_documents({})
    conf = await get_config()
    text = (
        f"📊 **System Status**\n"
        f"📥 Queue Size: {queue_count} Videos\n"
        f"🔗 Shortener: {'Active' if conf['shortener_api'] else 'Not Set'}\n"
        f"🗑 Auto Delete: {conf['auto_delete']}s\n"
        f"🔒 Protect: {conf['protect_content']}"
    )
    await message.reply_text(text)

# ------------------- SOURCE CHANNEL LISTENER -------------------

@app.on_message(filters.chat(SOURCE_CHANNEL) & filters.video)
async def incoming_video(client, message):
    # সোর্স চ্যানেল থেকে ভিডিও আসলে ডাটাবেসে সেভ হবে
    video_data = {
        "msg_id": message.id,
        "caption": message.caption or "New Video",
        "file_id": message.video.file_id,
        "date": message.date
    }
    await queue_col.insert_one(video_data)
    # কনসোলে প্রিন্ট (ডিবাগিংয়ের জন্য)
    print(f"New video added to DB Queue: {message.id}")

# ------------------- PUBLIC POSTER & FILE SENDER -------------------

# ১. ফাইল সেন্ডার (যখন ইউজার লিংকে ক্লিক করবে)
async def send_stored_file(client, message):
    try:
        # কমান্ড থেকে ম্যাসেজ আইডি বের করা (start=msg_id)
        msg_id = int(message.command[1])
        
        # সোর্স চ্যানেল থেকে ভিডিওটি কপি করে আনা
        file_msg = await client.get_messages(SOURCE_CHANNEL, msg_id)
        if not file_msg or not file_msg.video:
            return await message.reply_text("❌ ফাইলটি পাওয়া যাচ্ছে না বা ডিলিট হয়েছে।")

        conf = await get_config()
        
        # ফাইল পাঠানো
        sent_msg = await file_msg.copy(
            chat_id=message.chat.id,
            caption=f"🎥 **{file_msg.caption[:50]}...**",
            protect_content=conf["protect_content"] # ফরওয়ার্ড অন/অফ
        )

        # অটো ডিলিট লজিক
        if conf["auto_delete"] > 0:
            await message.reply_text(f"⚠️ এই ভিডিওটি {conf['auto_delete']} সেকেন্ড পর ডিলিট হয়ে যাবে।")
            await asyncio.sleep(conf["auto_delete"])
            await sent_msg.delete()
            
    except Exception as e:
        await message.reply_text(f"Error: {e}")

# ২. শিডিউলার (প্রতি ৩০ মিনিট পর পর পাবলিক চ্যানেলে পোস্ট করা)
async def post_scheduler():
    while True:
        try:
            # ডাটাবেস থেকে সবথেকে পুরনো ভিডিওটি খুঁজে বের করা
            video_data = await queue_col.find_one(sort=[("date", 1)])
            
            if video_data:
                msg_id = video_data["msg_id"]
                original_caption = video_data["caption"]

                # থাম্বনেইল পাওয়ার জন্য আসল ম্যাসেজটি লোড করা
                real_msg = await app.get_messages(SOURCE_CHANNEL, msg_id)
                thumb_path = await app.download_media(real_msg.thumbs[0].file_id) if real_msg.thumbs else None

                # স্টার্ট লিংক তৈরি (বটের ইউজারনেম দিয়ে)
                bot_info = await app.get_me()
                base_link = f"https://t.me/{bot_info.username}?start={msg_id}"
                
                # লিংক শর্ট করা
                short_link = await shorten_link(base_link)

                # পাবলিক চ্যানেলের জন্য পোস্ট সাজানো
                post_caption = (
                    f"🎬 **{original_caption}**\n\n"
                    f"🔗 **Download / Watch Video:**\n{short_link}\n\n"
                    f"👉 **Click the link above to watch!**"
                )

                # পোস্ট করা
                if thumb_path:
                    await app.send_photo(PUBLIC_CHANNEL, photo=thumb_path, caption=post_caption)
                else:
                    await app.send_message(PUBLIC_CHANNEL, post_caption)

                # কাজ শেষে ডাটাবেস থেকে রিমুভ করা
                await queue_col.delete_one({"_id": video_data["_id"]})
                print(f"Posted video {msg_id} to Public Channel")

            else:
                print("Queue empty. Waiting...")

        except Exception as e:
            print(f"Scheduler Error: {e}")

        # ৩০ মিনিট (১৮০০ সেকেন্ড) অপেক্ষা
        await asyncio.sleep(1800) 

# ------------------- RUN BOT -------------------

async def main():
    await app.start()
    print("Bot Started! Scheduler running...")
    
    # শিডিউলার ব্যাকগ্রাউন্ডে চালু করা
    asyncio.create_task(post_scheduler())
    
    await idle()
    await app.stop()

if __name__ == "__main__":
    app.run(main())
