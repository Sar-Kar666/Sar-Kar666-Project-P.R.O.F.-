import os
import json
import time
import argparse
import datetime
import urllib.request
import urllib.error
import urllib.parse
import ssl
import base64
import threading
import http.server
import fitz  # PyMuPDF

# Fix for macOS SSL certificate verification error
_SSL_CTX = ssl._create_unverified_context()

from dotenv import load_dotenv
import database as db  # PostgreSQL data layer

# Load environment variables
load_dotenv()

# --- Configuration ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
STUDENT_GROUP_CHAT_ID = os.getenv("STUDENT_GROUP_CHAT_ID")
OLLAMA_TEXT_MODEL = os.getenv("OLLAMA_TEXT_MODEL", "llama3.1")
OLLAMA_VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "llama3.2-vision")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8443"))

TELEGRAM_API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# ── Global coordination state (webhook-based, thread-safe) ──
_pending_replies = []   # list of active teacher coordination items
_teacher_queue = {}     # chat_id -> [remaining class slots]
_state_lock = threading.Lock()

# --- System Prompt ---
SYSTEM_PROMPT = """
You are 'P.R.O.F.' (Programmed Routine for Operational Flow). ONLY classify teacher responses about class schedules.

YOUR ONLY JOB: Read the teacher's latest reply and classify it as CONFIRMED, CANCELLED, RESCHEDULED, or UNCERTAIN about having a class.

CRITICAL RULES:
- IGNORE any document content, PDF text, or file data in the history. Only focus on the LATEST TEACHER REPLY.
- If the teacher says "yes", "sure", "ok", "okay", "yep", "yup", "alright", "absolutely", "definitely", "yes I will", "I'll take it", "confirmed", "I have class" -> CONFIRMED
- If the teacher says "no", "cancel", "not coming", "won't take", "cancle", "cancle it" -> CANCELLED
- If the teacher gives an EXPLICIT NEW TIME (e.g. "tomorrow at 9am", "3 PM", "reschedule to Monday") -> RESCHEDULED
- ONLY return RESCHEDULED when a specific new time or day is mentioned. A plain affirmative like "sure" or "ok" is CONFIRMED, NOT RESCHEDULED.
- ONLY return UNCERTAIN if you genuinely cannot tell from the reply.
- "Yes" alone in response to "Will you take the class?" = CONFIRMED. Do not ask for clarification.

Output ONLY this raw JSON, nothing else:
{ "status": "CONFIRMED" | "CANCELLED" | "RESCHEDULED" | "UNCERTAIN", "announcement": "emoji-rich student announcement here or empty string if UNCERTAIN" }
"""

# --- Conversational AI Prompt ---
CASUAL_SYSTEM_PROMPT = """
You are P.R.O.F. (Programmed Routine for Operational Flow), an AI assistant for a college.
You reply to ANYONE who messages — teachers, students, or anyone else — in a friendly, helpful, and playful way.
You can help with: class schedules, general knowledge, homework questions, and more.

If any user asks you to announce something to the students (e.g., "tell the students to come at 3 PM"), trigger an announcement.

OUTPUT FORMAT MUST BE JSON:
{
  "reply": "Your friendly response to the user",
  "action": "NONE" or "ANNOUNCE_CLASS",
  "action_text": "If action is ANNOUNCE_CLASS, write the exact public announcement here. Otherwise empty string."
}
"""

# ─────────────────────────────────────────────
# TELEGRAM API FUNCTIONS
# ─────────────────────────────────────────────

def _telegram_request(method, params=None):
    """Make a GET request to the Telegram Bot API."""
    url = f"{TELEGRAM_API_BASE}/{method}"
    if params:
        query_string = urllib.parse.urlencode(params)
        url += f"?{query_string}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30, context=_SSL_CTX) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"[Telegram] HTTP {e.code} error on {method}: {body}")
        return None
    except urllib.error.URLError as e:
        # Ignore normal long-polling timeouts or connection resets quietly to prevent log spam
        if "timeout" not in str(e).lower() and "reset" not in str(e).lower():
            print(f"[Telegram] Network error on {method}: {e}")
        return None
    except Exception as e:
        print(f"[Telegram] Unexpected error on {method}: {e}")
        return None


def _telegram_post(method, payload):
    """Make a POST request to the Telegram Bot API."""
    url = f"{TELEGRAM_API_BASE}/{method}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30, context=_SSL_CTX) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"[Telegram] HTTP {e.code} error on {method}: {body}")
        return None
    except urllib.error.URLError as e:
        print(f"[Telegram] Network error on {method}: {e}")
        return None
    except Exception as e:
        print(f"[Telegram] Unexpected error on {method}: {e}")
        return None


def download_telegram_image_b64(file_id):
    """Fetch an image file path from Telegram, download, and return as base64."""
    # Step 1: Get file path from file_id
    file_info = _telegram_request("getFile", {"file_id": file_id})
    if not file_info or not file_info.get("ok"):
        print("[Telegram] Failed to getFile for file_id:", file_id)
        return None
        
    file_path = file_info["result"]["file_path"]
    
    # Step 2: Download the actual file bytes
    download_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
    try:
        with urllib.request.urlopen(download_url, timeout=30, context=_SSL_CTX) as response:
            image_bytes = response.read()
            return base64.b64encode(image_bytes).decode("utf-8")
    except Exception as e:
        print(f"[Telegram] Failed to download image: {e}")
        return None


def download_and_parse_pdf(file_id):
    """Fetch a PDF document from Telegram, download bytes, and extract text using PyMuPDF."""
    file_info = _telegram_request("getFile", {"file_id": file_id})
    if not file_info or not file_info.get("ok"):
        print("[Telegram] Failed to getFile for file_id:", file_id)
        return None
        
    file_path = file_info["result"]["file_path"]
    download_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
    
    try:
        with urllib.request.urlopen(download_url, timeout=30, context=_SSL_CTX) as response:
            pdf_bytes = response.read()
            
            # Load PDF from memory using fitz (PyMuPDF)
            doc = fitz.open("pdf", pdf_bytes)
            extracted_text = ""
            for page in doc:
                extracted_text += page.get_text() + "\n"
            
            return extracted_text.strip()
            
    except Exception as e:
        print(f"[Telegram] Failed to download or parse PDF: {e}")
        return None


