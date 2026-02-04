import asyncio
import logging
import os
import aiohttp
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait, ChatWriteForbidden, ChatAdminRequired, PeerIdInvalid
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

CACHE = {
    "source_channel": None,
    "public_channel": None,
    "shortener_api": None,
    "shortener_key": None,
    "auto_delete": 0,
    "protect_content": False,
    "post_interval": 30, # টেস্টিংয়ের জন্য কমিয়ে ৩০ সেকেন্ড করা হলো
    "tutorial_url": "https://t.me/YourTutorialLink"
}

app = Client("smart_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ------------------- HELPER FUNCTIONS -------------------

async def notify_admin(text):
    try:
        await app.send_message(ADMIN_ID, text)
    except Exception as e:
        print(f"Could not notify admin: {e}")

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
            "post_interval": 30,
            "tutorial_url": "https://youtube.com"
        }
        await config_col.insert_one(default_conf)
        conf = default_conf
    
    CACHE.update(conf)
    print(f"✅ Config Loaded: Source={CACHE['source_channel']}, Public={CACHE['public_channel']}")

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
                short_url = data.get("shortenedUrl") or data.get("url")
                if short_url:
                    return short_url
                else:
                    return link
    except Exception as e:
        print(f"Shortener Error: {e}")
        return link

# ------------------- ADMIN COMMANDS -------------------

@app.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    if len(message.command) > 1:
        return await send_stored_file(client, message)
    await message.reply_text("👋 Bot is Ready! Use /setsource and /setpublic to configure.")

@app.on_message(filters.command("setsource") & filters.user(ADMIN_ID))
async def set_source(client, message):
    try:
        chat_id = int(message.command[1])
        try:
            chat = await client.get_chat(chat_id)
            await update_config("source_channel", chat_id)
            await message.reply_text(f"✅ Source Set: `{chat.title}` ({chat_id})")
        except Exception as e:
            await message.reply_text(f"❌ Bot cannot access channel. Make bot admin first.\nError: {e}")
    except: await message.reply_text("❌ Use: `/setsource -100xxxx`")

@app.on_message(filters.command("setpublic") & filters.user(ADMIN_ID))
async def set_public(client, message):
    try:
        chat_id = int(message.command[1])
        try:
            chat = await client.get_chat(chat_id)
            await update_config("public_channel", chat_id)
            await message.reply_text(f"✅ Public Set: `{chat.title}` ({chat_id})")
        except Exception as e:
            await message.reply_text(f"❌ Bot cannot access channel. Make bot admin first.\nError: {e}")
    except: await message.reply_text("❌ Use: `/setpublic -100xxxx`")

@app.on_message(filters.command("status") & filters.user(ADMIN_ID))
async def status(client, message):
    q_len = await queue_col.count_documents({})
    await message.reply_text(
        f"📊 **STATUS**\n"
        f"📥 Source: `{CACHE['source_channel']}`\n"
        f"📢 Public: `{CACHE['public_channel']}`\n"
        f"⏳ Queue Size: `{q_len}`\n"
    )

# ------------------- LOGIC (FIXED) -------------------

# Fix: Added filters.document along with filters.video
@app.on_message(filters.channel & (filters.video | filters.document))
async def incoming_video(client, message):
    # Debug print
    print(f"📩 New Message in {message.chat.id}. Expected Source: {CACHE['source_channel']}")
    
    if CACHE["source_channel"] and message.chat.id == int(CACHE["source_channel"]):
        # Check if document is actually a video
        file_id = None
        if message.video:
            file_id = message.video.file_id
        elif message.document and message.document.mime_type.startswith("video"):
            file_id = message.document.file_id
        
        if file_id:
            video_data = {
                "msg_id": message.id,
                "caption": message.caption or "New Video",
                "file_id": file_id,
                "date": message.date
            }
            await queue_col.insert_one(video_data)
            print(f"✅ Video Added to Queue: {message.id}")
        else:
            print("❌ Ignored: Not a video file.")

