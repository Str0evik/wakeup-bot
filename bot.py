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
TIMEZONE_OFFSET = 3
TIMEZONE = timezone(timedelta(hours=TIMEZONE_OFFSET))

SLEEP_HOURS = 8
FALL_ASLEEP_MIN = 15

# --- База данных ---
def init_db():
    conn = sqlite3.connect("reminders.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            chat_id INTEGER PRIMARY KEY,
            wake_time TEXT NOT NULL,
            sent_count INTEGER DEFAULT 0,
            wake_datetime TEXT,
            bedtime_datetime TEXT,
            bedtime_sent INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

def save_reminder(chat_id: int, wake_time: str, wake_datetime: str, bedtime_datetime: str):
    conn = sqlite3.connect("reminders.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO reminders (chat_id, wake_time, sent_count, wake_datetime, bedtime_datetime, bedtime_sent)
        VALUES (?, ?, 0, ?, ?, 0)
        ON CONFLICT(chat_id) DO UPDATE SET
            wake_time = excluded.wake_time,
            sent_count = 0,
            wake_datetime = excluded.wake_datetime,
            bedtime_datetime = excluded.bedtime_datetime,
            bedtime_sent = 0
    """, (chat_id, wake_time, wake_datetime, bedtime_datetime))
    conn.commit()
    conn.close()

def get_pending_reminders():
    conn = sqlite3.connect("reminders.db")
    cursor = conn.cursor()
    cursor.execute("SELECT chat_id, wake_time, sent_count, wake_datetime, bedtime_datetime, bedtime_sent FROM reminders")
    rows = cursor.fetchall()
    conn.close()
    return rows

def update_sent_count(chat_id: int, count: int):
    conn = sqlite3.connect("reminders.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE reminders SET sent_count = ? WHERE chat_id = ?", (count, chat_id))
    conn.commit()
    conn.close()

def update_bedtime_sent(chat_id: int, count: int):
    conn = sqlite3.connect("reminders.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE reminders SET bedtime_sent = ? WHERE chat_id = ?", (count, chat_id))
    conn.commit()
    conn.close()

def delete_reminder(chat_id: int):
    conn = sqlite3.connect("reminders.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM reminders WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()

# --- Тексты ---
WAKE_MESSAGES = [
    "🔔 Пора вставать! Ты спал до {time}. Доброе утро!",
    "⏰ Вставай! Уже {time}, ты проспишь!",
    "🚨 Последнее предупреждение! {time} — вставай немедленно!",
]

BEDTIME_MESSAGE = "🌙 Пора ложиться! Чтобы встать в {wake}, тебе нужно заснуть до {bedtime}. Спокойной ночи!"

# --- Обработчик /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

        now = datetime.now(TIMEZONE)
        wake_hour = int(time_code[:2])
        wake_minute = int(time_code[2:])
        wake_dt = now.replace(hour=wake_hour, minute=wake_minute, second=0, microsecond=0)

        if wake_dt <= now:
            wake_dt += timedelta(days=1)

        # Вычисляем время отхода ко сну
        bedtime_dt = wake_dt - timedelta(hours=SLEEP_HOURS, minutes=FALL_ASLEEP_MIN)
        # Напоминание — за 30 минут до отхода
        bedtime_reminder_dt = bedtime_dt - timedelta(minutes=30)

        # Определяем, ставить ли bedtime-напоминание
        minutes_until_bedtime = (bedtime_dt - now).total_seconds() / 60

        if minutes_until_bedtime > 30:
            # До отхода больше 30 минут — ставим за 30 минут
            bedtime_final = bedtime_reminder_dt
            bedtime_note = ""
        elif 5 < minutes_until_bedtime <= 30:
            # До отхода 5-30 минут — ставим через 5 минут
            bedtime_final = now + timedelta(minutes=5)
            bedtime_note = " (скоро ложиться)"
        else:
            # Отход уже прошёл или меньше 5 минут — не ставим
            bedtime_final = None
            bedtime_note = ""

        if bedtime_final:
            save_reminder(
                update.effective_chat.id,
                time_code,
                wake_dt.isoformat(),
                bedtime_final.isoformat()
            )
            bedtime_str = bedtime_dt.strftime("%H:%M")
            reply = (
                f"✅ Готово!\n\n"
                f"🌙 Напомню лечь в {bedtime_final.strftime('%H:%M')}{bedtime_note}, чтобы выспаться.\n"
                f"🔔 Разбужу в {formatted_time} тремя сообщениями.\n\n"
                f"Спокойной ночи!"
            )
            print(f"[{now.strftime('%H:%M:%S')}] {update.effective_chat.id}: встать {formatted_time}, лечь {bedtime_str}, напоминание {bedtime_final.strftime('%H:%M')}")
        else:
            save_reminder(
                update.effective_chat.id,
                time_code,
                wake_dt.isoformat(),
                ""
            )
            reply = (
                f"✅ Готово!\n\n"
                f"🔔 Разбужу в {formatted_time} тремя сообщениями.\n\n"
                f"Спокойной ночи!"
            )
            print(f"[{now.strftime('%H:%M:%S')}] {update.effective_chat.id}: встать {formatted_time} (без bedtime)")

        await update.message.reply_text(reply)
    else:
        await update.message.reply_text(
            "Привет! Я помогу тебе проснуться. "
            "Зайди на сайт, выбери время и нажми «Напомнить в Telegram»."
        )

# --- Планировщик ---
async def check_reminders(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(TIMEZONE)
    print(f"[{now.strftime('%H:%M:%S')}] Проверка напоминаний...")

    for chat_id, wake_time, sent_count, wake_datetime_str, bedtime_datetime_str, bedtime_sent in get_pending_reminders():
        formatted_time = f"{wake_time[:2]}:{wake_time[2:]}"

        # --- НАПОМИНАНИЕ О СНЕ (только одно) ---
        if bedtime_datetime_str and bedtime_sent == 0:
            try:
                bedtime_dt = datetime.fromisoformat(bedtime_datetime_str)
            except Exception as e:
                print(f"Ошибка парсинга bedtime: {e}")
                bedtime_dt = None

            if bedtime_dt and now >= bedtime_dt:
                try:
                    # Время, когда нужно заснуть
                    bedtime_target = bedtime_dt + timedelta(minutes=30)
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=BEDTIME_MESSAGE.format(
                            wake=formatted_time,
                            bedtime=bedtime_target.strftime("%H:%M")
                        )
                    )
                    update_bedtime_sent(chat_id, 1)
                    print(f"[{now.strftime('%H:%M:%S')}] Отправлено bedtime-сообщение для {chat_id}")
                except Exception as e:
                    print(f"Ошибка отправки bedtime: {e}")

        # --- НАПОМИНАНИЕ О ПРОБУЖДЕНИИ ---
        try:
            wake_dt = datetime.fromisoformat(wake_datetime_str)
        except Exception as e:
            print(f"Ошибка парсинга wake: {e}")
            continue

        if sent_count == 0 and now >= wake_dt:
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=WAKE_MESSAGES[0].format(time=formatted_time)
                )
                update_sent_count(chat_id, 1)
                print(f"[{now.strftime('%H:%M:%S')}] Отправлено 1-е wake-сообщение для {chat_id}")
            except Exception as e:
                print(f"Ошибка отправки: {e}")

        elif sent_count == 1 and now >= wake_dt + timedelta(minutes=1):
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=WAKE_MESSAGES[1].format(time=formatted_time)
                )
                update_sent_count(chat_id, 2)
                print(f"[{now.strftime('%H:%M:%S')}] Отправлено 2-е wake-сообщение для {chat_id}")
            except Exception as e:
                print(f"Ошибка отправки: {e}")

        elif sent_count == 2 and now >= wake_dt + timedelta(minutes=2):
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=WAKE_MESSAGES[2].format(time=formatted_time)
                )
                delete_reminder(chat_id)
                print(f"[{now.strftime('%H:%M:%S')}] Отправлено 3-е wake-сообщение для {chat_id}, напоминание удалено")
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

    app.job_queue.run_repeating(check_reminders, interval=60, first=5)

    print(f"Бот запущен. Часовой пояс: UTC+{TIMEZONE_OFFSET}")
    print("Нажми Ctrl+C для остановки.")
    app.run_polling()