def send_telegram_message(chat_id, text):
    """Send a text message to a Telegram chat/group."""
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }
    result = _telegram_post("sendMessage", payload)
    if result and result.get("ok"):
        print(f"[Telegram] ✅ Message sent to chat_id={chat_id}")
        return True
    else:
        print(f"[Telegram] ❌ Failed to send message to chat_id={chat_id}. Response: {result}")
        return False


def send_inline_keyboard(chat_id, text, buttons, parse_mode="Markdown"):
    """
    Send a message with an inline keyboard.
    buttons should be a list of lists of dicts containing 'text' and 'callback_data'.
    """
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "reply_markup": {
            "inline_keyboard": buttons
        }
    }
    result = _telegram_post("sendMessage", payload)
    if result and result.get("ok"):
        print(f"[Telegram] ✅ Inline keyboard sent to chat_id={chat_id}")
        return True
    else:
        print(f"[Telegram] ❌ Failed to send keyboard to chat_id={chat_id}. Response: {result}")
        return False


def answer_callback_query(callback_query_id, text=None):
    """Tell Telegram we handled the button press to stop the loading spinner."""
    payload = {
        "callback_query_id": callback_query_id,
    }
    if text:
        payload["text"] = text
    _telegram_post("answerCallbackQuery", payload)


def edit_message_text(chat_id, message_id, new_text, parse_mode="Markdown", reply_markup={"inline_keyboard": []}):
    """Edit the text (and implicitly remove the keyboard) of a previously sent message."""
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": new_text,
        "parse_mode": parse_mode,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    _telegram_post("editMessageText", payload)


def send_telegram_chat_action(chat_id, action="typing"):
    """
    Send a chat action (typing, upload_photo, etc.) to show activity.
    Valid actions: typing, upload_photo, record_video, upload_video, record_voice, upload_voice, upload_document, choose_sticker, find_location, record_video_note, upload_video_note.
    """
    payload = {
        "chat_id": chat_id,
        "action": action,
    }
    _telegram_post("sendChatAction", payload)


class TelegramStatusManager:
    """Runs a background thread to continuously send chat actions to Telegram while the AI thinks."""
    def __init__(self, chat_id, action="typing"):
        self.chat_id = chat_id
        self.action = action
        self.running = False
        self.thread = None

    def _loop(self):
        while self.running:
            send_telegram_chat_action(self.chat_id, action=self.action)
            # Telegram statuses expire after exactly 5 seconds. Ping every 4s to keep it alive.
            for _ in range(40):  # Wait 4 seconds total, checking running status every 0.1s
                if not self.running:
                    break
                time.sleep(0.1)

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join()


def get_telegram_updates(offset=None):
    """Fetch new updates from Telegram (long poll, 10s timeout)."""
    params = {
        "timeout": 10,
        "allowed_updates": json.dumps(["message", "callback_query"])
    }
    if offset is not None:
        params["offset"] = offset
    result = _telegram_request("getUpdates", params)
    if result and result.get("ok"):
        return result.get("result", [])
    return []


def check_for_reply_telegram(chat_id, update_offset):
    """
    Check if a new message has arrived from a specific chat_id.
    Returns (reply_text, new_offset) or (None, update_offset) if nothing new.
    """
    updates = get_telegram_updates(offset=update_offset)
    new_offset = update_offset

    for update in updates:
        new_offset = max(new_offset, update["update_id"] + 1)
        msg = update.get("message", {})
        if str(msg.get("chat", {}).get("id", "")) == str(chat_id):
            text = msg.get("text", "")
            if text:
                return text, new_offset

    return None, new_offset


def notify_students(announcement):
    """Send the announcement to the Student Group."""
    print(f"[Telegram] Notifying student group (chat_id={STUDENT_GROUP_CHAT_ID})...")
    send_telegram_message(STUDENT_GROUP_CHAT_ID, announcement)


def register_webhook(webhook_base_url):
    """Register the HTTPS webhook URL with Telegram."""
    url = webhook_base_url.rstrip("/") + "/webhook"
    payload = {
        "url": url,
        "allowed_updates": ["message", "callback_query"],
    }
    result = _telegram_post("setWebhook", payload)
    if result and result.get("ok"):
        print(f"[Webhook] ✅ Registered: {url}")
        return True
    print(f"[Webhook] ❌ Failed: {result}")
    return False


def delete_webhook():
    """Remove any registered webhook (reverts to long-polling if needed)."""
    _telegram_post("deleteWebhook", {})


# ─────────────────────────────────────────────
# OLLAMA AI FUNCTIONS  (unchanged)
# ─────────────────────────────────────────────

