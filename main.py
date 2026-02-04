import asyncio
import logging
import aiohttp
from pyrogram import Client, filters, idle
from pyrogram.types import Message
from motor.motor_asyncio import AsyncIOMotorClient

# ------------------- CONFIGURATION -------------------
# ⚠️ আপনার তথ্যগুলো নিচে আবার বসিয়ে নিন (নিরাপত্তার জন্য আমি সরিয়ে দিয়েছি)
API_ID = 22697010                 # আপনার API ID বসান
API_HASH = "fd88d7339b0371eb2a9501d523f3e2a7"   # আপনার API HASH বসান
BOT_TOKEN = "8303315439:AAGKPEugn60XGMC7_u4pOaZPnUWkWHvXSNM" # আপনার BOT TOKEN বসান
MONGO_URL = "mongodb+srv://mewayo8672:mewayo8672@cluster0.ozhvczp.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0" # আপনার MONGODB URL বসান
ADMIN_ID = 8172129114             # আপনার টেলিগ্রাম ADMIN ID বসান

# ------------------- DATABASE CONNECTION -------------------
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client["AutoPostBot"]
queue_col = db["video_queue"]  # ভিডিও কিউ
config_col = db["config"]      # সেটিংস স্টোর

# মেমোরিতে ডাটা ক্যাশ করে রাখা
CACHE = {
    "source_channel": None,
    "public_channel": None,
    "shortener_api": None,
    "shortener_key": None,
    "auto_delete": 0,
    "protect_content": False,
    "post_interval": 1800  # ডিফল্ট ৩০ মিনিট (সেকেন্ডে)
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
            "post_interval": 1800
        }
        await config_col.insert_one(default_conf)
        conf = default_conf
    
    # ডাটাবেস থেকে মান নিয়ে ক্যাশ আপডেট করা
    # পুরানো ডাটাবেস হলে post_interval নাও থাকতে পারে, তাই .get() ব্যবহার করা হয়েছে
    CACHE.update(conf)
    if "post_interval" not in CACHE:
        CACHE["post_interval"] = 1800
        
    print("✅ Configuration Loaded:", CACHE)

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
        print(f"Shortener Error: {e}")
        return link

# ------------------- ADMIN COMMANDS -------------------

@app.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    if len(message.command) > 1:
        return await send_stored_file(client, message)
    
    await message.reply_text(
        "👋 **স্বাগতম!** আমি অটো পোস্টার বট।\n\n"
        "🛠 **সেটআপ কমান্ড (শুধুমাত্র এডমিন):**\n"
        "1. `/setsource -100xxxx` (সোর্স চ্যানেল)\n"
        "2. `/setpublic -100xxxx` (পাবলিক চ্যানেল)\n"
        "3. `/setinterval 10` (পোস্টিং গ্যাপ - সেকেন্ডে)\n"
        "4. `/setshortener API_URL API_KEY` (লিংক শর্টনার)\n"
        "5. `/autodelete 600` (অটো ডিলিট - সেকেন্ডে)\n"
        "6. `/status` (বর্তমান অবস্থা)"
    )

@app.on_message(filters.command("setsource") & filters.user(ADMIN_ID))
async def set_source(client, message):
    try:
        chat_id = int(message.command[1])
        await update_config("source_channel", chat_id)
        await message.reply_text(f"✅ **সোর্স চ্যানেল সেট করা হয়েছে:** `{chat_id}`")
    except:
        await message.reply_text("❌ ভুল! লিখুন: `/setsource -100...`")

@app.on_message(filters.command("setpublic") & filters.user(ADMIN_ID))
async def set_public(client, message):
    try:
        chat_id = int(message.command[1])
        await update_config("public_channel", chat_id)
        await message.reply_text(f"✅ **পাবলিক চ্যানেল সেট করা হয়েছে:** `{chat_id}`")
    except:
        await message.reply_text("❌ ভুল! লিখুন: `/setpublic -100...`")

@app.on_message(filters.command("setshortener") & filters.user(ADMIN_ID))
async def set_shortener(client, message):
    try:
        _, url, key = message.text.split(" ")
        await update_config("shortener_api", url)
        await update_config("shortener_key", key)
        await message.reply_text("✅ **লিংক শর্টনার আপডেট করা হয়েছে!**")
    except:
        await message.reply_text("❌ ভুল! লিখুন: `/setshortener URL KEY`")

@app.on_message(filters.command("autodelete") & filters.user(ADMIN_ID))
async def set_autodelete(client, message):
    try:
        seconds = int(message.command[1])
        await update_config("auto_delete", seconds)
        await message.reply_text(f"✅ ইউজার ফাইল ডিলিট হবে: {seconds} সেকেন্ড পর।")
    except:
        await message.reply_text("❌ ভুল! উদাহরণ: `/autodelete 600`")

