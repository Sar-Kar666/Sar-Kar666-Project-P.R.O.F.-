# P.R.O.F.
**(Programmed Routine for Operational Flow)**

An AI-powered Telegram bot that autonomously coordinates class schedules between teachers and students. It contacts teachers daily, confirms/cancels/reschedules classes, detects time conflicts, and broadcasts announcements to the student group.

---

## Features
- Sends daily confirmation requests to teachers via Telegram (inline buttons)
- AI classifies replies as CONFIRMED / CANCELLED / RESCHEDULED / UNCERTAIN (OpenRouter)
- Detects scheduling conflicts before accepting a reschedule
- Broadcasts class announcements to the student group
- Casual AI chat for teachers and students 24/7
- Schedule stored in PostgreSQL (Neon) — no config files needed
- Webhook-based (instant delivery, no polling)

---

## Setup

### 1. Clone and create virtual environment
```bash
cd "project P.R.O.F/Sar-Kar666-Project-P.R.O.F.-"
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

### 2. Configure `.env`
```env
TELEGRAM_BOT_TOKEN=your_token
STUDENT_GROUP_CHAT_ID=your_group_id
ADMIN_CHAT_ID=your_chat_id
GEMINI_API_KEY=your_gemini_key
GEMINI_MODEL=gemini-2.0-flash
OPENROUTER_API_KEY=your_openrouter_key
OPENROUTER_MODEL=openai/gpt-4o-mini
DATABASE_URL=postgresql://...your_neon_url...?sslmode=require
WEBHOOK_URL=https://your-ngrok-url.ngrok-free.app
WEBHOOK_PORT=8443
```

### 3. Seed the database (run once)
```bash
venv/bin/python3 seed.py
```
Add teachers and classes by editing the `TEACHERS` and `CLASSES` lists in `seed.py`, then re-run.

### 4. Start ngrok
```bash
ngrok http 8443
```
Copy the `https://....ngrok-free.app` URL into `WEBHOOK_URL` in `.env`.

### 5. Run the bot
```bash
venv/bin/python3 prof.py
```

If your ngrok URL changed:
```bash
venv/bin/python3 prof.py --webhook-url https://your-new-url.ngrok-free.app
```

---

## CLI Options
| Flag | Default | Description |
|------|---------|-------------|
| `--time HH:MM` | `08:00` | Time to run the daily cycle (24hr) |
| `--webhook-url URL` | from `.env` | Override the webhook base URL |

---

## Database Schema
| Table | Purpose |
|-------|---------|
| `teachers` | Teacher name + Telegram chat ID |
| `classes` | Recurring weekly schedule (day, time, subject) |
| `class_sessions` | Per-day outcomes (CONFIRMED / CANCELLED / RESCHEDULED) |
| `conversation_memory` | All bot ↔ teacher/student messages |

---

## Tech Stack
- Python 3.14
- Telegram Bot API (webhook mode)
- OpenRouter API (`openai/gpt-4o-mini`)
- Google Gemini 2.0 Flash (optional primary)
- PostgreSQL via Neon + SQLAlchemy ORM
- PyMuPDF (PDF parsing)