def ensure_ollama_running():
    """Check if Ollama is running, if not, try to start it."""
    import subprocess

    url = "http://localhost:11434/api/tags"
    try:
        urllib.request.urlopen(url, timeout=1)
        print("Ollama is already running. ✅")
        return True
    except:
        print("Ollama is NOT running. Starting it now... 🦙")
        try:
            subprocess.Popen(
                ["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            print("Waiting for Ollama to start...", end="", flush=True)
            for _ in range(20):
                time.sleep(1)
                try:
                    urllib.request.urlopen(url, timeout=1)
                    print(" Done! ✅")
                    return True
                except:
                    print(".", end="", flush=True)
            print("\nWARNING: Could not start Ollama automatically. Please run 'ollama serve' manually.")
            return False
        except FileNotFoundError:
            print("\nERROR: 'ollama' command not found. Please install Ollama.")
            return False


# ─────────────────────────────────────────────
# GEMINI API  (primary AI engine)
# ─────────────────────────────────────────────

def call_gemini(system_prompt_text, user_prompt_text, image_b64=None, expect_json=True):
    """
    Call the Google Gemini REST API.
    Returns parsed dict/string on success, or None on any error (so callers can fall back to Ollama).
    Supports optional inline image (base64) for multimodal queries.
    Retries up to 3 times with backoff on 429 rate-limit errors.
    """
    if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
        return None  # No key configured — skip silently

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )

    # Build the parts list for the user turn
    user_parts = [{"text": user_prompt_text}]
    if image_b64:
        user_parts.append({
            "inline_data": {"mime_type": "image/jpeg", "data": image_b64}
        })

    body = {
        "system_instruction": {"parts": [{"text": system_prompt_text}]},
        "contents": [{"role": "user", "parts": user_parts}],
    }

    if expect_json:
        body["generationConfig"] = {"responseMimeType": "application/json"}

    MAX_RETRIES = 3
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            json_data = json.dumps(body).encode("utf-8")
            req = urllib.request.Request(
                url, data=json_data, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=30, context=_SSL_CTX) as response:
                raw = json.loads(response.read().decode("utf-8"))

            text = raw["candidates"][0]["content"]["parts"][0]["text"]
            print(f"[AI] Gemini raw response: {text[:200]}")

            if expect_json:
                # Strip markdown fences if model adds them despite responseMimeType
                cleaned = text.strip()
                if cleaned.startswith("```"):
                    cleaned = cleaned.split("```")[1]
                    if cleaned.startswith("json"):
                        cleaned = cleaned[4:]
                    cleaned = cleaned.split("```")[0].strip()
                return json.loads(cleaned)
            else:
                return text.strip()

        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            if e.code == 429 and attempt < MAX_RETRIES:
                # Parse the retryDelay from the error body, default to 20s
                wait = 20
                try:
                    err_json = json.loads(err_body)
                    for detail in err_json.get("error", {}).get("details", []):
                        if detail.get("@type", "").endswith("RetryInfo"):
                            delay_str = detail.get("retryDelay", "20s")
                            wait = int(delay_str.rstrip("s")) + 2  # +2s buffer
                            break
                except Exception:
                    pass
                print(f"[Gemini] Rate-limited (429). Waiting {wait}s before retry {attempt}/{MAX_RETRIES - 1}...")
                time.sleep(wait)
                continue
            print(f"[Gemini] HTTP {e.code} error: {err_body[:300]}")
            return None
        except Exception as e:
            print(f"[Gemini] Error: {e}")
            return None

    print("[Gemini] All retries exhausted.")
    return None


# ─────────────────────────────────────────────
# OPENROUTER API  (fallback AI engine)
# ─────────────────────────────────────────────

def call_openrouter(system_prompt_text, user_prompt_text, image_b64=None, expect_json=True, prior_messages=None):
    """
    Call the OpenRouter API (OpenAI-compatible).
    Returns parsed dict/string on success, or None on error.
    Supports optional inline image (base64) for vision queries.
    prior_messages: list of {"role": "user"|"assistant", "content": "..."} for conversation memory.
    Retries up to 3 times with backoff on 429 rate-limit errors.
    """
    if not OPENROUTER_API_KEY:
        print("[OpenRouter] No API key configured.")
        return None

    url = "https://openrouter.ai/api/v1/chat/completions"

    # Build user content — text only, or text + image for vision
    if image_b64:
        user_content = [
            {"type": "text", "text": user_prompt_text},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}
        ]
    else:
        user_content = user_prompt_text

    # Build message list: system → history → current user message
    messages = [{"role": "system", "content": system_prompt_text}]
    if prior_messages:
        messages.extend(prior_messages)
    messages.append({"role": "user", "content": user_content})

    body = {
        "model": OPENROUTER_MODEL,
        "messages": messages,
    }
    if expect_json and not image_b64:
        body["response_format"] = {"type": "json_object"}

    MAX_RETRIES = 3
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            json_data = json.dumps(body).encode("utf-8")
            req = urllib.request.Request(
                url, data=json_data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                }
            )
            with urllib.request.urlopen(req, timeout=60, context=_SSL_CTX) as response:
                raw = json.loads(response.read().decode("utf-8"))

            text = raw["choices"][0]["message"]["content"]
            print(f"[AI] OpenRouter raw response: {text[:200]}")

            if expect_json:
                cleaned = text.strip()
                if cleaned.startswith("```"):
                    cleaned = cleaned.split("```")[1]
                    if cleaned.startswith("json"):
                        cleaned = cleaned[4:]
                    cleaned = cleaned.split("```")[0].strip()
                return json.loads(cleaned)
            else:
                return text.strip()

        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            if e.code == 429 and attempt < MAX_RETRIES:
                wait = 20
                print(f"[OpenRouter] Rate-limited (429). Waiting {wait}s before retry {attempt}/{MAX_RETRIES - 1}...")
                time.sleep(wait)
                continue
            print(f"[OpenRouter] HTTP {e.code} error: {err_body[:300]}")
            return None
        except json.JSONDecodeError as e:
            print(f"[OpenRouter] JSON parse error: {e}")
            return None
        except Exception as e:
            print(f"[OpenRouter] Error: {e}")
            return None

    print("[OpenRouter] All retries exhausted.")
    return None


def parse_reschedule_time(text: str):
    """
    Use OpenRouter to extract the rescheduled day + time from a teacher's message.
    Returns {"day": "monday", "time": "02:30 PM"} or None if unparseable.
    """
    import datetime as _dt
    today = _dt.date.today()
    tomorrow = today + _dt.timedelta(days=1)

    system = "You are a scheduling parser. Extract day and time from rescheduling messages."
    user = (
        f"Today is {today.strftime('%A, %Y-%m-%d')}.\n"
        f"Extract the rescheduled day and time from this message: \"{text}\"\n\n"
        f"Rules:\n"
        f"- 'tomorrow' means {tomorrow.strftime('%A').lower()}\n"
        f"- If no day is mentioned, assume today ({today.strftime('%A').lower()})\n"
        f"- Always return time in zero-padded 12-hour format: 'HH:MM AM' or 'HH:MM PM'\n"
        f"  Example: 9am → '09:00 AM', 2:30pm → '02:30 PM', 14:00 → '02:00 PM'\n\n"
        f"Return ONLY this JSON:\n"
        f"{{\"day\": \"monday\", \"time\": \"09:00 AM\"}}\n\n"
        f"If you cannot find a clear time, return:\n"
        f"{{\"day\": null, \"time\": null}}"
    )
    result = call_openrouter(system, user, expect_json=True)
    if result and result.get("time") and result.get("day"):
        return result
    return None


# ─────────────────────────────────────────────
# AI ANALYSIS  (Gemini → OpenRouter fallback)
# ─────────────────────────────────────────────

