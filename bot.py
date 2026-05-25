import os, json, re, logging, tempfile, difflib, asyncio
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, MessageHandler, CommandHandler,
    ContextTypes, CallbackQueryHandler, filters
)
from groq import Groq

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

BOT_TOKEN  = os.environ["TELEGRAM_BOT_TOKEN"]
GROQ_KEY   = os.environ["GROQ_API_KEY"]
CONTACTS_FILE = Path("/tmp/contacts.json")
groq_client = Groq(api_key=GROQ_KEY)

def load_contacts():
    if CONTACTS_FILE.exists():
        with open(CONTACTS_FILE) as f:
            data = json.load(f)
        migrated = {}
        for k, v in data.items():
            if isinstance(v, int):
                migrated[k] = {"id": v, "username": ""}
            else:
                migrated[k] = v
        return migrated
    return {}

def save_contacts(contacts):
    with open(CONTACTS_FILE, "w") as f:
        json.dump(contacts, f, ensure_ascii=False, indent=2)

def find_contact(name, contacts):
    nl = name.lower()
    for k, v in contacts.items():
        if k.lower() == nl:
            return k, v
    keys = list(contacts.keys())
    close = difflib.get_close_matches(name, keys, n=1, cutoff=0.6)
    if close:
        return close[0], contacts[close[0]]
    return None, None

async def transcribe(ogg_path):
    with open(ogg_path, "rb") as f:
        result = groq_client.audio.transcriptions.create(
            model="whisper-large-v3",
            file=f,
            language="hy",
            response_format="text"
        )
    return result.strip()

SEND_PATTERNS = [
    r"(?P<name>\w+)[- ]?ին\s+(?:գրիր|ուղարկիր|ասա|փոխանցիր)\s+(?P<msg>.+)",
    r"(?:write|send(?:\s+(?:a\s+)?message(?:\s+to)?)?)\s+(?P<name>\w+)\s+(?P<msg>.+)",
    r"(?:hey[,\s]+)?(?:i\s+need\s+(?:you\s+)?to\s+)?(?:write|send)\s+(?P<name>\w+)\s+(?P<msg>.+)",
]

def parse_send(text):
    for pat in SEND_PATTERNS:
        m = re.search(pat, text.strip(), re.IGNORECASE)
        if m:
            return m.group("name").capitalize(), m.group("msg").strip()
    return None, None

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    contacts = load_contacts()
    already_saved = any(str(c.get("id")) == str(user.id) for c in contacts.values())
    if not already_saved:
        key = user.first_name.capitalize()
        base = key
        i = 2
        while key in contacts:
            key = f"{base}{i}"
            i += 1
        contacts[key] = {"id": user.id, "username": user.username or ""}
        save_contacts(contacts)
    await update.message.reply_text(
        f"Բարև <b>{user.first_name}</b>! 👋\n\n"
        f"🆔 Ձեր ID: <code>{user.id}</code>\n\n"
        "🎙️ Ուղարկեք ձայնային հաղորդագրություն հայերեն, ռուսերեն կամ անգլերեն:\n\n"
        "<b>Ձայնային հրամաններ:</b>\n"
        "• «Ani-ին գրիր Okay»\n"
        "• «Aram-ին ուղարկիր Բարև»\n"
        "• «Write Sona I'm running late»\n\n"
        "<b>Հրամաններ:</b>\n"
        "/contacts — բոլոր կոնտակտները\n"
        "/add Ani 123456789 — ավելացնել\n"
        "/remove Ani — ջնջել\n"
        "/myid — ձեր ID-ն\n"
        "/invite — հրավիրել ընկերոջը",
        parse_mode="HTML"
    )

async def cmd_myid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await update.message.reply_text(
        f"👤 <b>{u.first_name}</b>\n"
        f"🆔 ID: <code>{u.id}</code>\n"
        f"📛 Username: {'@' + u.username if u.username else '(none)'}",
        parse_mode="HTML"
    )

