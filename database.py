"""
database.py — P.R.O.F. PostgreSQL data layer (replaces db.py)

Provides the same save_message / get_history / init_db interface that prof.py
calls, plus new schedule-management functions backed by Neon PostgreSQL.
"""

import os
from datetime import date, datetime, timezone

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import Base, Teacher, Class, ClassSession, ConversationMemory

load_dotenv()

_DATABASE_URL = os.getenv("DATABASE_URL", "")

_engine = create_engine(
    _DATABASE_URL,
    pool_pre_ping=True,   # detect stale connections (important for serverless Neon)
    pool_size=5,
    max_overflow=10,
)
_SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)


# ─────────────────────────────────────────────
# SETUP
# ─────────────────────────────────────────────

def init_db():
    """Create all tables if they don't exist yet."""
    Base.metadata.create_all(_engine)
    print("[DB] PostgreSQL database ready.")


# ─────────────────────────────────────────────
# TEACHERS
# ─────────────────────────────────────────────

def get_all_teachers(active_only=True):
    """Return list of teacher dicts."""
    s = _SessionLocal()
    try:
        q = s.query(Teacher)
        if active_only:
            q = q.filter_by(active=True)
        return [
            {"id": t.id, "name": t.name, "telegram_chat_id": t.telegram_chat_id}
            for t in q.all()
        ]
    finally:
        s.close()


def upsert_teacher(name: str, telegram_chat_id: str) -> int:
    """Insert or update a teacher. Returns the teacher id."""
    s = _SessionLocal()
    try:
        t = s.query(Teacher).filter_by(telegram_chat_id=str(telegram_chat_id)).first()
        if t:
            t.name = name
            t.active = True
        else:
            t = Teacher(name=name, telegram_chat_id=str(telegram_chat_id))
            s.add(t)
        s.commit()
        s.refresh(t)
        return t.id
    finally:
        s.close()


# ─────────────────────────────────────────────
# CLASSES  (recurring weekly schedule)
# ─────────────────────────────────────────────

def upsert_class(teacher_id: int, subject: str, day_of_week: str, time: str) -> int:
    """Insert or update a class slot. Returns the class id."""
    s = _SessionLocal()
    try:
        c = s.query(Class).filter_by(
            teacher_id=teacher_id,
            subject=subject,
            day_of_week=day_of_week.lower(),
        ).first()
        if c:
            c.time = time
            c.active = True
        else:
            c = Class(
                teacher_id=teacher_id,
                subject=subject,
                day_of_week=day_of_week.lower(),
                time=time,
            )
            s.add(c)
        s.commit()
        s.refresh(c)
        return c.id
    finally:
        s.close()


def get_todays_classes():
    """
    Return a list of dicts for every active class scheduled for today's day of week.
    Each dict has: teacher_name, telegram_chat_id, subject, time, class_id.
    Sorted by time string (lexicographic — works for HH:MM AM/PM if consistent).
    """
    today = date.today().strftime("%A").lower()   # e.g. "monday"
    s = _SessionLocal()
    try:
        rows = (
            s.query(Teacher, Class)
            .join(Class, Class.teacher_id == Teacher.id)
            .filter(
                Class.day_of_week == today,
                Class.active == True,
                Teacher.active == True,
            )
            .order_by(Class.time)
            .all()
        )
        return [
            {
                "teacher_name":      t.name,
                "telegram_chat_id":  t.telegram_chat_id,
                "subject":           c.subject,
                "time":              c.time,
                "class_id":          c.id,
            }
            for t, c in rows
        ]
    finally:
        s.close()


def get_all_classes_by_teacher(telegram_chat_id: str):
    """Return all active classes for a specific teacher (all days)."""
    s = _SessionLocal()
    try:
        t = s.query(Teacher).filter_by(telegram_chat_id=str(telegram_chat_id)).first()
        if not t:
            return []
        rows = s.query(Class).filter_by(teacher_id=t.id, active=True).order_by(Class.day_of_week, Class.time).all()
        return [
            {"subject": c.subject, "day": c.day_of_week, "time": c.time, "class_id": c.id}
            for c in rows
        ]
    finally:
        s.close()


