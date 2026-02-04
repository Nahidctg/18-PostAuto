import asyncio
import os
import shutil
import time
import aiohttp
from pyrogram import Client, filters, idle
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, 
    InputMediaPhoto
)
from motor.motor_asyncio import AsyncIOMotorClient
from aiohttp import web
import cv2  # OpenCV (For Thumbnails)

# ------------------- ১. কনফিগারেশন -------------------
API_ID = 22697010
API_HASH = "fd88d7339b0371eb2a9501d523f3e2a7"
BOT_TOKEN = "8303315439:AAGKPEugn60XGMC7_u4pOaZPnUWkWHvXSNM"
MONGO_URL = "mongodb+srv://mewayo8672:mewayo8672@cluster0.ozhvczp.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
ADMIN_ID = 8172129114

# ডাটাবেস
mongo = AsyncIOMotorClient(MONGO_URL)
db = mongo["Final_Bot_Pro"]
queue_col = db["queue"]
config_col = db["config"]

# গ্লোবাল কনফিগ (Default Values)
CONFIG = {
    "source": None,
    "public": None,
    "interval": 30,             # Default 30s
    "shortener_domain": None,   # Link Shortener Domain
    "shortener_key": None,      # Link Shortener API Key
    "auto_delete": 0,           # 0 means OFF
    "protect": False,           # Content Protection
    "caption": "🎬 **{caption}**\n\n✨ **Quality:** HD 720p\n🔥 **Exclusive Content**"
}

app = Client("Master_Bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ------------------- ২. ওয়েব সার্ভার -------------------
async def web_server():
    async def handle(req): return web.Response(text="Bot is Active & Running!")
    app_web = web.Application()
    app_web.add_routes([web.get('/', handle)])
    runner = web.AppRunner(app_web)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 8080))).start()

# ------------------- ৩. হেল্পার ফাংশনস -------------------

async def load_settings():
    """ডাটাবেস থেকে সব সেটিংস লোড করা"""
    data = await config_col.find_one({"_id": "settings"})
    if not data:
        await config_col.insert_one({"_id": "settings"})
        return
    
    CONFIG.update(data)
    # অপ্রয়োজনীয় key ক্লিনআপ
    if "_id" in CONFIG: del CONFIG["_id"]
    print("⚙️ Settings Loaded Successfully!")

async def update_setting(key, value):
    """সেটিংস আপডেট করা"""
    await config_col.update_one({"_id": "settings"}, {"$set": {key: value}}, upsert=True)
    CONFIG[key] = value

async def get_short_link(long_url):
    """লিংক শর্টনার API হ্যান্ডেলিং"""
    if not CONFIG["shortener_domain"] or not CONFIG["shortener_key"]:
        return long_url

    try:
        # সাধারণ API ফরম্যাট: https://domain.com/api?api=KEY&url=URL
        api_url = f"https://{CONFIG['shortener_domain']}/api?api={CONFIG['shortener_key']}&url={long_url}"
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as resp:
                data = await resp.json()
                if "shortenedUrl" in data:
                    return data["shortenedUrl"]
    except Exception as e:
        print(f"Shortener Error: {e}")
    
    return long_url  # ফেইল করলে অরিজিনাল লিংক দিবে

