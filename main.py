import asyncio
import logging
import aiohttp
from pyrogram import Client, filters, idle
from pyrogram.types import Message
from motor.motor_asyncio import AsyncIOMotorClient

# ------------------- CONFIGURATION (FIXED) -------------------
# এই অংশগুলো শুধু একবারই বসাবেন, এগুলো বারবার বদলানোর দরকার নেই
API_ID = 22697010       # আপনার API ID
API_HASH = "fd88d7339b0371eb2a9501d523f3e2a7"
BOT_TOKEN = "8303315439:AAGKPEugn60XGMC7_u4pOaZPnUWkWHvXSNM"
MONGO_URL = "mongodb+srv://mewayo8672:mewayo8672@cluster0.ozhvczp.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
ADMIN_ID = 8172129114   # আপনার টেলিগ্রাম আইডি (যে শুধু কন্ট্রোল করবে)

# ------------------- DATABASE CONNECTION -------------------
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client["AutoPostBot"]
queue_col = db["video_queue"]  # ভিডিও কিউ
config_col = db["config"]      # সেটিংস স্টোর

# মেমোরিতে ডাটা ক্যাশ করে রাখা (যাতে বারবার ডাটাবেস কল না হয়)
CACHE = {
    "source_channel": None,
    "public_channel": None,
    "shortener_api": None,
    "shortener_key": None,
    "auto_delete": 0,
    "protect_content": False
}

