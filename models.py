from sqlalchemy import Column, Integer, String, Boolean, DateTime, Date, Text, ForeignKey
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func

Base = declarative_base()


class Teacher(Base):
    __tablename__ = "teachers"

    id               = Column(Integer, primary_key=True)
    name             = Column(String(100), nullable=False)
    telegram_chat_id = Column(String(50), unique=True, nullable=False)
    active           = Column(Boolean, default=True, nullable=False)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())

    classes = relationship("Class", back_populates="teacher", cascade="all, delete-orphan")


class Class(Base):
    __tablename__ = "classes"

    id         = Column(Integer, primary_key=True)
    teacher_id = Column(Integer, ForeignKey("teachers.id"), nullable=False)
    subject    = Column(String(100), nullable=False)
    day_of_week = Column(String(10), nullable=False)   # "monday" … "sunday"
    time       = Column(String(20), nullable=False)    # "09:00 AM"
    active     = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    teacher  = relationship("Teacher", back_populates="classes")
    sessions = relationship("ClassSession", back_populates="class_", cascade="all, delete-orphan")


class ClassSession(Base):
    """One row per class per day — tracks what actually happened."""
    __tablename__ = "class_sessions"

    id             = Column(Integer, primary_key=True)
    class_id       = Column(Integer, ForeignKey("classes.id"), nullable=False)
    session_date   = Column(Date, nullable=False)
    status         = Column(String(20), default="PENDING", nullable=False)
    rescheduled_to = Column(String(50), nullable=True)   # new time string if RESCHEDULED
    instructions   = Column(Text, nullable=True)
    announced_at   = Column(DateTime(timezone=True), nullable=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())

    class_ = relationship("Class", back_populates="sessions")


class ConversationMemory(Base):
    """Replaces the SQLite prof_memory.db — stores all bot ↔ teacher/student messages."""
    __tablename__ = "conversation_memory"

    id         = Column(Integer, primary_key=True)
    chat_id    = Column(String(50), nullable=False, index=True)
    user_name  = Column(String(100), nullable=False)
    role       = Column(String(20), nullable=False)   # "bot", "teacher", "user"
    message    = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