async def cmd_invite(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    me = await ctx.bot.get_me()
    link = f"https://t.me/{me.username}"
    await update.message.reply_text(
        f"📨 Ուղարկեք այս հղումը ձեր ընկերոջը:\n\n<b>{link}</b>\n\n"
        "Երբ նա սեղմի Start, ավտոմատ կավելացվի ձեր կոնտակտներին ✅",
        parse_mode="HTML"
    )

async def cmd_contacts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    contacts = load_contacts()
    if not contacts:
        await update.message.reply_text(
            "Կոնտակտներ չկան:\n\n"
            "1️⃣ /invite — ուղարկեք հղումն ընկերոջը\n"
            "2️⃣ /add Անուն ID — ձեռքով ավելացնել"
        )
        return
    lines = []
    for i, (name, info) in enumerate(sorted(contacts.items()), 1):
        uname = f"  @{info['username']}" if info.get("username") else ""
        lines.append(f"{i}. <b>{name}</b>{uname}  <code>{info['id']}</code>")
    await update.message.reply_text(
        f"<b>📋 Կոնտակտներ ({len(contacts)}):</b>\n\n" + "\n".join(lines),
        parse_mode="HTML"
    )

async def cmd_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if len(args) < 2 or not args[-1].lstrip("-").isdigit():
        await update.message.reply_text(
            "Օգտագործում: /add Անուն TelegramID\n"
            "Օրինակ: /add Ani 123456789"
        )
        return
    uid  = int(args[-1])
    name = " ".join(args[:-1]).capitalize()
    contacts = load_contacts()
    contacts[name] = {"id": uid, "username": ""}
    save_contacts(contacts)
    await update.message.reply_text(
        f"✅ <b>{name}</b> ավելացված է (ID: <code>{uid}</code>)", parse_mode="HTML"
    )

async def cmd_remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Օգտագործում: /remove Անուն")
        return
    name = " ".join(ctx.args).capitalize()
    contacts = load_contacts()
    matched, _ = find_contact(name, contacts)
    if matched:
        del contacts[matched]
        save_contacts(contacts)
        await update.message.reply_text(f"🗑️ <b>{matched}</b> ջնջված է:", parse_mode="HTML")
    else:
        await update.message.reply_text(f"❌ «{name}» չգտնվեց կոնտակտներում:")

async def do_send(update: Update, ctx, contact_name, message):
    contacts = load_contacts()
    matched_name, entry = find_contact(contact_name, contacts)
    if entry is None:
        if not contacts:
            await update.message.reply_text("❌ Կոնտակտներ չկան: /add Անուն ID")
            return
        keyboard = [
            [InlineKeyboardButton(n, callback_data=f"send|{n}|{message}")]
            for n in sorted(contacts.keys())
        ]
        keyboard.append([InlineKeyboardButton("❌ Չեղարկել", callback_data="cancel")])
        await update.message.reply_text(
            f"❓ «{contact_name}» չգտնվեց: Ո՞ւմ ուղարկե՞մ «{message}»-ը:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    try:
        await ctx.bot.send_message(chat_id=entry["id"], text=message)
        await update.message.reply_text(
            f"✅ Ուղարկվեց <b>{matched_name}</b>-ին:\n«{message}»", parse_mode="HTML"
        )
    except Exception as e:
        await update.message.reply_text(
            f"⚠️ Չհաջողվեց ուղարկել <b>{matched_name}</b>-ին:\n{e}\n\n"
            f"Խնդրեք {matched_name}-ին ուղարկի /start բոտին մեկ անգամ:",
            parse_mode="HTML"
        )

async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "cancel":
        await query.edit_message_text("❌ Չեղարկված:")
        return
    if data.startswith("send|"):
        _, name, message = data.split("|", 2)
        contacts = load_contacts()
        _, entry = find_contact(name, contacts)
        if entry:
            try:
                await ctx.bot.send_message(chat_id=entry["id"], text=message)
                await query.edit_message_text(
                    f"✅ Ուղարկվեց <b>{name}</b>-ին:\n«{message}»", parse_mode="HTML"
                )
            except Exception as e:
                await query.edit_message_text(f"⚠️ Սխալ: {e}")

async def handle_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    status = await msg.reply_text("🎙️ Ստանում եմ ձայնը...")
    voice_file = await ctx.bot.get_file(msg.voice.file_id)
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp_path = tmp.name
    await voice_file.download_to_drive(tmp_path)
    try:
        await status.edit_text("🔄 Ճանաչում եմ ձայնը...")
        text = await transcribe(tmp_path)
        await status.edit_text(f"📝 Լսեցի:\n<i>{text}</i>", parse_mode="HTML")
        contact_name, message = parse_send(text)
        if contact_name is None:
            await msg.reply_text(
                "🤔 Հասկացա ձայնը, բայց ուղարկելու հրաման չտեսա:\n\n"
                "Ասեք, օրինակ:\n• «Ani-ին գրիր Okay»\n• «Write Aram I'm coming»"
            )
            return
        await do_send(update, ctx, contact_name, message)
    except Exception as e:
        log.exception("Voice error")
        await msg.reply_text(f"⚠️ Սխալ: {e}")
    finally:
        os.unlink(tmp_path)

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    contact_name, message = parse_send(update.message.text)
    if contact_name:
        await do_send(update, ctx, contact_name, message)

def main():
    asyncio.set_event_loop(asyncio.new_event_loop())

    PORT = int(os.environ.get("PORT", 8443))
    WEBHOOK_URL = os.environ["RENDER_EXTERNAL_URL"]

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",         cmd_start))
    app.add_handler(CommandHandler("myid",          cmd_myid))
    app.add_handler(CommandHandler("invite",        cmd_invite))
    app.add_handler(CommandHandler("contacts",      cmd_contacts))
    app.add_handler(CommandHandler("add",           cmd_add))
    app.add_handler(CommandHandler("remove",        cmd_remove))
    app.add_handler(CommandHandler("add_contact",   cmd_add))
    app.add_handler(CommandHandler("list_contacts", cmd_contacts))
    app.add_handler(CommandHandler("del_contact",   cmd_remove))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.VOICE,   handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    log.info("Bot started ✅")

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=f"{WEBHOOK_URL}/webhook",
        url_path="webhook",
    )

if __name__ == "__main__":
    main()
