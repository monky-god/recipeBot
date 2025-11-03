#импорты
import asyncio
import random
import psycopg2
import google.generativeai as genai
from datetime import datetime
from urllib.parse import urlparse
import os
from dotenv import load_dotenv
load_dotenv()

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

# токены
TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# подключение к Railway PostgreSQL
DATABASE_URL = os.getenv("DATABASE_URL")
result = urlparse(DATABASE_URL)

DB_CONFIG = {
    "dbname": result.path[1:],  # убираем /
    "user": result.username,
    "password": result.password,
    "host": result.hostname,
    "port": result.port
}

MODEL = "models/gemini-2.5-flash"
SYSTEM_INSTRUCTION = (
    "Ты — дружелюбный кулинарный ассистент 🤖.\n"
    "Отвечай просто и понятно.\n"
    "Если даны ингредиенты — предложи рецепт.\n"
    "Если встречается слово 'пример' — добавь короткий пример блюда."
)


bot = Bot(token=TOKEN)
dp = Dispatcher()
user_waiting_note = {}



# Функции работы с базой
def get_connection():
    return psycopg2.connect(**DB_CONFIG)


def init_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        user_id BIGINT UNIQUE,
        username TEXT,
        first_name TEXT,
        last_activity TIMESTAMP
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS requests (
        id SERIAL PRIMARY KEY,
        user_id BIGINT REFERENCES users(user_id),
        question TEXT,
        answer TEXT,
        timestamp TIMESTAMP
    );
    """)
    conn.commit()
    cur.close()
    conn.close()

# Команды
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    now = datetime.now()

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM users WHERE user_id = %s;", (user_id,))
    if not cur.fetchone():
        cur.execute(
            "INSERT INTO users (user_id, username, first_name, last_activity) VALUES (%s, %s, %s, %s);",
            (user_id, username, first_name, now)
        )
        conn.commit()
    cur.close()
    conn.close()

    await message.answer(
        f"Привет, {first_name or username or 'друг'}!\n"
        f"Я Recipe Bot 🍳\n"
        f"Помогаю находить рецепты и сохранять заметки!\n\n"
        f"Напиши /help чтобы узнать, что я умею."
    )

def update_user_activity(user_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET last_activity = %s WHERE user_id = %s;", (datetime.now(), user_id))
    conn.commit()
    cur.close()
    conn.close()

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "📋 Команды:\n"
        "/start — начать работу\n"
        "/help — помощь\n"
        "/info — инфо о пользователе\n"
        "/find — найти рецепт по ингредиентам\n"
        "/random — случайный рецепт\n"
        "/add — добавить заметку\n"
        "/notes — показать заметки\n"
        "/history — история запросов\n"
        "/clear — очистить историю\n"
        "/ask — вопрос к AI"
    )


@dp.message(Command("info"))
async def cmd_info(message: types.Message):
    update_user_activity(message.from_user.id)
    user_id = message.from_user.id
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT username, first_name, last_activity FROM users WHERE user_id = %s;", (user_id,))
    user = cur.fetchone()
    cur.close()
    conn.close()

    if user:
        username, first_name, last_activity = user
        await message.answer(
            f"👤 Пользователь: @{username or '-'}\n"
            f"Имя: {first_name or '-'}\n"
            f"Последняя активность: {last_activity}"
        )
    else:
        await message.answer("Ты ещё не зарегистрирован. Напиши /start")


@dp.message(Command("random"))
async def cmd_random(message: types.Message):
    recipes = [
        "🥗 Греческий салат — помидоры, огурцы, оливки и фета.",
        "🍝 Паста Болоньезе — фарш, томаты и сыр.",
        "🍳 Омлет с овощами — яйца, перец, шпинат.",
        "🍲 Куриный суп с лапшой — классика домашнего обеда.",
        "🍕 Домашняя пицца с колбасой и сыром."
    ]
    await message.answer(f"Случайный рецепт дня:\n\n{random.choice(recipes)}")


@dp.message(Command("find"))
async def cmd_find(message: types.Message):
    await message.answer("✍️ Напиши ингредиенты через запятую — я предложу рецепт.")


@dp.message(Command("add"))
async def cmd_add(message: types.Message):
    user_id = message.from_user.id
    user_waiting_note[user_id] = True
    await message.answer("Напиши заметку, которую хочешь сохранить.")


@dp.message(Command("notes"))
async def cmd_notes(message: types.Message):
    user_id = message.from_user.id
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT answer, timestamp FROM requests
        WHERE user_id = %s AND question = 'заметка'
        ORDER BY timestamp DESC LIMIT 5;
    """, (user_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        await message.answer("📭 У тебя пока нет заметок.")
    else:
        text = "🗒 Последние заметки:\n\n"
        for note, t in rows:
            text += f"[{t.strftime('%Y-%m-%d %H:%M')}] — {note}\n"
        await message.answer(text)

#обработчик команды clear
@dp.message(Command("clear"))
async def cmd_clear(message: types.Message):
    user_id = message.from_user.id
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM requests WHERE user_id = %s;", (user_id,))
    conn.commit()
    cur.close()
    conn.close()
    await message.answer("🧹 История и заметки очищены!")

#обработчик команды history
@dp.message(Command("history"))
async def cmd_history(message: types.Message):
    user_id = message.from_user.id
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT question, answer, timestamp FROM requests
        WHERE user_id = %s ORDER BY timestamp DESC LIMIT 5;
    """, (user_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        await message.answer("📜 История пуста.")
    else:
        text = "📜 Последние запросы:\n\n"
        for q, a, t in rows:
            text += f"{t.strftime('%H:%M %d.%m')} — {q}\nОтвет: {a[:150]}...\n\n"
        await message.answer(text)


@dp.message(Command("ask"))
async def cmd_ask(message: types.Message):
    await message.answer("🤖 Напиши свой вопрос — я задам его AI.")



#Обработка всех сообщений
@dp.message()
async def process_message(message: types.Message):
    user_id = message.from_user.id
    text = message.text
    # --- обновляем активность пользователя (или добавляем, если нет) ---
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT 1 FROM users WHERE user_id = %s;", (user_id,))
    if not cur.fetchone():
        cur.execute(
            "INSERT INTO users (user_id, username, first_name, last_activity) VALUES (%s, %s, %s, %s);",
            (user_id, message.from_user.username, message.from_user.first_name, datetime.now())
        )
    else:
        cur.execute("UPDATE users SET last_activity = %s WHERE user_id = %s;", (datetime.now(), user_id))

    conn.commit()
    cur.close()
    conn.close()
    #если бот ждёт заметку
    if user_waiting_note.get(user_id):
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO requests (user_id, question, answer, timestamp) VALUES (%s, %s, %s, %s);",
            (user_id, "заметка", text, datetime.now())
        )
        conn.commit()
        cur.close()
        conn.close()
        user_waiting_note[user_id] = False
        await message.answer("✅ Заметка сохранена!")
        return

    #обращение к AI
    prompt = f"{SYSTEM_INSTRUCTION}\n\nПользователь: {text}"
    try:
        model = genai.GenerativeModel(MODEL)
        response = model.generate_content(prompt)
        answer = response.text
    except Exception as e:
        answer = f"Ошибка при обращении к AI: {e}"

    # сохраняем в базу
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO requests (user_id, question, answer, timestamp) VALUES (%s, %s, %s, %s);",
        (user_id, text, answer, datetime.now())
    )
    conn.commit()
    cur.close()
    conn.close()
    update_user_activity(user_id)

    await message.answer(f"🤖 Ответ от повара Gemini:\n\n{answer}")



#Запуск и вывод  в терминал
async def main():
    init_db()
    print("✅ Бот запущен и готов к работе!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())