app = Client("smart_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ------------------- HELPER FUNCTIONS -------------------

# বট চালু হওয়ার সময় ডাটাবেস থেকে সেটিংস লোড করা
async def load_config():
    conf = await config_col.find_one({"_id": "settings"})
    if not conf:
        # ডিফল্ট সেটিংস তৈরি
        default_conf = {
            "_id": "settings",
            "source_channel": None,
            "public_channel": None,
            "shortener_api": "",
            "shortener_key": "",
            "auto_delete": 0,
            "protect_content": False
        }
        await config_col.insert_one(default_conf)
        conf = default_conf
    
    # ক্যাশ আপডেট করা
    CACHE.update(conf)
    print("✅ Configuration Loaded:", CACHE)

# সেটিংস আপডেট করার ফাংশন
async def update_config(key, value):
    await config_col.update_one({"_id": "settings"}, {"$set": {key: value}}, upsert=True)
    CACHE[key] = value # সাথে সাথে ক্যাশ আপডেট

# লিংক শর্টনার ফাংশন
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
        print(f"Shortener Error: {e}")
        return link

# ------------------- ADMIN COMMANDS (SETUP) -------------------

@app.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    if len(message.command) > 1:
        return await send_stored_file(client, message)
    
    await message.reply_text(
        "👋 **স্বাগতম!** আমি অটো পোস্টার বট।\n\n"
        "🛠 **সেটআপ কমান্ড (শুধুমাত্র এডমিন):**\n"
        "1. `/setsource -100xxxx` (যে চ্যানেল থেকে ভিডিও নেব)\n"
        "2. `/setpublic -100xxxx` (যে চ্যানেলে পোস্ট করব)\n"
        "3. `/setshortener API_URL API_KEY` (লিংক শর্টনার)\n"
        "4. `/autodelete 600` (সেকেন্ড)\n"
        "5. `/status` (বর্তমান অবস্থা)"
    )

# ১. সোর্স চ্যানেল সেট করা
@app.on_message(filters.command("setsource") & filters.user(ADMIN_ID))
async def set_source(client, message):
    try:
        chat_id = int(message.command[1])
        await update_config("source_channel", chat_id)
        await message.reply_text(f"✅ **সোর্স চ্যানেল সেট করা হয়েছে:** `{chat_id}`")
    except:
        await message.reply_text("❌ ভুল! লিখুন: `/setsource -100123456789`")

# ২. পাবলিক চ্যানেল সেট করা
@app.on_message(filters.command("setpublic") & filters.user(ADMIN_ID))
async def set_public(client, message):
    try:
        chat_id = int(message.command[1])
        await update_config("public_channel", chat_id)
        await message.reply_text(f"✅ **পাবলিক চ্যানেল সেট করা হয়েছে:** `{chat_id}`")
    except:
        await message.reply_text("❌ ভুল! লিখুন: `/setpublic -100987654321`")

# ৩. শর্টনার সেট করা
@app.on_message(filters.command("setshortener") & filters.user(ADMIN_ID))
async def set_shortener(client, message):
    try:
        _, url, key = message.text.split(" ")
        await update_config("shortener_api", url)
        await update_config("shortener_key", key)
        await message.reply_text("✅ **লিংক শর্টনার আপডেট করা হয়েছে!**")
    except:
        await message.reply_text("❌ ভুল! লিখুন: `/setshortener API_URL API_KEY`")

# ৪. অটো ডিলিট এবং প্রটেক্ট
@app.on_message(filters.command("autodelete") & filters.user(ADMIN_ID))
async def set_autodelete(client, message):
    try:
        seconds = int(message.command[1])
        await update_config("auto_delete", seconds)
        await message.reply_text(f"✅ অটো ডিলিট: {seconds} সেকেন্ড")
    except:
        await message.reply_text("❌ ভুল! উদাহরণ: `/autodelete 600`")

@app.on_message(filters.command("protect") & filters.user(ADMIN_ID))
async def toggle_protect(client, message):
    state = message.command[1].lower() == "on"
    await update_config("protect_content", state)
    await message.reply_text(f"✅ কন্টেন্ট প্রটেকশন: {'ON' if state else 'OFF'}")

# ৫. স্ট্যাটাস চেক
@app.on_message(filters.command("status") & filters.user(ADMIN_ID))
async def status(client, message):
    q_len = await queue_col.count_documents({})
    txt = (
        f"📊 **Bot Status**\n"
        f"📥 Source Channel: `{CACHE['source_channel']}`\n"
        f"📢 Public Channel: `{CACHE['public_channel']}`\n"
        f"⏳ Queue Pending: {q_len}\n"
        f"🔗 Shortener: {'Active' if CACHE['shortener_api'] else 'Inactive'}"
    )
    await message.reply_text(txt)

# ------------------- LOGIC: WATCHING & POSTING -------------------

# সোর্স চ্যানেল থেকে ভিডিও ধরা
@app.on_message(filters.channel & filters.video)
async def incoming_video(client, message):
    # চেক করি মেসেজটি আমাদের সেট করা সোর্স চ্যানেল থেকে এসেছে কি না
    if CACHE["source_channel"] and message.chat.id == int(CACHE["source_channel"]):
        video_data = {
            "msg_id": message.id,
            "caption": message.caption or "New Video",
            "file_id": message.video.file_id,
            "date": message.date
        }
        await queue_col.insert_one(video_data)
        print(f"📥 Queued video from {message.chat.title}")

# ফাইল ডেলিভারি (ইউজার যখন লিংকে ক্লিক করবে)
async def send_stored_file(client, message):
    try:
        if not CACHE["source_channel"]:
            return await message.reply_text("❌ এডমিন এখনো সোর্স চ্যানেল সেট করেনি।")

        msg_id = int(message.command[1])
        
        # সোর্স চ্যানেল থেকে কপি করা
        file_msg = await client.get_messages(int(CACHE["source_channel"]), msg_id)
        
        if not file_msg or not file_msg.video:
            return await message.reply_text("❌ ফাইলটি ডিলিট হয়ে গেছে।")

        sent = await file_msg.copy(
            chat_id=message.chat.id,
            caption=f"🎥 **{file_msg.caption[:50]}...**",
            protect_content=CACHE["protect_content"]
        )

        if CACHE["auto_delete"] > 0:
            await message.reply_text(f"⏳ **This video will be deleted in {CACHE['auto_delete']} seconds!**")
            await asyncio.sleep(CACHE["auto_delete"])
            await sent.delete()

    except Exception as e:
        await message.reply_text("❌ টেকনিক্যাল সমস্যা বা চ্যানেল অ্যাক্সেস নেই।")
        print(f"Delivery Error: {e}")

# শিডিউলার (অটোমেটিক পোস্টার)
async def post_scheduler():
    while True:
        try:
            # যদি পাবলিক বা সোর্স চ্যানেল সেট করা না থাকে, অপেক্ষা করো
            if not CACHE["source_channel"] or not CACHE["public_channel"]:
                await asyncio.sleep(60)
                continue

            # ডাটাবেস থেকে ভিডিও খোজা
            video_data = await queue_col.find_one(sort=[("date", 1)])
            
            if video_data:
                msg_id = video_data["msg_id"]
                
                # রিয়েল ভিডিও মেসেজ আনা (থাম্বনেইলের জন্য)
                try:
                    real_msg = await app.get_messages(int(CACHE["source_channel"]), msg_id)
                    thumb = await app.download_media(real_msg.thumbs[0].file_id) if real_msg.thumbs else None
                except:
                    # যদি সোর্স থেকে ভিডিও ডিলিট হয়ে যায়, কিউ থেকেও ডিলিট করে পরেরটায় যাবে
                    await queue_col.delete_one({"_id": video_data["_id"]})
                    continue

                # লিংক তৈরি
                bot_usr = (await app.get_me()).username
                start_link = f"https://t.me/{bot_usr}?start={msg_id}"
                final_link = await shorten_link(start_link)

                caption = (
                    f"🎬 **{video_data['caption']}**\n\n"
                    f"🔗 **Download Link:**\n{final_link}\n\n"
                    f"👉 Join Channel for more!"
                )

                # পাবলিক চ্যানেলে পোস্ট
                dest_id = int(CACHE["public_channel"])
                if thumb:
                    await app.send_photo(dest_id, thumb, caption=caption)
                else:
                    await app.send_message(dest_id, caption)

                # কিউ থেকে ডিলিট
                await queue_col.delete_one({"_id": video_data["_id"]})
                print(f"✅ Posted video {msg_id}")

            else:
                print("💤 Queue Empty...")

        except Exception as e:
            print(f"Scheduler Error: {e}")

        await asyncio.sleep(1800) # ৩০ মিনিট বিরতি

# ------------------- RUNNER -------------------

async def main():
    await app.start()
    await load_config() # বট চালুর সময় কনফিগারেশন লোড হবে
    print("🤖 Bot Started Successfully!")
    
    asyncio.create_task(post_scheduler())
    await idle()
    await app.stop()

if __name__ == "__main__":
    app.run(main())
