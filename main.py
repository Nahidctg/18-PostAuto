import asyncio
import os
import aiohttp
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait, ChatWriteForbidden, ChatAdminRequired, RPCError
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
    "post_interval": 20, # ডিফল্ট ২০ সেকেন্ড
    "tutorial_url": "https://t.me/YourTutorialLink"
}

app = Client("smart_bot_v2", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ------------------- HELPER FUNCTIONS -------------------

async def notify_admin(text):
    """এডমিনকে এরর বা স্ট্যাটাস জানানোর ফাংশন"""
    try:
        await app.send_message(ADMIN_ID, text)
    except Exception as e:
        print(f"Failed to notify admin: {e}")

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
            "post_interval": 20,
            "tutorial_url": "https://youtube.com"
        }
        await config_col.insert_one(default_conf)
        conf = default_conf
    
    CACHE.update(conf)
    print(f"✅ Config Loaded: Source={CACHE['source_channel']} | Public={CACHE['public_channel']}")

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
                if short_url: return short_url
    except Exception as e:
        print(f"Shortener Error: {e}")
    return link

# ------------------- ADMIN COMMANDS -------------------

@app.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    if len(message.command) > 1:
        return await send_stored_file(client, message)
    await message.reply_text("👋 Bot is Online! V2.0\nUse /status to check queue.")

@app.on_message(filters.command("setsource") & filters.user(ADMIN_ID))
async def set_source(client, message):
    try:
        chat_id = int(message.command[1])
        try:
            chat = await client.get_chat(chat_id)
            await update_config("source_channel", chat_id)
            await message.reply_text(f"✅ Source Channel Set: `{chat.title}`\nID: `{chat_id}`")
        except Exception as e:
            await message.reply_text(f"❌ Error: Bot isn't admin in that channel or wrong ID.\nLog: {e}")
    except: await message.reply_text("❌ Format: `/setsource -100xxxx`")

@app.on_message(filters.command("setpublic") & filters.user(ADMIN_ID))
async def set_public(client, message):
    try:
        chat_id = int(message.command[1])
        try:
            chat = await client.get_chat(chat_id)
            await update_config("public_channel", chat_id)
            await message.reply_text(f"✅ Public Channel Set: `{chat.title}`\nID: `{chat_id}`")
        except Exception as e:
            await message.reply_text(f"❌ Error: Bot isn't admin in that channel or wrong ID.\nLog: {e}")
    except: await message.reply_text("❌ Format: `/setpublic -100xxxx`")

@app.on_message(filters.command("status") & filters.user(ADMIN_ID))
async def status(client, message):
    q_len = await queue_col.count_documents({})
    await message.reply_text(
        f"📊 **SYSTEM STATUS**\n"
        f"📥 Source: `{CACHE['source_channel']}`\n"
        f"📢 Public: `{CACHE['public_channel']}`\n"
        f"⏳ Queue Pending: `{q_len}`\n"
        f"⏱ Interval: {CACHE.get('post_interval', 20)}s"
    )

@app.on_message(filters.command("clearqueue") & filters.user(ADMIN_ID))
async def clear_queue(client, message):
    await queue_col.delete_many({})
    await message.reply_text("🗑️ Queue Cleared!")

# ------------------- INPUT LOGIC -------------------

@app.on_message(filters.channel & (filters.video | filters.document))
async def incoming_video(client, message):
    # সোর্স চ্যানেল চেক
    if CACHE["source_channel"] and message.chat.id == int(CACHE["source_channel"]):
        
        # ফাইল আইডি বের করা
        file_id = None
        if message.video:
            file_id = message.video.file_id
        elif message.document and message.document.mime_type and "video" in message.document.mime_type:
            file_id = message.document.file_id
        
        if file_id:
            video_data = {
                "msg_id": message.id,
                "caption": message.caption or "New Video",
                "file_id": file_id,
                "date": message.date
            }
            await queue_col.insert_one(video_data)
            print(f"✅ Added to Queue: MsgID {message.id}")
        else:
            print("⚠️ Ignored non-video file")

async def send_stored_file(client, message):
    try:
        msg_id = int(message.command[1])
        if not CACHE["source_channel"]:
            return await message.reply_text("❌ Source Channel not set!")

        file_msg = await client.get_messages(int(CACHE["source_channel"]), msg_id)
        
        if not file_msg or (not file_msg.video and not file_msg.document):
            return await message.reply_text("❌ File not found (Maybe deleted from source).")

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
        await message.reply_text(f"❌ Error sending file: {e}")

# ------------------- SCHEDULER (UPDATED) -------------------