def analyze_reply(reply_text, teacher_name, subject, instructions=None, history=None):
    """
    Classify a teacher's reply as CONFIRMED / CANCELLED / RESCHEDULED / UNCERTAIN.
    Tries Gemini first; falls back to Ollama if Gemini is unavailable.
    """
    if not reply_text:
        return None

    # Clean history: strip document blobs that pollute the context
    POISON_KEYWORDS = ["[ATTACHED DOCUMENT TEXT:]", "[Image Context]", "```", "DOCUMENT CONTENT"]
    if history:
        clean_history = [
            line[:300] for line in history
            if not any(kw in line for kw in POISON_KEYWORDS)
        ]
    else:
        clean_history = []

    history_text = "\n".join(clean_history) if clean_history else "No previous history."

    user_prompt = (
        f"Teacher Name: {teacher_name}\n"
        f"Subject: {subject}\n"
        f"Teacher's Reply Text: \"{reply_text}\"\n"
        f"Teacher's Specific Instructions: \"{instructions if instructions else 'None'}\"\n"
        f"Conversation History (class coordination only):\n{history_text}"
    )

    # --- Try Gemini first (DISABLED per user request) ---
    # print("[AI] Trying Gemini for reply analysis...")
    # result = call_gemini(SYSTEM_PROMPT, user_prompt, expect_json=True)
    # if result:
    #     print(f"[AI] Gemini classified: {result.get('status')}")
    #     return result

    # --- OpenRouter ---
    print("[AI] Using OpenRouter for analysis...")
    result = call_openrouter(SYSTEM_PROMPT, user_prompt, expect_json=True)
    if result:
        print(f"[AI] OpenRouter classified: {result.get('status')}")
        return result
    print("[AI] OpenRouter failed.")
    return {"status": "API_ERROR", "error": "OpenRouter returned no result"}


# Keep the old name as an alias so nothing else in the call-flow breaks
analyze_reply_with_ollama = analyze_reply


# ─────────────────────────────────────────────
# CASUAL CHAT  (Gemini → Ollama fallback)
# ─────────────────────────────────────────────

def chat_with_ai(reply_text, user_name, history=None, image_b64=None, pdf_text=None):
    """
    Handle a casual teacher/student chat message.
    history: list of {"role": "user"|"assistant", "content": "..."} for proper memory.
    Also accepts plain string lists (legacy flat format) — converted automatically.
    """
    if not reply_text and image_b64:
        reply_text = "What is in this image?"

    # Truncate huge PDFs
    if pdf_text:
        MAX_PDF_CHARS = 8000
        if len(pdf_text) > MAX_PDF_CHARS:
            pdf_text = pdf_text[:MAX_PDF_CHARS] + "\n...[Document truncated]..."

    # Separate structured history from injected context strings (e.g. live schedule block)
    structured_history = []
    context_prefix = ""
    if history:
        for item in history:
            if isinstance(item, dict) and "role" in item:
                structured_history.append(item)
            else:
                # Plain string — treat as system context, not a turn
                context_prefix += str(item) + "\n"

    # Choose system prompt
    if pdf_text:
        system_prompt = (
            "You are P.R.O.F., a helpful AI assistant for college. "
            "The user has attached a document. Read the document content provided below, "
            "then answer the user's request about it directly. Be thorough but clear. "
            "DO NOT output JSON. Just respond naturally."
        )
    elif image_b64:
        system_prompt = (
            "You are P.R.O.F., a helpful AI assistant for college. "
            "Please look at the attached image carefully and answer the user's question about it directly. "
            "DO NOT use JSON formatting or output action items. Just talk naturally."
        )
    else:
        system_prompt = CASUAL_SYSTEM_PROMPT

    # Prepend any context (e.g. live schedule) to the system prompt
    if context_prefix:
        system_prompt = system_prompt + "\n\n" + context_prefix.strip()

    doc_section = f"\n\n[DOCUMENT CONTENT]:\n{pdf_text}" if pdf_text else ""
    user_prompt = f"User Name: {user_name}\nUser's Message: \"{reply_text}\"{doc_section}"

    has_attachment = bool(image_b64 or pdf_text)

    # --- Try Gemini first (DISABLED per user request) ---
    # print("[AI] Trying Gemini for casual chat...")
    # gemini_result = call_gemini(
    #     system_prompt,
    #     user_prompt,
    #     image_b64=image_b64 if not pdf_text else None,
    #     expect_json=(not has_attachment),
    # )
    #
    # if gemini_result is not None:
    #     print("[AI] Gemini responded successfully.")
    #     if isinstance(gemini_result, str):
    #         return {"reply": gemini_result, "action": "NONE"}
    #     if isinstance(gemini_result, dict):
    #         return gemini_result
    #     return {"reply": str(gemini_result), "action": "NONE"}

    # --- OpenRouter ---
    print("[AI] Using OpenRouter for casual chat...")
    or_result = call_openrouter(
        system_prompt,
        user_prompt,
        image_b64=image_b64 if not pdf_text else None,
        expect_json=(not has_attachment),
        prior_messages=structured_history if structured_history else None,
    )
    if or_result is not None:
        if isinstance(or_result, str):
            return {"reply": or_result, "action": "NONE"}
        if isinstance(or_result, dict):
            return or_result
        return {"reply": str(or_result), "action": "NONE"}

    print("[AI] OpenRouter chat failed.")
    return {"reply": "I'm having trouble thinking right now. 💤", "action": "NONE"}


# Alias for backward compatibility
chat_with_ollama = chat_with_ai