def get_todays_status_for_teacher(telegram_chat_id: str):
    """
    Return today's classes for a teacher with their current session status.
    Used to give the AI accurate live context when a teacher asks about their schedule.
    Returns list of dicts: {subject, time, status, rescheduled_to, instructions}
    """
    today = date.today()
    day_name = today.strftime("%A").lower()
    s = _SessionLocal()
    try:
        teacher = s.query(Teacher).filter_by(telegram_chat_id=str(telegram_chat_id)).first()
        if not teacher:
            return []
        classes = s.query(Class).filter_by(teacher_id=teacher.id, day_of_week=day_name, active=True).order_by(Class.time).all()
        result = []
        for c in classes:
            session = s.query(ClassSession).filter_by(class_id=c.id, session_date=today).first()
            result.append({
                "subject":        c.subject,
                "time":           c.time,
                "status":         session.status if session else "NOT ASKED YET",
                "rescheduled_to": session.rescheduled_to if session else None,
                "instructions":   session.instructions if session else None,
            })
        return result
    finally:
        s.close()


def get_conflicts(day_of_week: str, time_str: str, exclude_class_id: int = None, window_minutes: int = 60):
    """
    Return any active class on the same day within `window_minutes` of the given time.
    Used to detect scheduling conflicts before accepting a reschedule.
    """
    from datetime import datetime as _dt

    target_dt = None
    for fmt in ["%I:%M %p", "%I %p", "%H:%M", "%H"]:
        try:
            target_dt = _dt.strptime(time_str.strip().upper(), fmt)
            break
        except ValueError:
            pass
    if not target_dt:
        return []

    s = _SessionLocal()
    try:
        q = (
            s.query(Teacher, Class)
            .join(Class, Class.teacher_id == Teacher.id)
            .filter(
                Class.day_of_week == day_of_week.lower(),
                Class.active == True,
                Teacher.active == True,
            )
        )
        if exclude_class_id:
            q = q.filter(Class.id != exclude_class_id)

        conflicts = []
        for t, c in q.all():
            for fmt in ["%I:%M %p", "%I %p", "%H:%M"]:
                try:
                    class_dt = _dt.strptime(c.time.strip().upper(), fmt)
                    diff_mins = abs((target_dt - class_dt).total_seconds()) / 60
                    if diff_mins < window_minutes:
                        conflicts.append({
                            "subject": c.subject,
                            "teacher": t.name,
                            "time":    c.time,
                            "day":     c.day_of_week,
                        })
                    break
                except ValueError:
                    pass
        return conflicts
    finally:
        s.close()


# ─────────────────────────────────────────────
# CLASS SESSIONS  (per-day outcomes)
# ─────────────────────────────────────────────

def create_class_session(class_id: int, session_date=None) -> int:
    """Create a PENDING session for today. Returns session id."""
    if session_date is None:
        session_date = date.today()
    s = _SessionLocal()
    try:
        # Avoid duplicates — return existing if already created today
        existing = s.query(ClassSession).filter_by(
            class_id=class_id, session_date=session_date
        ).first()
        if existing:
            return existing.id
        session = ClassSession(class_id=class_id, session_date=session_date, status="PENDING")
        s.add(session)
        s.commit()
        s.refresh(session)
        return session.id
    finally:
        s.close()


def update_class_session(session_id: int, status: str, rescheduled_to=None, instructions=None):
    """Update the outcome of a class session."""
    s = _SessionLocal()
    try:
        row = s.query(ClassSession).filter_by(id=session_id).first()
        if not row:
            return
        row.status = status
        if rescheduled_to:
            row.rescheduled_to = rescheduled_to
        if instructions:
            row.instructions = instructions
        if status in ("CONFIRMED", "CANCELLED", "RESCHEDULED"):
            row.announced_at = datetime.now(timezone.utc)
        s.commit()
    finally:
        s.close()