# 🔥 নতুন কমান্ড: পোস্ট ইন্টারভাল সেট করা
@app.on_message(filters.command("setinterval") & filters.user(ADMIN_ID))
async def set_post_interval(client, message):
    try:
        seconds = int(message.command[1])
        if seconds < 5:
            return await message.reply_text("⚠️ সর্বনিম্ন ৫ সেকেন্ড দিতে হবে।")
            
        await update_config("post_interval", seconds)
        await message.reply_text(f"🚀 **পোস্টিং স্পিড আপডেট করা হয়েছে!**\nএখন প্রতি **{seconds}** সেকেন্ড পর পর ভিডিও পোস্ট হবে।")
    except:
        await message.reply_text("❌ ভুল! উদাহরণ: `/setinterval 10` (টেস্ট করার জন্য) অথবা `/setinterval 1800` (৩০ মিনিট)")

@app.on_message(filters.command("protect") & filters.user(ADMIN_ID))
async def toggle_protect(client, message):
    try:
        state = message.command[1].lower() == "on"
        await update_config("protect_content", state)
        await message.reply_text(f"✅ কন্টেন্ট প্রটেকশন: {'ON' if state else 'OFF'}")
    except:
        await message.reply_text("Use: `/protect on` or `/protect off`")

@app.on_message(filters.command("status") & filters.user(ADMIN_ID))
async def status(client, message):
    q_len = await queue_col.count_documents({})
    txt = (
        f"📊 **Bot Status**\n"
        f"📥 Source: `{CACHE['source_channel']}`\n"
        f"📢 Public: `{CACHE['public_channel']}`\n"
        f"⏱ Post Interval: {CACHE['post_interval']}s\n"
        f"⏳ Queue Pending: {q_len}\n"
        f"🗑 Auto Delete: {CACHE['auto_delete']}s"
    )
    await message.reply_text(txt)

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
        print(f"📥 Queued: {message.id}")

async def send_stored_file(client, message):
    try:
        if not CACHE["source_channel"]:
            return await message.reply_text("❌ Source Channel not set!")

        msg_id = int(message.command[1])
        file_msg = await client.get_messages(int(CACHE["source_channel"]), msg_id)
        
        if not file_msg or not file_msg.video:
            return await message.reply_text("❌ File not found (Deleted).")

        sent = await file_msg.copy(
            chat_id=message.chat.id,
            caption=f"🎥 **{file_msg.caption[:50]}...**",
            protect_content=CACHE["protect_content"]
        )

        if CACHE["auto_delete"] > 0:
            await message.reply_text(f"⏳ Deleting in {CACHE['auto_delete']} seconds!")
            await asyncio.sleep(CACHE["auto_delete"])
            await sent.delete()

    except Exception as e:
        await message.reply_text("❌ Error getting file.")
        print(f"Delivery Error: {e}")

async def post_scheduler():
    while True:
        try:
            # সেটিংস থেকে ইন্টারভাল টাইম নেওয়া (ডিফল্ট ১৮০০)
            interval = CACHE.get("post_interval", 1800)

            if not CACHE["source_channel"] or not CACHE["public_channel"]:
                await asyncio.sleep(30)
                continue

            video_data = await queue_col.find_one(sort=[("date", 1)])
            
            if video_data:
                msg_id = video_data["msg_id"]
                try:
                    real_msg = await app.get_messages(int(CACHE["source_channel"]), msg_id)
                    thumb = await app.download_media(real_msg.thumbs[0].file_id) if real_msg.thumbs else None
                except:
                    await queue_col.delete_one({"_id": video_data["_id"]})
                    continue

                bot_usr = (await app.get_me()).username
                start_link = f"https://t.me/{bot_usr}?start={msg_id}"
                final_link = await shorten_link(start_link)

                caption = (
                    f"🎬 **{video_data['caption']}**\n\n"
                    f"🔗 **Watch Full Video:**\n{final_link}\n\n"
                    f"👉 Join Channel for more!"
                )

                dest_id = int(CACHE["public_channel"])
                if thumb:
                    await app.send_photo(dest_id, thumb, caption=caption)
                else:
                    await app.send_message(dest_id, caption)

                await queue_col.delete_one({"_id": video_data["_id"]})
                print(f"✅ Posted {msg_id}. Waiting {interval}s...")
                
                # এখানে ডায়নামিক টাইমার ব্যবহার করা হচ্ছে
                await asyncio.sleep(interval)
            else:
                print("💤 Queue Empty. Checking again in 60s...")
                await asyncio.sleep(60)

        except Exception as e:
            print(f"Scheduler Error: {e}")
            await asyncio.sleep(60)

# ------------------- MAIN -------------------

async def main():
    await app.start()
    await load_config()
    print("🤖 Bot Started with Dynamic Scheduler!")
    asyncio.create_task(post_scheduler())
    await idle()
    await app.stop()

if __name__ == "__main__":
    app.run(main())
