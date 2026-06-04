import os, json, re, logging, tempfile, difflib, asyncio
from pathlib import Path
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.contacts import GetContactsRequest
from groq import Groq
from aiohttp import web
import aiohttp

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

API_ID        = int(os.environ["TELEGRAM_API_ID"])
API_HASH      = os.environ["TELEGRAM_API_HASH"]
SESSION       = os.environ["TELEGRAM_SESSION"]
GROQ_KEY      = os.environ["GROQ_API_KEY"]
CONTACTS_FILE = Path("/tmp/contacts.json")
CHATS_FILE    = Path("/tmp/chats.json")

groq_client = Groq(api_key=GROQ_KEY)
client = TelegramClient(StringSession(SESSION), API_ID, API_HASH)

AM_LETTERS = {
    'Ա': 'A', 'ա': 'a', 'Բ': 'B', 'բ': 'b', 'Գ': 'G', 'գ': 'g',
    'Դ': 'D', 'դ': 'd', 'Ե': 'Ye', 'ե': 'ye', 'Զ': 'Z', 'զ': 'z',
    'Է': 'E', 'է': 'e', 'Ը': 'E', 'ը': 'e', 'Թ': 'T', 'թ': 't',
    'Ժ': 'Zh', 'ժ': 'zh', 'Ի': 'I', 'ի': 'i', 'Լ': 'L', 'լ': 'l',
    'Խ': 'Kh', 'խ': 'kh', 'Ծ': 'Ts', 'ծ': 'ts', 'Կ': 'K', 'կ': 'k',
    'Հ': 'H', 'հ': 'h', 'Ձ': 'Dz', 'ձ': 'dz', 'Ղ': 'Gh', 'ղ': 'gh',
    'Ճ': 'Ch', 'ճ': 'ch', 'Մ': 'M', 'մ': 'm', 'Յ': 'Y', 'յ': 'y',
    'Ն': 'N', 'ն': 'n', 'Շ': 'Sh', 'շ': 'sh', 'Ո': 'Vo', 'ո': 'vo',
    'Չ': 'Ch', 'չ': 'ch', 'Պ': 'P', 'պ': 'p', 'Ջ': 'J', 'ջ': 'j',
    'Ռ': 'R', 'ռ': 'r', 'Ս': 'S', 'ս': 's', 'Վ': 'V', 'վ': 'v',
    'Տ': 'T', 'տ': 't', 'Ր': 'R', 'ր': 'r', 'Ց': 'Ts', 'ց': 'ts',
    'Փ': 'P', 'փ': 'p', 'Ք': 'K', 'ք': 'k', 'Օ': 'O', 'օ': 'o',
    'Ֆ': 'F', 'ֆ': 'f', 'ու': 'u', 'Ու': 'U',
}

def transliterate(name):
    result = ''
    i = 0
    while i < len(name):
        if i + 1 < len(name) and name[i:i+2] in AM_LETTERS:
            result += AM_LETTERS[name[i:i+2]]
            i += 2
        elif name[i] in AM_LETTERS:
            result += AM_LETTERS[name[i]]
            i += 1
        else:
            result += name[i]
            i += 1
    return result

def strip_armenian_suffix(name):
    return re.sub(r'ային$|յին$|ուն$|ին$|ի$', '', name)

def to_latin(name: str) -> str:
    name = name.strip()
    if any('\u0531' <= c <= '\u0587' for c in name):
        name = strip_armenian_suffix(name)
        name = transliterate(name)
    return name.lower()

def find_in_dict(spoken_name: str, store: dict):
    """
    Generic fuzzy finder used for both contacts and chats.
    Returns (matched_key, entry) or (None, [list]) or (None, None).
    """
    latin = to_latin(spoken_name)
    log.info(f"Looking for '{spoken_name}' → normalized '{latin}'")

    for k in store:
        if k.lower() == latin:
            return k, store[k]

    starts = [k for k in store if k.lower().startswith(latin)]
    if len(starts) == 1:
        return starts[0], store[starts[0]]
    if len(starts) > 1:
        return None, starts

    keys_lower = {k.lower(): k for k in store}
    close_lower = difflib.get_close_matches(latin, keys_lower.keys(), n=5, cutoff=0.5)
    close = [keys_lower[c] for c in close_lower]
    if len(close) == 1:
        return close[0], store[close[0]]
    if len(close) > 1:
        return None, close

    substr = [k for k in store if latin in k.lower() or k.lower() in latin]
    if len(substr) == 1:
        return substr[0], store[substr[0]]
    if len(substr) > 1:
        return None, substr

    return None, None

