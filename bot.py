from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, Defaults
import re
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден! Проверь файл .env")

# --- Настройки ---
TIMEZONE_OFFSET = 3  # Москва UTC+3. Если другой пояс — поменяй число.
TIMEZONE = timezone(timedelta(hours=TIMEZONE_OFFSET))

# --- База данных ---
def init_db():
    conn = sqlite3.connect("reminders.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            chat_id INTEGER PRIMARY KEY,
            wake_time TEXT NOT NULL,
            sent_count INTEGER DEFAULT 0,
            wake_datetime TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_reminder(chat_id: int, wake_time: str, wake_datetime: str):
    conn = sqlite3.connect("reminders.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO reminders (chat_id, wake_time, sent_count, wake_datetime)
        VALUES (?, ?, 0, ?)
        ON CONFLICT(chat_id) DO UPDATE SET
            wake_time = excluded.wake_time,
            sent_count = 0,
            wake_datetime = excluded.wake_datetime
    """, (chat_id, wake_time, wake_datetime))
    conn.commit()
    conn.close()

def get_pending_reminders():
    conn = sqlite3.connect("reminders.db")
    cursor = conn.cursor()
    cursor.execute("SELECT chat_id, wake_time, sent_count, wake_datetime FROM reminders")
    rows = cursor.fetchall()
    conn.close()
    return rows

def update_sent_count(chat_id: int, count: int):
    conn = sqlite3.connect("reminders.db")
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE reminders SET sent_count = ? WHERE chat_id = ?",
        (count, chat_id)
    )
    conn.commit()
    conn.close()

def delete_reminder(chat_id: int):
    conn = sqlite3.connect("reminders.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM reminders WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()

# --- Тексты сообщений ---
MESSAGES = [
    "🔔 Пора вставать! Ты спал до {time}. Доброе утро!",
    "⏰ Вставай! Уже {time}, ты проспишь!",
    "🚨 Последнее предупреждение! {time} — вставай немедленно!",
]

# --- Обработчик /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Проверка: если сообщение не текстовое — выходим
    if not update.message or not update.message.text:
        await update.message.reply_text(
            "Привет! Я помогу тебе проснуться. "
            "Зайди на сайт, выбери время и нажми «Напомнить в Telegram»."
        )
        return
    
    text = update.message.text
    match = re.search(r'(\d{4})', text)
    
    if match:
        time_code = match.group(1)
        formatted_time = f"{time_code[:2]}:{time_code[2:]}"
        
        # Считаем дату и время пробуждения
        now = datetime.now(TIMEZONE)
        wake_hour = int(time_code[:2])
        wake_minute = int(time_code[2:])
        wake_dt = now.replace(hour=wake_hour, minute=wake_minute, second=0, microsecond=0)
        
        # Если время уже прошло сегодня — ставим на завтра
        if wake_dt <= now:
            wake_dt += timedelta(days=1)
        
        save_reminder(
            update.effective_chat.id,
            time_code,
            wake_dt.isoformat()
        )
        
        print(f"[{now.strftime('%H:%M:%S')}] Сохранено напоминание для {update.effective_chat.id} на {formatted_time}")
        
        await update.message.reply_text(
            f"✅ Готово! Напомню тебе в {formatted_time}.\n"
            f"Разбужу тремя сообщениями с интервалом в минуту.\n"
            f"Спокойной ночи!"
        )
    else:
        await update.message.reply_text(
            "Привет! Я помогу тебе проснуться. "
            "Зайди на сайт, выбери время и нажми «Напомнить в Telegram»."
        )

# --- Планировщик ---
async def check_reminders(context: ContextTypes.DEFAULT_TYPE):
    """Проверяет, кому пора вставать, и отправляет напоминания."""
    now = datetime.now(TIMEZONE)
    print(f"[{now.strftime('%H:%M:%S')}] Проверка напоминаний...")
    
    for chat_id, wake_time, sent_count, wake_datetime_str in get_pending_reminders():
        try:
            wake_dt = datetime.fromisoformat(wake_datetime_str)
        except Exception as e:
            print(f"Ошибка парсинга даты: {e}")
            continue
        
        formatted_time = f"{wake_time[:2]}:{wake_time[2:]}"
        
        # Первое сообщение — в момент пробуждения
        if sent_count == 0 and now >= wake_dt:
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=MESSAGES[0].format(time=formatted_time)
                )
                update_sent_count(chat_id, 1)
                print(f"[{now.strftime('%H:%M:%S')}] Отправлено 1-е сообщение для {chat_id}")
            except Exception as e:
                print(f"Ошибка отправки: {e}")
        
        # Второе — через минуту
        elif sent_count == 1 and now >= wake_dt + timedelta(minutes=1):
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=MESSAGES[1].format(time=formatted_time)
                )
                update_sent_count(chat_id, 2)
                print(f"[{now.strftime('%H:%M:%S')}] Отправлено 2-е сообщение для {chat_id}")
            except Exception as e:
                print(f"Ошибка отправки: {e}")
        
        # Третье — ещё через минуту, затем удаляем
        elif sent_count == 2 and now >= wake_dt + timedelta(minutes=2):
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=MESSAGES[2].format(time=formatted_time)
                )
                delete_reminder(chat_id)
                print(f"[{now.strftime('%H:%M:%S')}] Отправлено 3-е сообщение для {chat_id}, напоминание удалено")
            except Exception as e:
                print(f"Ошибка отправки: {e}")

# --- Запуск ---
if __name__ == '__main__':
    init_db()
    
    app = ApplicationBuilder() \
        .token(BOT_TOKEN) \
        .defaults(Defaults(tzinfo=TIMEZONE)) \
        .connect_timeout(30) \
        .read_timeout(30) \
        .build()
    
    app.add_handler(CommandHandler("start", start))
    
    # Проверка каждую минуту
    app.job_queue.run_repeating(check_reminders, interval=60, first=5)
    
    print(f"Бот запущен. Часовой пояс: UTC+{TIMEZONE_OFFSET}")
    print("Нажми Ctrl+C для остановки.")
    app.run_polling()