def generate_thumb_cv2(video_path, msg_id):
    """OpenCV দিয়ে থাম্বনেইল জেনারেট (FFmpeg ছাড়া)"""
    thumb_path = f"downloads/thumb_{msg_id}.jpg"
    try:
        vid = cv2.VideoCapture(video_path)
        if not vid.isOpened(): return None
        
        # ১০ সেকেন্ড অথবা ভিডিওর মাঝখান থেকে ছবি নিবে
        frames = vid.get(cv2.CAP_PROP_FRAME_COUNT)
        fps = vid.get(cv2.CAP_PROP_FPS)
        duration = frames / fps if fps > 0 else 0
        
        target = 10 if duration > 15 else duration / 2
        vid.set(cv2.CAP_PROP_POS_FRAMES, int(target * fps))
        
        ret, frame = vid.read()
        if ret:
            cv2.imwrite(thumb_path, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
            vid.release()
            return thumb_path
        vid.release()
    except: pass
    return None

# ------------------- ৪. কমান্ড হ্যান্ডলার (সব কমান্ড) -------------------

@app.on_message(filters.command("start"))
async def start_c(c, m):
    # ইউজার ডেলিভারি পার্ট
    if len(m.command) > 1:
        return await deliver_content(c, m)

    # অ্যাডমিন প্যানেল
    if m.from_user.id == ADMIN_ID:
        txt = (
            "🛠 **ADMIN COMMANDS**\n\n"
            "📌 `/setsource -100xxx` - Set Source Channel\n"
            "📌 `/setpublic -100xxx` - Set Public Channel\n"
            "⏱ `/setinterval 60` - Set Post Delay (Sec)\n"
            "🔗 `/setshortener domain.com api_key`\n"
            "⏳ `/autodelete 60` - Auto Delete (0 to off)\n"
            "🛡 `/protect on/off` - Content Protection\n"
            "📊 `/status` - Check Settings"
        )
        await m.reply(txt)
    else:
        await m.reply("👋 I am an Auto Post Bot. Join channel for updates.")

async def deliver_content(c, m):
    """ভিডিও ডেলিভারি + অটো ডিলিট + প্রটেকশন"""
    try:
        msg_id = int(m.command[1])
        if not CONFIG["source"]: return await m.reply("❌ Bot Maintenance Mode.")

        sts = await m.reply("🔄 **Processing Video...**")
        msg = await c.get_messages(int(CONFIG["source"]), msg_id)
        
        if not msg: return await sts.edit("❌ Content Deleted.")

        # কপি করা (প্রটেকশন সেটিং অনুযায়ী)
        caption = "✅ **Here is your video!**\n❌ **Don't Forward**"
        
        sent_msg = await msg.copy(
            chat_id=m.chat.id,
            caption=caption,
            protect_content=CONFIG["protect"] # True/False
        )
        await sts.delete()

        # অটো ডিলিট লজিক
        if CONFIG["auto_delete"] > 0:
            notify = await m.reply(f"⏳ **This video will be deleted in {CONFIG['auto_delete']} seconds!**")
            await asyncio.sleep(CONFIG["auto_delete"])
            await sent_msg.delete()
            await notify.delete()

    except Exception as e:
        print(f"Delivery Error: {e}")

# ----- কনফিগারেশন কমান্ডস -----

@app.on_message(filters.command("setsource") & filters.user(ADMIN_ID))
async def set_src(c, m):
    try:
        cid = int(m.command[1])
        await update_setting("source", cid)
        await m.reply(f"✅ Source Set: `{cid}`")
    except: await m.reply("Usage: `/setsource -100xxxx`")

@app.on_message(filters.command("setpublic") & filters.user(ADMIN_ID))
async def set_pub(c, m):
    try:
        cid = int(m.command[1])
        await update_setting("public", cid)
        await m.reply(f"✅ Public Set: `{cid}`")
    except: await m.reply("Usage: `/setpublic -100xxxx`")

@app.on_message(filters.command("setinterval") & filters.user(ADMIN_ID))
async def set_int(c, m):
    try:
        sec = int(m.command[1])
        await update_setting("interval", sec)
        await m.reply(f"⏱ Interval Set: `{sec} seconds`")
    except: await m.reply("Usage: `/setinterval 60`")

@app.on_message(filters.command("autodelete") & filters.user(ADMIN_ID))
async def set_ad(c, m):
    try:
        sec = int(m.command[1])
        await update_setting("auto_delete", sec)
        await m.reply(f"⏳ Auto Delete: `{sec} seconds`")
    except: await m.reply("Usage: `/autodelete 60` (Set 0 to disable)")

@app.on_message(filters.command("protect") & filters.user(ADMIN_ID))
async def set_prot(c, m):
    try:
        val = m.command[1].lower()
        if val == "on":
            await update_setting("protect", True)
            await m.reply("🛡 Content Protection: **ON**")
        elif val == "off":
            await update_setting("protect", False)
            await m.reply("🛡 Content Protection: **OFF**")
        else:
            await m.reply("Usage: `/protect on` or `/protect off`")
    except: await m.reply("Usage: `/protect on` or `/protect off`")

@app.on_message(filters.command("setshortener") & filters.user(ADMIN_ID))
async def set_short(c, m):
    try:
        # /setshortener domain.com api_key
        if len(m.command) < 3:
            return await m.reply("Usage: `/setshortener domain.com api_key`")
        
        dom = m.command[1]
        key = m.command[2]
        await update_setting("shortener_domain", dom)
        await update_setting("shortener_key", key)
        await m.reply(f"🔗 Shortener Set:\nDomain: `{dom}`\nKey: `{key}`")
    except Exception as e: await m.reply(f"Error: {e}")

@app.on_message(filters.command("status") & filters.user(ADMIN_ID))
async def status_cmd(c, m):
    q = await queue_col.count_documents({})
    txt = (
        f"📊 **SYSTEM STATUS**\n"
        f"📥 Queue: `{q}`\n"
        f"⏱ Interval: `{CONFIG['interval']}s`\n"
        f"⏳ Auto Delete: `{CONFIG['auto_delete']}s`\n"
        f"🛡 Protected: `{CONFIG['protect']}`\n"
        f"📂 Source: `{CONFIG['source']}`\n"
        f"📢 Public: `{CONFIG['public']}`\n"
        f"🔗 Shortener: `{'Active' if CONFIG['shortener_domain'] else 'Disabled'}`"
    )
    await m.reply(txt)

# ------------------- ৫. অটো পোস্টিং ইঞ্জিন -------------------
@app.on_message(filters.channel & (filters.video | filters.document))
async def listener(c, m):
    if CONFIG["source"] and m.chat.id == int(CONFIG["source"]):
        if m.video or (m.document and "video" in m.document.mime_type):
            if not await queue_col.find_one({"msg_id": m.id}):
                await queue_col.insert_one({"msg_id": m.id, "caption": m.caption, "date": m.date})
                print(f"📥 New Video: {m.id}")

async def processor():
    if not os.path.exists("downloads"): os.makedirs("downloads")
    print("🚀 Engine Started...")
    
    while True:
        try:
            if not CONFIG["source"] or not CONFIG["public"]:
                await asyncio.sleep(20); continue

            task = await queue_col.find_one(sort=[("date", 1)])
            if task:
                msg_id = task["msg_id"]
                try:
                    # ১. ভিডিও ডাউনলোড
                    msg = await app.get_messages(int(CONFIG["source"]), msg_id)
                    if not msg:
                        await queue_col.delete_one({"_id": task["_id"]}); continue
                    
                    v_path = f"downloads/v_{msg_id}.mp4"
                    await app.download_media(msg, file_name=v_path)

                    # ২. থাম্বনেইল জেনারেট (OpenCV)
                    t_path = generate_thumb_cv2(v_path, msg_id)

                    # ৩. লিংক শর্ট করা
                    bot_usr = (await app.get_me()).username
                    raw_link = f"https://t.me/{bot_usr}?start={msg_id}"
                    final_link = await get_short_link(raw_link)

                    # ৪. পাবলিক চ্যানেলে পোস্ট
                    cap = CONFIG["caption"].format(caption=task.get('caption', 'Video')[:100])
                    btn = InlineKeyboardMarkup([[InlineKeyboardButton("📥 DOWNLOAD / WATCH 📥", url=final_link)]])
                    dest = int(CONFIG["public"])

                    if t_path and os.path.exists(t_path):
                        await app.send_photo(dest, t_path, caption=cap, reply_markup=btn)
                    else:
                        await app.send_message(dest, cap + "\n\n⚠️ No Thumb", reply_markup=btn)
                    
                    print(f"✅ Posted: {msg_id}")

                except Exception as e:
                    print(f"Error: {e}")
                
                # ক্লিনআপ
                await queue_col.delete_one({"_id": task["_id"]})
                try:
                    if os.path.exists(v_path): os.remove(v_path)
                    if t_path and os.path.exists(t_path): os.remove(t_path)
                except: pass
            
            # ইউজার সেট করা ইন্টারভাল অনুযায়ী অপেক্ষা
            await asyncio.sleep(CONFIG.get("interval", 30))

        except Exception as e:
            print(f"Loop Error: {e}"); await asyncio.sleep(10)

# ------------------- ৬. মেইন রানার -------------------
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(web_server())
    loop.create_task(processor())
    
    app.start()
    loop.run_until_complete(load_settings()) # সেটিংস লোড
    print("🤖 Bot Fully Active with All Commands!")
    idle()
    app.stop()
