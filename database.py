import aiosqlite
import asyncio
from pathlib import Path

DB_PATH = Path("pravaha_core.db")

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS command_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transcript TEXT,
                command TEXT,
                response TEXT,
                execution_duration REAL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

async def log_command(transcript, intent, response, duration):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO command_logs (transcript, command, response, execution_duration)
            VALUES (?, ?, ?, ?)
        """, (transcript, intent, response, duration))
        await db.commit()

async def get_recent_logs(limit=10):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT transcript, response, timestamp FROM command_logs ORDER BY timestamp DESC LIMIT ?", (limit,)) as cursor:
            return await cursor.fetchall()

async def clear_logs():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM command_logs")
        await db.commit()
