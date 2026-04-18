"""
get_chat_ids.py  ─  P.R.O.F. Helper Script
───────────────────────────────────────────
Run this ONCE after creating your Telegram bot and having each teacher
(and yourself, for the student group) send a message to the bot.

Usage:
    python3 get_chat_ids.py

The script will print all recent chats with their IDs. Copy those IDs
into routine.json (for teachers) and .env (for the student group).
"""

import json
import urllib.request
import urllib.parse
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    print("ERROR: TELEGRAM_BOT_TOKEN not found in .env")
    exit(1)

url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
print(f"Fetching updates from Telegram...\n")

try:
    with urllib.request.urlopen(url, timeout=10) as resp:
        data = json.loads(resp.read().decode())
except Exception as e:
    print(f"Error connecting to Telegram: {e}")
    exit(1)

if not data.get("ok"):
    print(f"Telegram API error: {data}")
    exit(1)

updates = data.get("result", [])
if not updates:
    print("No updates found. Make sure each teacher has sent at least ONE message to your bot.")
    print("Ask them to open Telegram, find your bot, and type /start or any message.")
    exit(0)

seen = {}
for update in updates:
    msg = update.get("message") or update.get("channel_post", {})
    if not msg:
        continue
    chat = msg.get("chat", {})
    cid = chat.get("id")
    ctype = chat.get("type", "unknown")
    name = (
        chat.get("title")                       # groups / channels
        or f"{chat.get('first_name', '')} {chat.get('last_name', '')}".strip()
        or chat.get("username", "Unknown")
    )
    if cid and cid not in seen:
        seen[cid] = {"name": name, "type": ctype, "id": cid}

print("=" * 55)
print(f"{'NAME':<30} {'TYPE':<12} {'CHAT ID'}")
print("=" * 55)
for info in seen.values():
    print(f"{info['name']:<30} {info['type']:<12} {info['id']}")
print("=" * 55)
print("\nCopy the CHAT ID values into:")
print("  • routine.json  →  'telegram_chat_id' field for each teacher")
print("  • .env          →  STUDENT_GROUP_CHAT_ID=<group id>")
print("\nNote: Group chat IDs are negative numbers like -1001234567890")