async def send_stored_file(client, message):
    try:
        msg_id = int(message.command[1])
        if not CACHE["source_channel"]:
            return await message.reply_text("❌ Source Channel not set!")

        # Fetch message directly using ID
        file_msg = await client.get_messages(int(CACHE["source_channel"]), msg_id)
        
        if not file_msg or (not file_msg.video and not file_msg.document):
            return await message.reply_text("❌ File deleted or not found.")

        caption = f"🎥 **{file_msg.caption[:50] if file_msg.caption else 'Video'}...**"
        
        sent = await file_msg.copy(
            chat_id=message.chat.id,
            caption=caption,
            protect_content=CACHE["protect_content"]
        )

        if CACHE["auto_delete"] > 0:
            await asyncio.sleep(CACHE["auto_delete"])
            await sent.delete()
    except Exception as e:
        print(f"Delivery Error: {e}")

# ------------------- SCHEDULER -------------------

async def post_scheduler():
    print("🔄 Scheduler Started...")
    while True:
        interval = CACHE.get("post_interval", 30)
        
        try:
            if not CACHE["source_channel"] or not CACHE["public_channel"]:
                print("⚠️ Channels not configured yet. Waiting...")
                await asyncio.sleep(20)
                continue

            # Check Queue
            video_data = await queue_col.find_one(sort=[("date", 1)])
            
            if video_data:
                msg_id = video_data["msg_id"]
                print(f"🚀 Processing Video ID: {msg_id}")
                
                try:
                    real_msg = await app.get_messages(int(CACHE["source_channel"]), msg_id)
                    
                    if not real_msg:
                        print("❌ Message not found in source, deleting from queue.")
                        await queue_col.delete_one({"_id": video_data["_id"]})
                        continue

                    # Thumbnail Logic
                    thumb_path = None
                    if real_msg.thumbs:
                        thumb_path = await app.download_media(real_msg.thumbs[0].file_id)
                    elif real_msg.video and real_msg.video.thumbs:
                         thumb_path = await app.download_media(real_msg.video.thumbs[0].file_id)

                    bot_usr = (await app.get_me()).username
                    start_link = f"https://t.me/{bot_usr}?start={msg_id}"
                    final_link = await shorten_link(start_link)

                    dest_id = int(CACHE["public_channel"])
                    caption_text = video_data.get('caption', 'Video')
                    if caption_text is None: caption_text = "Video"
                    
                    caption = (
                        f"🎬 **{caption_text[:100]}**\n\n"
                        f"🔗 **Download:** {final_link}"
                    )
                    
                    buttons = InlineKeyboardMarkup([
                        [InlineKeyboardButton("📥 Download Video", url=final_link)]
                    ])

                    # Posting
                    if thumb_path:
                        await app.send_photo(dest_id, photo=thumb_path, caption=caption, reply_markup=buttons)
                        os.remove(thumb_path)
                    else:
                        await app.send_message(dest_id, text=caption, reply_markup=buttons)
                    
                    print(f"✅ Posted Successfully: {msg_id}")
                    await queue_col.delete_one({"_id": video_data["_id"]})

                except Exception as e:
                    print(f"❌ Post Failed: {e}")
                    # Error হলে আপাতত Queue থেকে মুছে ফেলছি যাতে লুপ না হয়
                    await queue_col.delete_one({"_id": video_data["_id"]})
            else:
                print("💤 Queue Empty...")

        except Exception as e:
            print(f"Critical Scheduler Error: {e}")
            
        await asyncio.sleep(interval)

# ------------------- RUNNER -------------------

async def main():
    await app.start()
    await load_config()
    print("🤖 BOT STARTED SUCCESSFULLY")
    
    # Check if channels are set
    if not CACHE["source_channel"]:
        print("⚠️ WARNING: Source Channel NOT set! Run /setsource")
    if not CACHE["public_channel"]:
        print("⚠️ WARNING: Public Channel NOT set! Run /setpublic")

    asyncio.create_task(post_scheduler())
    await idle()
    await app.stop()

if __name__ == "__main__":
    app.run(main())