async def post_scheduler():
    print("🔄 Scheduler Started...")
    await notify_admin("🔄 Bot Started! Scheduler is running.")

    while True:
        interval = CACHE.get("post_interval", 20)
        
        try:
            if not CACHE["source_channel"] or not CACHE["public_channel"]:
                await asyncio.sleep(10)
                continue

            # Queue চেক করা
            video_data = await queue_col.find_one(sort=[("date", 1)])
            
            if video_data:
                msg_id = video_data["msg_id"]
                source_id = int(CACHE["source_channel"])
                dest_id = int(CACHE["public_channel"])

                print(f"🚀 Processing MsgID: {msg_id}")

                # ১. সোর্স থেকে মেসেজটা আনার চেষ্টা
                try:
                    real_msg = await app.get_messages(source_id, msg_id)
                    if not real_msg or (not real_msg.video and not real_msg.document):
                        await notify_admin(f"⚠️ **Skipped ID:** `{msg_id}`\nReason: Message deleted from Source.")
                        await queue_col.delete_one({"_id": video_data["_id"]})
                        continue
                except Exception as e:
                    print(f"Source Access Error: {e}")
                    await asyncio.sleep(10)
                    continue

                # ২. লিঙ্ক এবং থাম্বনেইল তৈরি
                bot_usr = (await app.get_me()).username
                start_link = f"https://t.me/{bot_usr}?start={msg_id}"
                final_link = await shorten_link(start_link)
                
                caption_text = video_data.get('caption', 'Video') or "Video"
                full_caption = (
                    f"🎬 **{caption_text[:100]}**\n\n"
                    f"🔗 **Download:** {final_link}"
                )
                
                buttons = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📥 Download / Watch Video", url=final_link)]
                ])

                # থাম্বনেইল ডাউনলোড করার চেষ্টা
                thumb_path = None
                try:
                    if real_msg.thumbs:
                        thumb_path = await app.download_media(real_msg.thumbs[0].file_id)
                    elif real_msg.video and real_msg.video.thumbs:
                        thumb_path = await app.download_media(real_msg.video.thumbs[0].file_id)
                except Exception as e:
                    print(f"Thumbnail Error: {e}") # থাম্বনেইল না থাকলে সমস্যা নেই, টেক্সট যাবে

                # ৩. পোস্ট করা (Try-Except Block for Posting)
                posted = False
                try:
                    if thumb_path:
                        await app.send_photo(dest_id, photo=thumb_path, caption=full_caption, reply_markup=buttons)
                        os.remove(thumb_path)
                    else:
                        # থাম্বনেইল না পেলে শুধু টেক্সট
                        await app.send_message(dest_id, text=full_caption, reply_markup=buttons)
                    
                    posted = True
                    print(f"✅ Successfully Posted: {msg_id}")
                    await queue_col.delete_one({"_id": video_data["_id"]})

                except ChatWriteForbidden:
                    await notify_admin(f"🚨 **POST FAILED!**\nBot is NOT Admin in Public Channel (`{dest_id}`).\nPlease make me Admin with 'Post Messages' rights.")
                    # Queue থেকে ডিলিট করছি না, যাতে পারমিশন ঠিক করার পর আবার ট্রাই করতে পারে
                    await asyncio.sleep(60) 
                    
                except ChatAdminRequired:
                    await notify_admin(f"🚨 **POST FAILED!**\nNeed Admin permission in Public Channel.")
                    await asyncio.sleep(60)

                except FloodWait as e:
                    print(f"⏳ Sleeping for {e.value}s due to FloodWait")
                    await asyncio.sleep(e.value)
                
                except RPCError as e:
                    # অন্য কোনো টেলিগ্রাম এরর হলে এডমিনকে জানানো হবে
                    await notify_admin(f"❌ **Telegram Error for ID {msg_id}:**\n`{e}`\nSkipping this video.")
                    await queue_col.delete_one({"_id": video_data["_id"]})

                except Exception as e:
                    # একদম অজানা এরর
                    await notify_admin(f"❌ **Unknown Error for ID {msg_id}:**\n`{e}`")
                    await queue_col.delete_one({"_id": video_data["_id"]})

            else:
                # Queue খালি থাকলে অপেক্ষা
                pass

        except Exception as e:
            print(f"Critical Scheduler Loop Error: {e}")
            await asyncio.sleep(5)
            
        await asyncio.sleep(interval)

# ------------------- RUNNER -------------------

async def main():
    await app.start()
    await load_config()
    
    # Check permissions on start
    if CACHE["public_channel"]:
        try:
            chat = await app.get_chat(CACHE["public_channel"])
            perms = chat.permissions
            print(f"Connected to Public: {chat.title}")
        except Exception as e:
            print(f"Startup Warning: Cannot access Public Channel. {e}")

    asyncio.create_task(post_scheduler())
    await idle()
    await app.stop()

if __name__ == "__main__":
    app.run(main())