# Keep old name as alias so existing call sites work
def find_contact(spoken_name, contacts):
    return find_in_dict(spoken_name, contacts)

# ── Contacts storage ──────────────────────────────────────────────────────────

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

# ── Chats storage ─────────────────────────────────────────────────────────────

def load_chats():
    if CHATS_FILE.exists():
        with open(CHATS_FILE) as f:
            return json.load(f)
    return {}

def save_chats(chats):
    with open(CHATS_FILE, "w") as f:
        json.dump(chats, f, ensure_ascii=False, indent=2)

# ── Transcription ─────────────────────────────────────────────────────────────

async def transcribe(ogg_path):
    with open(ogg_path, "rb") as f:
        result = groq_client.audio.transcriptions.create(
            model="whisper-large-v3",
            file=f,
            language="hy",
            response_format="verbose_json",
            prompt="Արևելահայերեն։ Անի, Արամ, Մարի, գրիր, ուղարկիր, բարև, լավ եմ։"
        )
    text = result.text.strip()
    log.info(f"Whisper raw output: {text}")
    return text

# ── Send pattern parsing ──────────────────────────────────────────────────────

SEND_PATTERNS = [
    r"(?P<name>[\w\u0531-\u0587]+)[- ]?ին\s+(?:գրիր|ուղարկիր|ասա|փոխանցիր)\s+(?P<msg>.+)",
    r"(?P<name>[\w\u0531-\u0587]+)ային\s+(?:գրիր|ուղարկիր|ասա|փոխանցիր)\s+(?P<msg>.+)",
    r"(?:write|send(?:\s+(?:a\s+)?message(?:\s+to)?)?)\s+(?P<name>\w+)\s+(?P<msg>.+)",
    r"(?:hey[,\s]+)?(?:i\s+need\s+(?:you\s+)?to\s+)?(?:write|send)\s+(?P<name>\w+)\s+(?P<msg>.+)",
]

def parse_send(text):
    for pat in SEND_PATTERNS:
        m = re.search(pat, text.strip(), re.IGNORECASE)
        if m:
            return m.group("name"), m.group("msg").strip()
    return None, None

pending_sends = {}

# ── Commands ──────────────────────────────────────────────────────────────────

async def cmd_sync(event):
    await event.reply("🔄 Սինքրոնիզացնում եմ կոնտակտները...")
    try:
        result = await client(GetContactsRequest(hash=0))
        contacts = load_contacts()
        count = 0
        for user in result.users:
            if user.bot:
                continue
            name = user.first_name or ""
            if user.last_name:
                name += f" {user.last_name}"
            name = name.strip().capitalize()
            if not name:
                continue
            base = name
            i = 2
            while name in contacts and contacts[name]["id"] != user.id:
                name = f"{base}{i}"
                i += 1
            contacts[name] = {"id": user.id, "username": user.username or ""}
            count += 1
        save_contacts(contacts)
        await event.reply(f"✅ {count} կոնտակտ սինքրոնիզացվեց!")
    except Exception as e:
        log.exception("Sync error")
        await event.reply(f"⚠️ Սխալ: {e}")

async def cmd_sync_chats(event):
    """Sync group chats from recent dialogs."""
    await event.reply("🔄 Սինքրոնիզացնում եմ խմբային չաթերը...")
    try:
        chats = load_chats()
        count = 0
        async for dialog in client.iter_dialogs():
            # Only group chats (not channels, not private)
            if not dialog.is_group:
                continue
            name = (dialog.name or "").strip()
            if not name:
                continue
            chats[name] = {"id": dialog.id}
            count += 1
        save_chats(chats)
        await event.reply(f"✅ {count} խմբային չաթ սինքրոնիզացվեց!")
    except Exception as e:
        log.exception("Sync chats error")
        await event.reply(f"⚠️ Սխալ: {e}")