def handle_casual_chat(chat_id, user_name, text, image_b64=None, pdf_text=None):
    """Process a casual message from any user, get AI response, reply, and log reply."""
    # Never reply to messages from the student group (bot posts there, never reads)
    if str(chat_id) == str(STUDENT_GROUP_CHAT_ID):
        return

    # Handle PDF attachment
    if pdf_text:
        doc_context = f"\n\n[ATTACHED DOCUMENT TEXT:]\n{pdf_text}\n"
        if text:
            # User sent a caption with the PDF — answer their specific question
            text = text + doc_context
        else:
            # No caption — save full PDF to history for follow-up context, then ask what they want
            db.save_message(chat_id, user_name, "user", f"[Sent a PDF document]{doc_context[:10000]}")
            ack = (
                "📄 Got your document! What would you like me to do with it?\n\n"
                "You can ask me to:\n"
                "• Summarize it\n"
                "• Answer specific questions\n"
                "• Extract key points\n"
                "• Anything else!"
            )
            send_telegram_message(chat_id, ack)
            db.save_message(chat_id, "PROF", "bot", ack)
            return  # Wait for the user's actual instruction

    msg_log = text if text else "[Image Context]"
    print(f"Casual message from {user_name} ({chat_id}): {msg_log[:100]}...")
    db.save_message(chat_id, user_name, "user", msg_log)

    # Build a live schedule context block so the AI knows today's real status
    todays_classes = db.get_todays_status_for_teacher(str(chat_id))
    if todays_classes:
        status_emoji = {"CONFIRMED": "✅", "CANCELLED": "❌", "RESCHEDULED": "🕒", "PENDING": "⏳", "NOT ASKED YET": "📋"}
        schedule_lines = []
        for c in todays_classes:
            emoji = status_emoji.get(c["status"], "📋")
            line = f"  {emoji} {c['subject']} at {c['time']} — {c['status']}"
            if c["rescheduled_to"]:
                line += f" (moved to {c['rescheduled_to']})"
            if c["instructions"]:
                line += f" | Note: {c['instructions']}"
            schedule_lines.append(line)
        today_context = "\n[TODAY'S LIVE CLASS STATUS FOR THIS TEACHER]\n" + "\n".join(schedule_lines) + "\n"
    else:
        today_context = ""

    if pdf_text:
        action_type = "upload_document"
    elif image_b64:
        action_type = "upload_photo"
    else:
        action_type = "typing"

    status_manager = TelegramStatusManager(chat_id, action=action_type)
    status_manager.start()

    # Structured conversation history for proper multi-turn memory
    history = db.get_history_structured(chat_id, limit=30)
    if today_context:
        # Inject live schedule as a system-level string (handled in chat_with_ai)
        history = [today_context] + history

    # Run the heavy AI processing
    ai_response_obj = chat_with_ollama(text, user_name, history, image_b64=image_b64, pdf_text=pdf_text if not image_b64 else None)
    
    # Stop the "Processing" action when AI finishes
    status_manager.stop()
    
    # Simulate a brief "typing delay" right before sending actual text, for a more natural feel
    send_telegram_chat_action(chat_id, action="typing")
    time.sleep(1.5)
    
    ai_reply = ai_response_obj.get("reply", "Something went wrong! 😵‍💫")
    ai_action = ai_response_obj.get("action", "NONE")
    ai_action_text = ai_response_obj.get("action_text", "")
    
    print(f"AI Response to {user_name}: {ai_reply} | Action: {ai_action}")
    send_telegram_message(chat_id, ai_reply)
    db.save_message(chat_id, user_name, "bot", ai_reply)

    if ai_action == "ANNOUNCE_CLASS" and ai_action_text:
        print(f"AI triggered announcement: {ai_action_text}")
        notify_students(f"📢 *Announcement from {user_name}*\n\n{ai_action_text}")


# ─────────────────────────────────────────────
# WEBHOOK — INCOMING UPDATE HANDLER
# ─────────────────────────────────────────────

