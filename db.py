"""
db.py  ─  P.R.O.F. Persistent Memory
─────────────────────────────────────
Manages the SQLite database that stores all bot ↔ teacher conversations.
No external dependencies — uses Python's built-in sqlite3.
"""

import sqlite3
import datetime
import os

# Database lives next to prof.py
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prof_memory.db")


def init_db():
    """Create the database and messages table if they don't exist."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id     TEXT    NOT NULL,
                teacher     TEXT    NOT NULL,
                role        TEXT    NOT NULL,
                text        TEXT    NOT NULL,
                timestamp   TEXT    NOT NULL
            )
        """)
        conn.commit()
    print(f"[DB] Memory database ready: {DB_PATH}")


def save_message(chat_id, teacher_name, role, text):
    """
    Save a single message to the database.

    Args:
        chat_id     : Telegram chat ID (stored as text)
        teacher_name: Human-readable teacher name
        role        : 'bot' or 'teacher'
        text        : The message content
    """
    timestamp = datetime.datetime.now().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO messages (chat_id, teacher, role, text, timestamp) VALUES (?, ?, ?, ?, ?)",
            (str(chat_id), teacher_name, role, text, timestamp)
        )
        conn.commit()


def get_history(chat_id, limit=40):
    """
    Retrieve the last `limit` messages for a teacher as a list of strings.
    Format matches what Ollama expects: ["Bot: ...", "Teacher: ...", ...]

    Args:
        chat_id : Telegram chat ID
        limit   : Max number of messages to return (most recent)

    Returns:
        List of formatted message strings, oldest first.
    """
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT role, text, timestamp FROM messages
            WHERE chat_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (str(chat_id), limit)
        ).fetchall()

    # Reverse so oldest is first (chronological order for context)
    rows = list(reversed(rows))

    formatted = []
    for role, text, timestamp in rows:
        date_str = timestamp[:10]  # just the date part: YYYY-MM-DD
        prefix = "Bot" if role == "bot" else "Teacher"
        formatted.append(f"[{date_str}] {prefix}: {text}")

    return formatted


def get_history_summary(chat_id):
    """Return a quick summary string of how many messages are stored for a teacher."""
    with sqlite3.connect(DB_PATH) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE chat_id = ?",
            (str(chat_id),)
        ).fetchone()[0]
    return count
