# Xelacis — Telegram Userbot

A personal Telegram userbot that lets you send messages to contacts and groups using natural language — by text or voice — in Armenian, English, or Russian. Powered by Groq (Whisper + LLaMA).

---

## Features

- Send messages by saying or typing the recipient's name in any language
- Voice message transcription with Armenian language support
- Armenian-to-Latin transliteration for fuzzy contact matching
- Built-in AI assistant (Xelacis) via LLaMA 3.3 70B
- Auto-sync contacts and group chats from Telegram
- Disambiguation prompts when multiple contacts match
- Health check endpoint for deployment on Render

---

## Commands

| Command | Description |
|---|---|
| `/sync` | Sync contacts from Telegram |
| `/contacts` | List all contacts |
| `/add Name ID` | Manually add a contact |
| `/remove Name` | Remove a contact |
| `/syncchats` | Sync group chats |
| `/chats` | List all group chats |
| `/help` | Show help |

---

## Natural Language Usage

Send messages by typing naturally:

```
Write Ani I'll be late
Անի-ին գրիր Բարև
Work chat-ին գրիր Meeting at 3
```

Ask the assistant:

```
Xelacis, what should I reply to Ani?
Xelacis, translate this to formal Armenian
Xelacis, ինչ գրեմ հարցազրույցի համար
```

Or say any of the above as a voice message.

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/your-username/xelacis-userbot.git
cd xelacis-userbot
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Generate a Telethon session string

Run this once locally to get your session string:

```python
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

API_ID = your_api_id        # integer, no quotes
API_HASH = "your_api_hash"
PHONE = "+1234567890"

with TelegramClient(StringSession(), API_ID, API_HASH) as client:
    client.start(phone=PHONE)
    print("Your session string:")
    print(client.session.save())
```

It will send a Telegram login code to your phone. After you enter it, the session string is printed to the terminal. Copy it — that is your `TELEGRAM_SESSION` value.

### 4. Set environment variables

| Variable | Description |
|---|---|
| `TELEGRAM_API_ID` | From [my.telegram.org](https://my.telegram.org) |
| `TELEGRAM_API_HASH` | From [my.telegram.org](https://my.telegram.org) |
| `TELEGRAM_SESSION` | Telethon StringSession from step 3 |
| `GROQ_API_KEY` | From [console.groq.com](https://console.groq.com) |

### 5. Run locally

```bash
python bot.py
```

The bot only responds to messages you send to yourself (Saved Messages).

---

## Deployment on Render

The repo includes a `render.yaml` for one-click deployment as a web service.

1. Push the repo to GitHub
2. Create a new Web Service on [render.com](https://render.com) and connect the repo
3. Set the four environment variables in the Render dashboard
4. Deploy

The bot pings itself every 10 minutes to stay alive on free-tier instances.

---

## How Contact Matching Works

When you say or type a name, the bot:

1. Strips Armenian grammatical suffixes (e.g. `-ին`, `-ի`, `-ուն`)
2. Transliterates Armenian script to Latin
3. Tries exact match, then prefix match, then fuzzy match (difflib), then substring match
4. If multiple contacts match, it lists them and asks you to pick by number
5. Type `0` to cancel a pending selection

---

## Project Structure

```
.
├── bot.py              # Main bot logic
├── requirements.txt    # Python dependencies
└── render.yaml         # Render deployment config
```

---

## Tech Stack

- [Telethon](https://github.com/LonamiWebs/Telethon) — Telegram MTProto client
- [Groq](https://console.groq.com) — Whisper large-v3 transcription and LLaMA 3.3 70B inference
- [aiohttp](https://docs.aiohttp.org) — lightweight health check web server

---

## Notes

- This is a userbot, meaning it runs as your personal Telegram account, not a bot account. Keep your session string private.
- Contacts and chats are cached locally in `/tmp/contacts.json` and `/tmp/chats.json`. Run `/sync` and `/syncchats` after first deploy.
- Voice messages must be sent to your own Saved Messages chat for the bot to process them.