def _handle_schedule_message(chat_id, reply_text, user_name, is_callback=False, msg_id=None):
    """Process a teacher reply during an active coordination cycle."""
    import re

    with _state_lock:
        item = next((x for x in _pending_replies if str(x["chat_id"]) == str(chat_id)), None)
    if not item:
        return

    teacher = item["teacher"]
    subject = item["subject"]
    state = item.get("state", "WAITING_FOR_CONFIRMATION")

    print(f"New reply from {teacher}: {reply_text}")

    if is_callback and msg_id:
        edit_message_text(chat_id, msg_id, item["last_msg"] + f"\n\n👉 *You selected: {reply_text}*")

    item["history"].append(f"Teacher: {reply_text}")
    db.save_message(chat_id, teacher, "teacher", reply_text)

    if state == "WAITING_FOR_CONFIRMATION":
        if is_callback:
            status = reply_text
            pre_analysis = None
        else:
            pre_analysis = analyze_reply(reply_text, teacher, subject, history=item["history"])
            status = pre_analysis.get("status", "UNCERTAIN") if pre_analysis else "UNCERTAIN"

        if status == "API_ERROR":
            print(f"CRITICAL: API Error for {teacher}.")
            with _state_lock:
                if item in _pending_replies:
                    _pending_replies.remove(item)
            return

        if status == "CANCELLED":
            db.update_class_session(item["session_id"], "CANCELLED")
            if is_callback:
                notify_students(f"❌ *Class Cancelled!*\n\n{teacher} has cancelled the {subject} class.")
            elif pre_analysis and pre_analysis.get("announcement"):
                notify_students(pre_analysis["announcement"])
            with _state_lock:
                if item in _pending_replies:
                    _pending_replies.remove(item)
            _trigger_next_class_in_queue(str(chat_id))

        elif status == "RESCHEDULED":
            if is_callback:
                follow_up = "Please type the new time and any instructions for the class:"
                if send_telegram_message(chat_id, follow_up):
                    item.update({"state": "WAITING_FOR_INSTRUCTIONS", "first_reply": "RESCHEDULED", "status": "RESCHEDULED"})
                    item["history"].append(f"Bot: {follow_up}")
                    db.save_message(chat_id, teacher, "bot", follow_up)
            else:
                has_time_info = bool(re.search(
                    r'\d|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|am|pm|morning|afternoon|evening|next|week',
                    reply_text, re.IGNORECASE
                ))
                if not has_time_info:
                    follow_up = "Do you want any specific instruction for the class?"
                    if send_telegram_message(chat_id, follow_up):
                        item.update({"state": "WAITING_FOR_INSTRUCTIONS", "first_reply": reply_text, "status": "CONFIRMED"})
                        item["history"].append(f"Bot: {follow_up}")
                        db.save_message(chat_id, teacher, "bot", follow_up)
                else:
                    # Check for conflicts before accepting the reschedule
                    parsed = parse_reschedule_time(reply_text)
                    if parsed and parsed.get("time") and parsed.get("day"):
                        conflicts = db.get_conflicts(
                            parsed["day"], parsed["time"],
                            exclude_class_id=item["class_id"],
                        )
                        if conflicts:
                            conflict_list = "\n".join(
                                f"📚 *{c['subject']}* ({c['teacher']}) at *{c['time']}*"
                                for c in conflicts
                            )
                            conflict_msg = (
                                f"⚠️ *Time Conflict Detected!*\n\n"
                                f"The following class is already scheduled near "
                                f"*{parsed['time']}* on *{parsed['day'].capitalize()}*:\n\n"
                                f"{conflict_list}\n\n"
                                f"Please choose a different time:"
                            )
                            send_telegram_message(chat_id, conflict_msg)
                            item["history"].append(f"Bot: {conflict_msg}")
                            db.save_message(chat_id, teacher, "bot", conflict_msg)
                            item.update({"state": "WAITING_FOR_INSTRUCTIONS", "first_reply": "RESCHEDULED", "status": "RESCHEDULED"})
                            print(f"[Conflict] {teacher} chose {parsed['time']} on {parsed['day']} — blocked.")
                            return
                    db.update_class_session(item["session_id"], "RESCHEDULED", rescheduled_to=reply_text)
                    announcement = pre_analysis.get("announcement") if pre_analysis else None
                    notify_students(announcement or f"🗓️ *Class Rescheduled!*\n\n{teacher} rescheduled {subject}.\nMessage: {reply_text}")
                    with _state_lock:
                        if item in _pending_replies:
                            _pending_replies.remove(item)
                    _trigger_next_class_in_queue(str(chat_id))

        elif status == "UNCERTAIN":
            clarification = "Could you please clarify if the class is confirmed?"
            send_telegram_message(chat_id, clarification)
            item["last_msg"] = clarification
            item["history"].append(f"Bot: {clarification}")
            db.save_message(chat_id, teacher, "bot", clarification)

        elif status == "CONFIRMED":
            follow_up = "Do you want any specific instruction for the class?"
            if send_telegram_message(chat_id, follow_up):
                item.update({"state": "WAITING_FOR_INSTRUCTIONS", "first_reply": reply_text, "status": "CONFIRMED"})
                item["history"].append(f"Bot: {follow_up}")
                db.save_message(chat_id, teacher, "bot", follow_up)

    elif state == "WAITING_FOR_INSTRUCTIONS":
        print(f"Instructions from {teacher}: {reply_text}")

        # ── Conflict check for RESCHEDULED classes ──────────────────────────
        if item.get("status") == "RESCHEDULED":
            parsed = parse_reschedule_time(reply_text)
            if parsed and parsed.get("time") and parsed.get("day"):
                conflicts = db.get_conflicts(
                    parsed["day"], parsed["time"],
                    exclude_class_id=item["class_id"],
                )
                if conflicts:
                    conflict_list = "\n".join(
                        f"📚 *{c['subject']}* ({c['teacher']}) at *{c['time']}*"
                        for c in conflicts
                    )
                    conflict_msg = (
                        f"⚠️ *Time Conflict Detected!*\n\n"
                        f"The following class is already scheduled near "
                        f"*{parsed['time']}* on *{parsed['day'].capitalize()}*:\n\n"
                        f"{conflict_list}\n\n"
                        f"Please choose a different time:"
                    )
                    send_telegram_message(chat_id, conflict_msg)
                    item["history"].append(f"Bot: {conflict_msg}")
                    db.save_message(chat_id, teacher, "bot", conflict_msg)
                    print(f"[Conflict] {teacher} chose {parsed['time']} on {parsed['day']} — blocked.")
                    return  # Stay in WAITING_FOR_INSTRUCTIONS, wait for a new time
            elif not parsed:
                # Couldn't parse a time — ask again
                unclear_msg = "Sorry, I couldn't understand the time. Please send it clearly (e.g., '03:00 PM' or '2:30pm'):"
                send_telegram_message(chat_id, unclear_msg)
                item["history"].append(f"Bot: {unclear_msg}")
                db.save_message(chat_id, teacher, "bot", unclear_msg)
                return
        # ────────────────────────────────────────────────────────────────────

        with _state_lock:
            has_more = str(chat_id) in _teacher_queue and len(_teacher_queue[str(chat_id)]) > 0

        if not has_more:
            exit_msg = "Okay, noting that down. Have a great day!"
            send_telegram_message(chat_id, exit_msg)
            db.save_message(chat_id, teacher, "bot", exit_msg)
        else:
            interim_msg = "Okay, noted! Give me just a second..."
            send_telegram_message(chat_id, interim_msg)
            db.save_message(chat_id, teacher, "bot", interim_msg)

        final_analysis = analyze_reply(item.get("first_reply", ""), teacher, subject, instructions=reply_text, history=item["history"])
        announcement = final_analysis.get("announcement") if final_analysis else None

        if not announcement and item.get("status") == "CONFIRMED":
            instr_text = f"\n📝 Note: {reply_text}" if len(reply_text) > 3 and "no" not in reply_text.lower() else ""
            announcement = (
                f"🎉 *Class Confirmed!* 🎉\n\n"
                f"*{subject}* with *{teacher}* is happening! ✅\n\n"
                f"⏰ Time: {item.get('time', 'Scheduled Time')}{instr_text}\n\n"
                f"See you in class! 🏃‍♂️💨"
            )

        if announcement:
            notify_students(announcement)

        db.update_class_session(
            item["session_id"],
            item.get("status", "CONFIRMED"),
            rescheduled_to=item.get("first_reply") if item.get("status") == "RESCHEDULED" else None,
            instructions=reply_text if len(reply_text) > 3 and "no" not in reply_text.lower() else None,
        )

        with _state_lock:
            if item in _pending_replies:
                _pending_replies.remove(item)
        _trigger_next_class_in_queue(str(chat_id))