async def cmd_chats(event):
    chats = load_chats()
    if not chats:
        await event.reply(
            "Խմբային չաթեր չկան:\n\n"
            "/syncchats — ավտոմատ սինքրոնիզացնել"
        )
        return
    lines = [f"{i}. {name}  {info['id']}"
             for i, (name, info) in enumerate(sorted(chats.items()), 1)]
    await event.reply(f"💬 Խմբային չաթեր ({len(chats)}):\n\n" + "\n".join(lines))

async def cmd_contacts(event):
    contacts = load_contacts()
    if not contacts:
        await event.reply(
            "Կոնտակտներ չկան:\n\n"
            "/sync — ավտոմատ սինքրոնիզացնել\n"
            "/add Անուն ID — ձեռքով ավելացնել"
        )
        return
    lines = []
    for i, (name, info) in enumerate(sorted(contacts.items()), 1):
        uname = f"  @{info['username']}" if info.get("username") else ""
        lines.append(f"{i}. {name}{uname}  {info['id']}")
    await event.reply(f"📋 Կոնտակտներ ({len(contacts)}):\n\n" + "\n".join(lines))

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
        "👤 Կոնտակտներ\n"
        "/sync — սինքրոնիզացնել կոնտակտները\n"
        "/contacts — բոլոր կոնտակտները\n"
        "/add Ani 123456789 — ձեռքով ավելացնել\n"
        "/remove Ani — ջնջել\n\n"
        "💬 Խմբային չաթեր\n"
        "/syncchats — սինքրոնիզացնել խմբային չաթերը\n"
        "/chats — բոլոր խմբային չաթերը\n\n"
        "/help — օգնություն\n\n"
        "📨 Ուղարկելու համար:\n"
        "• Write Ani Hello\n"
        "• Անի-ին գրիր Բարև\n"
        "• Work chat-ին գրիր Meeting at 3\n"
        "• Կամ ձայնային հաղորդագրություն"
    )

# ── Core send logic ───────────────────────────────────────────────────────────

async def do_send(event, target_name, message):
    contacts = load_contacts()
    chats    = load_chats()

    # Search contacts first, then group chats
    matched_name, entry = find_in_dict(target_name, contacts)
    source = "contact"

    if entry is None and matched_name is None:
        # Try group chats
        matched_name, entry = find_in_dict(target_name, chats)
        source = "chat"

    # Still nothing — show combined list
    if entry is None and matched_name is None:
        if not contacts and not chats:
            await event.reply("❌ Կոնտակտներ և չաթեր չկան:\n/sync  /syncchats")
            return
        combined = sorted(contacts.keys()) + sorted(chats.keys())
        latin = to_latin(target_name)
        await event.reply(
            f"❓ «{latin}» չգտնվեց:\n\n" +
            "\n".join(f"{i+1}. {n}" for i, n in enumerate(combined)) +
            "\n\nՊատասխանեք համարով կամ 0՝ չեղարկելու:"
        )
        pending_sends[event.chat_id] = {
            "contacts": combined,
            "message": message,
            "contacts_keys": sorted(contacts.keys()),
            "chats_keys": sorted(chats.keys()),
        }
        return

    # Multiple matches — ask user to choose
    if isinstance(entry, list):
        latin = to_latin(target_name)
        await event.reply(
            f"❓ «{latin}» — մի քանի նմանատիպ:\n\n" +
            "\n".join(f"{i+1}. {n}" for i, n in enumerate(entry)) +
            "\n\nՊատասխանեք համարով կամ 0՝ չեղարկելու:"
        )
        pending_sends[event.chat_id] = {
            "contacts": entry,
            "message": message,
            "contacts_keys": sorted(contacts.keys()),
            "chats_keys": sorted(chats.keys()),
        }
        return

    # Single match — send
    target_id = entry["id"]
    try:
        await client.send_message(target_id, message)
        icon = "💬" if source == "chat" else "✅"
        await event.reply(f"{icon} Ուղարկվեց {matched_name}-ին:\n«{message}»")
    except Exception as e:
        await event.reply(f"⚠️ Չհաջողվեց ուղարկել {matched_name}-ին:\n{e}")