def get_todays_public_schedule():
    """
    Return today's non-cancelled classes for public student display.
    Sorted by time. Each dict: {teacher_name, subject, time, status, rescheduled_to}.
    """
    today = date.today()
    day_name = today.strftime("%A").lower()
    s = _SessionLocal()
    try:
        rows = (
            s.query(Teacher, Class, ClassSession)
            .join(Class, Class.teacher_id == Teacher.id)
            .outerjoin(
                ClassSession,
                (ClassSession.class_id == Class.id) & (ClassSession.session_date == today),
            )
            .filter(
                Class.day_of_week == day_name,
                Class.active == True,
                Teacher.active == True,
            )
            .order_by(Class.time)
            .all()
        )
        result = []
        for t, c, cs in rows:
            status = cs.status if cs else "NOT ASKED YET"
            if status == "CANCELLED":
                continue
            result.append({
                "teacher_name":  t.name,
                "subject":       c.subject,
                "time":          c.time,
                "status":        status,
                "rescheduled_to": cs.rescheduled_to if cs else None,
            })
        return result
    finally:
        s.close()


def get_recent_sessions(days=7):
    """Return last N days of class sessions for a quick history view."""
    from datetime import timedelta
    cutoff = date.today() - timedelta(days=days)
    s = _SessionLocal()
    try:
        rows = (
            s.query(ClassSession, Class, Teacher)
            .join(Class, Class.id == ClassSession.class_id)
            .join(Teacher, Teacher.id == Class.teacher_id)
            .filter(ClassSession.session_date >= cutoff)
            .order_by(ClassSession.session_date.desc(), Class.time)
            .all()
        )
        return [
            {
                "date":           str(cs.session_date),
                "teacher":        t.name,
                "subject":        c.subject,
                "time":           c.time,
                "status":         cs.status,
                "rescheduled_to": cs.rescheduled_to,
                "instructions":   cs.instructions,
            }
            for cs, c, t in rows
        ]
    finally:
        s.close()


# ─────────────────────────────────────────────
# CONVERSATION MEMORY  (replaces SQLite db.py)
# ─────────────────────────────────────────────

def save_message(chat_id, user_name, role, message):
    s = _SessionLocal()
    try:
        s.add(ConversationMemory(
            chat_id=str(chat_id),
            user_name=user_name,
            role=role,
            message=message,
        ))
        s.commit()
    finally:
        s.close()


def get_history(chat_id, limit=20):
    """Return last `limit` messages as formatted strings, oldest first."""
    s = _SessionLocal()
    try:
        rows = (
            s.query(ConversationMemory)
            .filter_by(chat_id=str(chat_id))
            .order_by(ConversationMemory.created_at.desc())
            .limit(limit)
            .all()
        )
        rows = list(reversed(rows))
        return [
            f"[{r.created_at.strftime('%Y-%m-%d') if r.created_at else ''}] "
            f"{'Bot' if r.role == 'bot' else 'Teacher'}: {r.message}"
            for r in rows
        ]
    finally:
        s.close()


def get_history_structured(chat_id, limit=30):
    """
    Return the last `limit` messages as OpenRouter-compatible message dicts.
    Alternating role: "user" / "assistant" — what the model expects for memory.
    """
    s = _SessionLocal()
    try:
        rows = (
            s.query(ConversationMemory)
            .filter_by(chat_id=str(chat_id))
            .order_by(ConversationMemory.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "role":    "assistant" if r.role == "bot" else "user",
                "content": r.message,
            }
            for r in reversed(rows)
        ]
    finally:
        s.close()


def get_history_summary(chat_id):
    s = _SessionLocal()
    try:
        return s.query(ConversationMemory).filter_by(chat_id=str(chat_id)).count()
    finally:
        s.close()
