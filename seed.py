"""
seed.py — Populate the PostgreSQL database with teacher + class data.
Run once:  venv/bin/python3 seed.py
Safe to re-run — uses upsert so nothing is duplicated.
"""

import database as db

TEACHERS = [
    {"name": "Diptanu", "telegram_chat_id": "7542430041"},
    {"name": "Annie",   "telegram_chat_id": "1111912063"},
]

CLASSES = [
    # ── Diptanu (AI / ML focus) ─────────────────────────────────────────
    # Monday
    {"teacher_chat_id": "7542430041", "subject": "Artificial Intelligence", "day": "monday",    "time": "09:00 AM"},
    {"teacher_chat_id": "7542430041", "subject": "Machine Learning",        "day": "monday",    "time": "01:00 PM"},
    {"teacher_chat_id": "7542430041", "subject": "Deep Learning",           "day": "monday",    "time": "03:00 PM"},
    # Tuesday
    {"teacher_chat_id": "7542430041", "subject": "Neural Networks",         "day": "tuesday",   "time": "10:00 AM"},
    {"teacher_chat_id": "7542430041", "subject": "Computer Vision",         "day": "tuesday",   "time": "02:00 PM"},
    # Wednesday
    {"teacher_chat_id": "7542430041", "subject": "Natural Language Processing", "day": "wednesday", "time": "09:00 AM"},
    {"teacher_chat_id": "7542430041", "subject": "Reinforcement Learning",  "day": "wednesday", "time": "03:00 PM"},
    # Thursday
    {"teacher_chat_id": "7542430041", "subject": "Data Mining",             "day": "thursday",  "time": "11:00 AM"},
    {"teacher_chat_id": "7542430041", "subject": "Big Data Analytics",      "day": "thursday",  "time": "02:00 PM"},
    # Friday
    {"teacher_chat_id": "7542430041", "subject": "Research Methodology",    "day": "friday",    "time": "10:00 AM"},
    {"teacher_chat_id": "7542430041", "subject": "AI Project Guidance",     "day": "friday",    "time": "03:00 PM"},
    # Saturday
    {"teacher_chat_id": "7542430041", "subject": "AI Tools Workshop",       "day": "saturday",  "time": "10:00 AM"},

    # ── Annie (CS fundamentals) ──────────────────────────────────────────
    # Monday
    {"teacher_chat_id": "1111912063", "subject": "Data Structures",         "day": "monday",    "time": "11:00 AM"},
    {"teacher_chat_id": "1111912063", "subject": "Algorithms",              "day": "monday",    "time": "02:00 PM"},
    {"teacher_chat_id": "1111912063", "subject": "Database Management",     "day": "monday",    "time": "04:00 PM"},
    # Tuesday
    {"teacher_chat_id": "1111912063", "subject": "Operating Systems",       "day": "tuesday",   "time": "09:00 AM"},
    {"teacher_chat_id": "1111912063", "subject": "Computer Networks",       "day": "tuesday",   "time": "01:00 PM"},
    # Wednesday
    {"teacher_chat_id": "1111912063", "subject": "Software Engineering",    "day": "wednesday", "time": "10:00 AM"},
    {"teacher_chat_id": "1111912063", "subject": "Web Development",         "day": "wednesday", "time": "02:00 PM"},
    # Thursday
    {"teacher_chat_id": "1111912063", "subject": "Discrete Mathematics",    "day": "thursday",  "time": "09:00 AM"},
    {"teacher_chat_id": "1111912063", "subject": "Theory of Computation",   "day": "thursday",  "time": "03:00 PM"},
    # Friday
    {"teacher_chat_id": "1111912063", "subject": "Computer Architecture",   "day": "friday",    "time": "11:00 AM"},
    {"teacher_chat_id": "1111912063", "subject": "Compiler Design",         "day": "friday",    "time": "02:00 PM"},
    # Saturday
    {"teacher_chat_id": "1111912063", "subject": "Programming Lab",         "day": "saturday",  "time": "11:00 AM"},
]


def seed():
    db.init_db()

    print("\n── Seeding Teachers ──")
    teacher_id_map = {}
    for t in TEACHERS:
        tid = db.upsert_teacher(t["name"], t["telegram_chat_id"])
        teacher_id_map[t["telegram_chat_id"]] = tid
        print(f"  ✅ {t['name']} (chat_id={t['telegram_chat_id']}) → id={tid}")

    print("\n── Seeding Classes ──")
    for c in CLASSES:
        tid = teacher_id_map[c["teacher_chat_id"]]
        cid = db.upsert_class(tid, c["subject"], c["day"], c["time"])
        print(f"  ✅ {c['subject']:<35} {c['day']:<12} {c['time']} → id={cid}")

    print(f"\n── Done! {len(CLASSES)} classes across 6 days seeded. ──\n")


if __name__ == "__main__":
    seed()