# ── Message & voice handlers ──────────────────────────────────────────────────

async def handle_message(event):
    chat_id = event.chat_id

    # Resolve pending contact/chat selection
    if chat_id in pending_sends and event.raw_text.strip().isdigit():
        choice = int(event.raw_text.strip()) - 1
        pending = pending_sends.pop(chat_id)
        names   = pending["contacts"]   # combined list shown to user
        message = pending["message"]
        contacts_keys = pending.get("contacts_keys", [])
        chats_keys    = pending.get("chats_keys", [])

        if choice == -1:
            await event.reply("❌ Չեղարկված")
            return
        if not (0 <= choice < len(names)):
            await event.reply("❌ Սխալ համար")
            return

        name = names[choice]
        contacts = load_contacts()
        chats    = load_chats()

        # Figure out if the chosen name is a contact or a chat
        if name in contacts:
            entry = contacts[name]
        elif name in chats:
            entry = chats[name]
        else:
            # Fallback fuzzy search across both
            _, entry = find_in_dict(name, {**contacts, **chats})

        if entry and not isinstance(entry, list):
            try:
                await client.send_message(entry["id"], message)
                await event.reply(f"✅ Ուղարկվեց {name}-ին:\n«{message}»")
            except Exception as e:
                await event.reply(f"⚠️ Սխալ: {e}")
        else:
            await event.reply("⚠️ Կոնտակտը չգտնվեց, փորձեք կրկին")
        return

    if event.raw_text.startswith("/syncchats"):
        await cmd_sync_chats(event)
    elif event.raw_text.startswith("/chats"):
        await cmd_chats(event)
    elif event.raw_text.startswith("/sync"):
        await cmd_sync(event)
    elif event.raw_text.startswith("/contacts"):
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
        await event.reply(f"📝 Լսեցի:\n`{text}`")
        contact_name, message = parse_send(text)
        if contact_name is None:
            await event.reply(
                "🤔 Հասկացա ձայնը, բայց հրաման չտեսա:\n\n"
                "Ասեք, օրինակ:\n• «Անի-ին գրիր Okay»\n• «Write Aram I'm coming»"
            )
            return
        await do_send(event, contact_name, message)
    except Exception as e:
        log.exception("Voice error")
        await event.reply(f"⚠️ Սխալ: {e}")
    finally:
        os.unlink(tmp_path)

# ── Keep-alive & watchdog ─────────────────────────────────────────────────────

async def keep_alive(url: str):
    await asyncio.sleep(60)
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    log.info(f"Keep-alive ping → {resp.status}")
            except Exception as e:
                log.warning(f"Keep-alive ping failed: {e}")
            await asyncio.sleep(10 * 60)

async def watchdog():
    await asyncio.sleep(30)
    while True:
        await asyncio.sleep(60)
        if not client.is_connected():
            log.warning("Telethon disconnected — reconnecting...")
            try:
                await client.connect()
                log.info("Reconnected ✅")
            except Exception as e:
                log.error(f"Reconnect failed: {e}")

# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    await client.start()
    log.info("UserBot started ✅ — listening to yourself only")

    me = await client.get_me()
    my_id = me.id

    @client.on(events.NewMessage(outgoing=True))
    async def on_message(event):
        if event.chat_id != my_id:
            return
        if event.voice:
            await handle_voice(event)
        elif event.raw_text:
            await handle_message(event)

    async def handle_health(request):
        return web.Response(text="OK")

    app = web.Application()
    app.router.add_get("/", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info(f"Health check running on port {port}")

    service_url = os.environ.get("RENDER_EXTERNAL_URL", f"http://localhost:{port}")
    log.info(f"Keep-alive target: {service_url}")

    asyncio.create_task(keep_alive(service_url))
    asyncio.create_task(watchdog())

    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