def _process_update(update):
    """Route a single Telegram update — called in a background thread per request."""
    with _state_lock:
        active_ids = {str(x["chat_id"]) for x in _pending_replies}

    if "callback_query" in update:
        cq = update["callback_query"]
        cid = str(cq["message"]["chat"]["id"])
        data = cq["data"]
        user_name = cq["from"].get("first_name", "User")
        msg_id = cq["message"]["message_id"]
        original_text = cq["message"].get("text", "")

        _BUTTON_UI = {
            "CONFIRMED":   ("✅ Got it!",  "⏳ _Confirming your class..._"),
            "CANCELLED":   ("❌ Got it!",  "⏳ _Cancelling your class..._"),
            "RESCHEDULED": ("🕒 Got it!",  "⏳ _Processing reschedule..._"),
        }
        toast, inline = _BUTTON_UI.get(data, ("✅ Got it!", "⏳ _Processing..._"))

        if cid in active_ids:
            # 1. Show popup toast so the button feels instant
            answer_callback_query(cq["id"], text=toast)
            # 2. Remove the buttons and show a "processing" line immediately
            edit_message_text(cid, msg_id, original_text + f"\n\n{inline}")
            # 3. Run the actual logic (will do a final edit + send follow-up)
            _handle_schedule_message(cid, data, user_name, is_callback=True, msg_id=msg_id)
        else:
            answer_callback_query(cq["id"], text="⏰ This coordination session has already ended.")
        return

    msg = update.get("message", {})
    if not msg:
        return

    cid = str(msg.get("chat", {}).get("id", ""))
    text = msg.get("text", "") or msg.get("caption", "")
    user_name = msg.get("from", {}).get("first_name", "User")

    image_b64 = None
    if "photo" in msg and msg["photo"]:
        image_b64 = download_telegram_image_b64(msg["photo"][-1]["file_id"])

    pdf_text = None
    if "document" in msg and msg["document"].get("mime_type") == "application/pdf":
        pdf_text = download_and_parse_pdf(msg["document"]["file_id"])

    if not cid or str(cid) == str(STUDENT_GROUP_CHAT_ID):
        return
    if not text and not image_b64 and not pdf_text:
        return

    if cid in active_ids:
        _handle_schedule_message(cid, text, user_name, is_callback=False)
    else:
        handle_casual_chat(cid, user_name, text, image_b64=image_b64, pdf_text=pdf_text)


class _WebhookHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/webhook":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
        try:
            update = json.loads(body.decode("utf-8"))
            threading.Thread(target=_process_update, args=(update,), daemon=True).start()
        except Exception as e:
            print(f"[Webhook] Parse error: {e}")

    def log_message(self, format, *args):
        pass  # Suppress HTTP access log spam


# ─────────────────────────────────────────────
# DAILY CYCLE  (Phase 1 — sends messages; replies arrive via webhook)
# ─────────────────────────────────────────────

def _start_daily_cycle():
    """Query today's classes from DB, send confirmation messages, populate global state."""
    print(f"\n--- Starting Daily Cycle at {datetime.datetime.now()} ---")

    if not TELEGRAM_BOT_TOKEN or not STUDENT_GROUP_CHAT_ID:
        print("ERROR: Missing TELEGRAM_BOT_TOKEN or STUDENT_GROUP_CHAT_ID in .env")
        return

    classes = db.get_todays_classes()
    if not classes:
        print("[Daily Cycle] No classes scheduled for today.")
        return

    teacher_queue = {}
    for cls in classes:
        cid = str(cls["telegram_chat_id"])
        teacher_queue.setdefault(cid, []).append(cls)

    with _state_lock:
        _pending_replies.clear()
        _teacher_queue.clear()
        _teacher_queue.update(teacher_queue)

    print("\n--- Phase 1: Sending Messages ---")
    for chat_id, queue in list(_teacher_queue.items()):
        if not queue:
            continue
        slot = queue.pop(0)
        teacher  = slot["teacher_name"]
        subject  = slot["subject"]
        time_slot = slot["time"]
        session_id = db.create_class_session(slot["class_id"])

        initial_msg = (
            f"Hello {teacher}, this is the automated class coordinator. "
            f"Do you have the {subject} class at {time_slot} today?"
        )
        buttons = [
            [{"text": "✅ Confirm",    "callback_data": "CONFIRMED"}],
            [{"text": "❌ Cancel",     "callback_data": "CANCELLED"}],
            [{"text": "🕒 Reschedule","callback_data": "RESCHEDULED"}],
        ]
        if send_inline_keyboard(chat_id, initial_msg, buttons):
            history = db.get_history(chat_id)
            history.append(f"Bot: {initial_msg}")
            db.save_message(chat_id, teacher, "bot", initial_msg)
            with _state_lock:
                _pending_replies.append({
                    "teacher": teacher, "subject": subject, "time": time_slot,
                    "chat_id": chat_id, "last_msg": initial_msg,
                    "history": history, "state": "WAITING_FOR_CONFIRMATION",
                    "session_id": session_id, "class_id": slot["class_id"],
                    "sent_at": time.time(), "reminders_sent": 0,
                })
        time.sleep(1)

    print("[Daily Cycle] Messages sent. Replies will arrive via webhook.")


def _trigger_next_class_in_queue(chat_id):
    """Ask the teacher about their next queued class (creates a DB session for it)."""
    with _state_lock:
        queue = _teacher_queue.get(chat_id, [])
        if not queue:
            return
        next_slot = queue.pop(0)

    teacher   = next_slot["teacher_name"]
    subject   = next_slot["subject"]
    time_slot = next_slot["time"]
    session_id = db.create_class_session(next_slot["class_id"])

    next_msg = (
        f"Thanks! One more thing, {teacher} — "
        f"Do you also have the {subject} class at {time_slot} today?"
    )
    buttons = [
        [{"text": "✅ Confirm",    "callback_data": "CONFIRMED"}],
        [{"text": "❌ Cancel",     "callback_data": "CANCELLED"}],
        [{"text": "🕒 Reschedule","callback_data": "RESCHEDULED"}],
    ]
    if send_inline_keyboard(chat_id, next_msg, buttons):
        history = db.get_history(chat_id)
        history.append(f"Bot: {next_msg}")
        db.save_message(chat_id, teacher, "bot", next_msg)
        with _state_lock:
            _pending_replies.append({
                "teacher": teacher, "subject": subject, "time": time_slot,
                "chat_id": chat_id, "last_msg": next_msg,
                "history": history, "state": "WAITING_FOR_CONFIRMATION",
                "session_id": session_id, "class_id": next_slot["class_id"],
                "sent_at": time.time(), "reminders_sent": 0,
            })
        print(f"[Queue] Asking {teacher} about next class: {subject} at {time_slot}.")


