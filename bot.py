import os
import json
import re
import logging
import asyncio
import tempfile
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application, MessageHandler, CommandHandler,
    ContextTypes, filters
)
import openai
import httpx

# ── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────
BOT_TOKEN   = os.environ["TELEGRAM_BOT_TOKEN"]
OPENAI_KEY  = os.environ["OPENAI_API_KEY"]

# contacts.json  →  { "Ani": 123456789, "Aram": 987654321, ... }
CONTACTS_FILE = Path(__file__).parent / "contacts.json"

openai_client = openai.OpenAI(api_key=OPENAI_KEY)


def load_contacts() -> dict[str, int]:
    if CONTACTS_FILE.exists():
        with open(CONTACTS_FILE) as f:
            return json.load(f)
    return {}


def save_contacts(contacts: dict[str, int]):
    with open(CONTACTS_FILE, "w") as f:
        json.dump(contacts, f, ensure_ascii=False, indent=2)


# ── Voice → Text (Whisper) ─────────────────────────────────────────────────
async def transcribe_voice(ogg_path: str) -> str:
    """Transcribe an OGG voice file using Whisper; hint Armenian."""
    with open(ogg_path, "rb") as audio_file:
        result = openai_client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="hy",          # ISO-639-1 for Armenian
            response_format="text"
        )
    return result.strip()


# ── Intent Parser ──────────────────────────────────────────────────────────
# Handles both Armenian and transliterated/mixed phrases:
#   "Ani-ին գրիր Okay"
#   "Ani-ին ուղարկիր բարև"
#   "write Ani OK"
#   "send message to Aram hello"
SEND_PATTERNS = [
    # Armenian: "<name>-ին գրիր/ուղարկիր <message>"
    r"(?P<name>\w+)[- ]?ին\s+(?:գրիր|ուղարկիր)\s+(?P<msg>.+)",
    # English-style: "write/send <name> <message>"
    r"(?:write|send(?:\s+message(?:\s+to)?)?)\s+(?P<name>\w+)\s+(?P<msg>.+)",
    # "Hey ... write Ani OK"
    r"(?:hey[,\s]+)?(?:i\s+need\s+you\s+to\s+)?(?:write|send)\s+(?P<name>\w+)\s+(?P<msg>.+)",
]

def parse_send_intent(text: str) -> tuple[str, str] | None:
    """Return (contact_name, message) or None."""
    clean = text.strip()
    for pat in SEND_PATTERNS:
        m = re.search(pat, clean, re.IGNORECASE)
        if m:
            return m.group("name").capitalize(), m.group("msg").strip()
    return None


# ── Handlers ───────────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    name = update.effective_user.first_name
    await update.message.reply_text(
        f"Բարև {name}! 👋\n\n"
        f"Ձեր Telegram ID-ն է: <code>{uid}</code>\n\n"
        "Ես ձայնային հաղորդագրություններ եմ ընդունում հայերեն 🎙️\n\n"
        "<b>Հրամաններ:</b>\n"
        "/add_contact Ani 123456789  — ավելացնել կոնտակտ\n"
        "/list_contacts              — տեսնել բոլոր կոնտակտները\n"
        "/del_contact Ani            — ջնջել կոնտակտ\n\n"
        "<b>Օրինակ ձայնային հրաման:</b>\n"
        "\"Ani-ին գրիր Okay\"\n"
        "\"Write Ani I'm on my way\"",
        parse_mode="HTML"
    )


