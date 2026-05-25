import os, json, re, logging, tempfile, difflib, asyncio
from pathlib import Path
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from groq import Groq

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

API_ID        = int(os.environ["TELEGRAM_API_ID"])
API_HASH      = os.environ["TELEGRAM_API_HASH"]
SESSION       = os.environ["TELEGRAM_SESSION"]
GROQ_KEY      = os.environ["GROQ_API_KEY"]
CONTACTS_FILE = Path("/tmp/contacts.json")

groq_client = Groq(api_key=GROQ_KEY)
client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)

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

async def cmd_contacts(event):
    contacts = load_contacts()
    if not contacts:
        await event.reply(
            "Կոնտակտներ չկան:\n\n"
            "/add Անուն ID — ավելացնել"
        )
        return
    lines = []
    for i, (name, info) in enumerate(sorted(contacts.items()), 1):
        uname = f"  @{info['username']}" if info.get("username") else ""
        lines.append(f"{i}. {name}{uname}  {info['id']}")
    await event.reply(
        f"📋 Կոնտակտներ ({len(contacts)}):\n\n" + "\n".join(lines)
    )

async def cmd_add(event):
    parts = event.raw_text.strip().split()
    if len(parts) < 3 or not parts[-1].lstrip("-").isdigit():
        await event.reply(
            "Օգտագործում: /add Անուն TelegramID\n"
            "Օրինակ: /add Ani 123456789"
        )
        return
    uid  = int(parts[-1])
    name = " ".join(parts[1:-1]).capitalize()
    contacts = load_contacts()
    contacts[name] = {"id": uid, "username": ""}
    save_contacts(contacts)
    await event.reply(f"✅ {name} ավելացված է (ID: {uid})")

async def cmd_remove(event):
    parts = event.raw_text.strip().split()
    if len(parts) < 2:
        await event.reply("Օգտագործում: /remove Անուն")
        return
    name = " ".join(parts[1:]).capitalize()
    contacts = load_contacts()
    matched, _ = find_contact(name, contacts)
    if matched:
        del contacts[matched]
        save_contacts(contacts)
        await event.reply(f"🗑️ {matched} ջնջված է")
    else:
        await event.reply(f"❌ «{name}» չգտնվեց կոնտակտներում")

async def cmd_help(event):
    await event.reply(
        "🤖 Հրամաններ:\n\n"
        "/contacts — բոլոր կոնտակտները\n"
        "/add Ani 123456789 — ավելացնել\n"
        "/remove Ani — ջնջել\n"
        "/help — օգնություն\n\n"
        "📨 Ուղարկելու համար:\n"
        "• Write Ani Hello\n"
        "• Ani-ին գրիր Բարև\n"
        "• Կամ ձայնային հաղորդագրություն"
    )

async def do_send(event, contact_name, message):
    contacts = load_contacts()
    matched_name, entry = find_contact(contact_name, contacts)
    if entry is None:
        if not contacts:
            await event.reply("❌ Կոնտակտներ չկան: /add Անուն ID")
            return
        lines = "\n".join(f"• {n}" for n in sorted(contacts.keys()))
        await event.reply(f"❓ «{contact_name}» չգտնվեց:\n\n{lines}")
        return
    try:
        await client.send_message(entry["id"], message)
        await event.reply(f"✅ Ուղարկվեց {matched_name}-ին:\n«{message}»")
    except Exception as e:
        await event.reply(f"⚠️ Չհաջողվեց ուղարկել {matched_name}-ին:\n{e}")

async def handle_message(event):
    if event.raw_text.startswith("/contacts"):
        await cmd_contacts(event)
    elif event.raw_text.startswith("/add"):
        await cmd_add(event)
    elif event.raw_text.startswith("/remove"):
        await cmd_remove(event)
    elif event.raw_text.startswith("/help"):
        await cmd_help(event)
    else:
        contact_name, message = parse_send(event.raw_text)
        if contact_name:
            await do_send(event, contact_name, message)

async def handle_voice(event):
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp_path = tmp.name
    await client.download_media(event.message, tmp_path)
    try:
        text = await transcribe(tmp_path)
        await event.reply(f"📝 Լսեցի:\n{text}")
        contact_name, message = parse_send(text)
        if contact_name is None:
            await event.reply(
                "🤔 Հասկացա ձայնը, բայց հրաման չտեսա:\n\n"
                "Ասեք, օրինակ:\n• «Ani-ին գրիր Okay»\n• «Write Aram I'm coming»"
            )
            return
        await do_send(event, contact_name, message)
    except Exception as e:
        log.exception("Voice error")
        await event.reply(f"⚠️ Սխալ: {e}")
    finally:
        os.unlink(tmp_path)

async def main():
    await client.start()
    log.info("UserBot started ✅ — listening to yourself only")

    me = await client.get_me()
    my_id = me.id

    @client.on(events.NewMessage(from_users=my_id, outgoing=False))
    async def on_message(event):
        if event.voice:
            await handle_voice(event)
        elif event.raw_text:
            await handle_message(event)

    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