# ─────────────────────────────────────────────
# TEACHER REMINDER LOOP
# ─────────────────────────────────────────────

def _reminder_loop():
    """Background thread: nudge teachers who haven't replied in 30 minutes (max 2 nudges)."""
    REMINDER_INTERVAL = 30 * 60   # seconds before first/subsequent nudge
    MAX_REMINDERS = 2
    CHECK_EVERY = 5 * 60          # poll interval

    while True:
        time.sleep(CHECK_EVERY)
        now = time.time()
        with _state_lock:
            items_to_nudge = [
                item for item in _pending_replies
                if item.get("state") == "WAITING_FOR_CONFIRMATION"
                and now - item.get("sent_at", now) >= REMINDER_INTERVAL
                and item.get("reminders_sent", 0) < MAX_REMINDERS
            ]

        for item in items_to_nudge:
            chat_id  = item["chat_id"]
            teacher  = item["teacher"]
            subject  = item["subject"]
            time_slot = item["time"]
            count = item.get("reminders_sent", 0) + 1

            nudge = (
                f"👋 Hey {teacher}, just a gentle reminder! "
                f"I'm still waiting for your reply about the *{subject}* class at *{time_slot}*. "
                f"Are you confirming, cancelling, or rescheduling?"
            )
            buttons = [
                [{"text": "✅ Confirm",    "callback_data": "CONFIRMED"}],
                [{"text": "❌ Cancel",     "callback_data": "CANCELLED"}],
                [{"text": "🕒 Reschedule","callback_data": "RESCHEDULED"}],
            ]
            if send_inline_keyboard(chat_id, nudge, buttons):
                with _state_lock:
                    item["reminders_sent"] = count
                    item["sent_at"] = now
                    item["last_msg"] = nudge
                db.save_message(chat_id, teacher, "bot", nudge)
                print(f"[Reminder #{count}] Sent to {teacher} for {subject} at {time_slot}.")


# ─────────────────────────────────────────────
# STUDENT SCHEDULE COMMAND
# ─────────────────────────────────────────────

def handle_schedule_command(chat_id):
    """Reply with today's public class schedule (non-cancelled classes)."""
    classes = db.get_todays_public_schedule()
    today_name = datetime.date.today().strftime("%A")

    if not classes:
        msg = (
            f"📅 *Today's Schedule ({today_name})*\n\n"
            f"No classes are scheduled today, or all classes have been cancelled."
        )
    else:
        status_emoji = {"CONFIRMED": "✅", "RESCHEDULED": "🕒", "PENDING": "⏳", "NOT ASKED YET": "📋"}
        lines = [f"📅 *Today's Schedule ({today_name})*\n"]
        for c in classes:
            emoji = status_emoji.get(c["status"], "📋")
            line = f"{emoji} *{c['subject']}* — {c['time']} _(with {c['teacher_name']})_"
            if c["rescheduled_to"]:
                line += f"\n   ↪️ Rescheduled to: {c['rescheduled_to']}"
            lines.append(line)
        msg = "\n".join(lines)

    send_telegram_message(chat_id, msg)


# ─────────────────────────────────────────────
# SCHEDULER
# ─────────────────────────────────────────────

def send_startup_reminder():
    """Send each teacher a grouped reminder of their classes today (from DB)."""
    import datetime as _dt
    try:
        classes = db.get_todays_classes()
        if not classes:
            print("[Startup] No classes scheduled today — no reminders sent.")
            return

        today_name = _dt.date.today().strftime("%A")
        teacher_schedules = {}
        for cls in classes:
            cid = str(cls["telegram_chat_id"])
            teacher_schedules.setdefault(cid, {"name": cls["teacher_name"], "classes": []})
            teacher_schedules[cid]["classes"].append(
                f"🕐 *{cls['time']}* — {cls['subject']}"
            )

        for chat_id, data in teacher_schedules.items():
            name = data["name"]
            classes_str = "\n".join(data["classes"])
            msg = (
                f"📅 *Good day, {name}!*\n\n"
                f"P.R.O.F. is online for today ({today_name}).\n\n"
                f"{classes_str}\n\n"
                f"✅ I'll be in touch to confirm your classes shortly!"
            )
            send_telegram_message(chat_id, msg)
            print(f"[Startup] Reminder sent to {name} (chat_id={chat_id}).")
    except Exception as e:
        print(f"[Startup] Failed to send reminders: {e}")


def run_scheduler(start_time_str="08:00", webhook_base_url=""):
    """Register webhook, run daily cycle, and serve forever."""
    db.init_db()

    url = webhook_base_url or WEBHOOK_URL
    if not url:
        print("ERROR: No webhook URL provided. Use --webhook-url or set WEBHOOK_URL in .env")
        return

    register_webhook(url)
    send_startup_reminder()

    print(f"\nP.R.O.F. Started (webhook mode). Daily cycle at {start_time_str}.")
    print(f"Webhook listening on port {WEBHOOK_PORT}. Press Ctrl+C to stop.\n")

    _start_daily_cycle()

    def _scheduler_thread():
        while True:
            if datetime.datetime.now().strftime("%H:%M") == start_time_str:
                _start_daily_cycle()
                time.sleep(61)
            time.sleep(30)

    threading.Thread(target=_scheduler_thread, daemon=True).start()

    http.server.HTTPServer.allow_reuse_address = True
    server = http.server.HTTPServer(("0.0.0.0", WEBHOOK_PORT), _WebhookHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Webhook] Shutting down...")
        delete_webhook()
        server.server_close()


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="P.R.O.F.: Autonomous Class Coordinator (Telegram Edition)")
    parser.add_argument("--time", default="08:00", help="Time to run daily cycle (HH:MM, 24hr)")
    parser.add_argument("--webhook-url", default="", help="Public HTTPS base URL for webhook (e.g. ngrok URL)")
    args = parser.parse_args()

    run_scheduler(start_time_str=args.time, webhook_base_url=args.webhook_url)


if __name__ == "__main__":
    main()