async def cmd_add_contact(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Usage: /add_contact Name 123456789"""
    args = ctx.args
    if len(args) != 2 or not args[1].lstrip("-").isdigit():
        await update.message.reply_text(
            "Օգտագործում: /add_contact Անուն TelegramID\n"
            "Օրինակ: /add_contact Ani 123456789"
        )
        return
    name, uid = args[0].capitalize(), int(args[1])
    contacts = load_contacts()
    contacts[name] = uid
    save_contacts(contacts)
    await update.message.reply_text(f"✅ {name} ավելացված է (ID: {uid})")


async def cmd_list_contacts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    contacts = load_contacts()
    if not contacts:
        await update.message.reply_text("Կոնտակտներ չկան։ Ավելացրեք /add_contact հրամանով։")
        return
    lines = "\n".join(f"• {n}: <code>{uid}</code>" for n, uid in contacts.items())
    await update.message.reply_text(f"<b>Կոնտակտներ:</b>\n{lines}", parse_mode="HTML")


async def cmd_del_contact(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Օգտագործում: /del_contact Անուն")
        return
    name = ctx.args[0].capitalize()
    contacts = load_contacts()
    if name in contacts:
        del contacts[name]
        save_contacts(contacts)
        await update.message.reply_text(f"🗑️ {name} ջնջված է։")
    else:
        await update.message.reply_text(f"❌ {name} կոնտակտներում չկա։")


async def handle_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    await msg.reply_text("🎙️ Ձայնը ստացվեց, մշակում եմ...")

    # 1. Download voice file
    voice_file = await ctx.bot.get_file(msg.voice.file_id)
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp_path = tmp.name
    await voice_file.download_to_drive(tmp_path)

    try:
        # 2. Transcribe
        text = await transcribe_voice(tmp_path)
        await msg.reply_text(f"📝 Ճանաչված տեքստ:\n<i>{text}</i>", parse_mode="HTML")

        # 3. Parse intent
        result = parse_send_intent(text)
        if result is None:
            await msg.reply_text(
                "🤔 Հասկացա ձայնը, բայց հաղորդագրություն ուղարկելու հրաման չհայտնաբերեցի։\n"
                "Ասեք, օրինակ՝ «Ani-ին գրիր Okay»"
            )
            return

        contact_name, outgoing_msg = result
        contacts = load_contacts()

        # Fuzzy match — case-insensitive
        match = next(
            (uid for name, uid in contacts.items()
             if name.lower() == contact_name.lower()),
            None
        )
        if match is None:
            await msg.reply_text(
                f"❌ «{contact_name}» կոնտակտներում չկա։\n"
                f"Ավելացրեք՝ /add_contact {contact_name} <TelegramID>"
            )
            return

        # 4. Send the message
        await ctx.bot.send_message(
            chat_id=match,
            text=outgoing_msg
        )
        await msg.reply_text(
            f"✅ «{outgoing_msg}» հաղորդագրությունն ուղարկվեց {contact_name}-ին։"
        )

    except Exception as e:
        log.exception("Error processing voice")
        await msg.reply_text(f"⚠️ Սխալ տեղի ունեցավ: {e}")
    finally:
        os.unlink(tmp_path)


async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Also handle plain text commands (for testing without voice)."""
    text = update.message.text
    result = parse_send_intent(text)
    if result:
        contact_name, outgoing_msg = result
        contacts = load_contacts()
        match = next(
            (uid for name, uid in contacts.items()
             if name.lower() == contact_name.lower()),
            None
        )
        if match is None:
            await update.message.reply_text(
                f"❌ «{contact_name}» կոնտակտներում չկա։\n"
                f"Ավելացրեք՝ /add_contact {contact_name} <TelegramID>"
            )
            return
        await ctx.bot.send_message(chat_id=match, text=outgoing_msg)
        await update.message.reply_text(
            f"✅ «{outgoing_msg}» հաղորդագրությունն ուղարկվեց {contact_name}-ին։"
        )


# ── Main ───────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",         cmd_start))
    app.add_handler(CommandHandler("add_contact",   cmd_add_contact))
    app.add_handler(CommandHandler("list_contacts", cmd_list_contacts))
    app.add_handler(CommandHandler("del_contact",   cmd_del_contact))
    app.add_handler(MessageHandler(filters.VOICE,   handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    log.info("Bot is running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
