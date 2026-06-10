import asyncio
import logging
import sqlite3
import math

from maxapi import Bot, Dispatcher
from maxapi.types import (
    BotStarted,
    MessageCreated,
    CallbackButton,
    ButtonsPayload,
    Attachment,
    MessageCallback,
)
from maxapi.filters.command import CommandStart

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = "f9LHodD0cOJEg9h4yFIJR37KNWS9FchffAw-rNlVkZ99uoninEOoiBeTgLbs43WufAX-dt5H4JPiqFNDmnTA"

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# ---------------------------------------------------------------------------
# База данных
# ---------------------------------------------------------------------------
conn = sqlite3.connect('wifi_points.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''
CREATE TABLE IF NOT EXISTS wifi_spots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    address TEXT,
    latitude REAL,
    longitude REAL,
    password TEXT,
    instructions TEXT
)
''')
conn.commit()

cursor.execute('SELECT COUNT(*) FROM wifi_spots')
if cursor.fetchone()[0] == 0:
    test_spots = [
        ("Библиотека им. Ленина", "ул. Воздвиженка, 3/5", 55.751244, 37.618423, "", "Сеть Moscow_WiFi без пароля"),
        ("ТЦ Европейский", "пл. Киевского Вокзала, 2", 55.744364, 37.566161, "euro_free", "Пароль: euro_free"),
        ("Кафе Кофеин", "ул. Тверская, 15", 55.765873, 37.605837, "cafein123", "Пароль: cafein123"),
        ("Макдоналдс", "ул. Арбат, 42", 55.750341, 37.590527, "", "Бесплатный Wi-Fi"),
        ("Коворкинг Старт", "пер. Хохловский, 5", 55.757623, 37.639546, "start123", "Пароль: start123"),
    ]
    for spot in test_spots:
        cursor.execute(
            'INSERT INTO wifi_spots (name, address, latitude, longitude, password, instructions) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            spot
        )
    conn.commit()
    print(f"Загружено тестовых точек: {len(test_spots)}")

print(f"Точек в базе: {cursor.execute('SELECT COUNT(*) FROM wifi_spots').fetchone()[0]}")

# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------
def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    return round(R * c, 2)

def find_nearest_spots(user_lat, user_lon, limit=5):
    cursor.execute('SELECT name, address, latitude, longitude, password, instructions FROM wifi_spots')
    spots = cursor.fetchall()
    spots_with_distance = []
    for name, address, lat, lon, password, instructions in spots:
        distance = calculate_distance(user_lat, user_lon, lat, lon)
        spots_with_distance.append((distance, name, address, lat, lon, password, instructions))
    spots_with_distance.sort(key=lambda x: x[0])
    return spots_with_distance[:limit]

def get_all_spots():
    cursor.execute('SELECT name, address, password, instructions FROM wifi_spots')
    return cursor.fetchall()

def format_spots_message(spots):
    if not spots:
        return "Рядом нет сохранённых Wi-Fi точек."
    message = "Ближайшие точки Wi-Fi:\n\n"
    for i, spot in enumerate(spots, 1):
        distance, name, address, lat, lon, password, instructions = spot
        message += f"{i}. {name}\n"
        message += f"   Адрес: {address}\n"
        message += f"   Расстояние: {distance} км\n"
        if password:
            message += f"   Пароль: {password}\n"
        message += f"   Инструкция: {instructions}\n\n"
    first_lat, first_lon = spots[0][3], spots[0][4]
    message += f"Открыть на Яндекс.Картах: https://yandex.ru/maps/?text={first_lat},{first_lon}"
    return message

def format_all_spots_message(spots):
    if not spots:
        return "База данных пуста."
    message = "Список всех Wi-Fi точек:\n\n"
    for i, spot in enumerate(spots, 1):
        name, address, password, instructions = spot
        message += f"{i}. {name}\n"
        message += f"   Адрес: {address}\n"
        if password:
            message += f"   Пароль: {password}\n"
        message += f"   Инструкция: {instructions}\n\n"
    return message

def get_chat_id(event):
    if hasattr(event, 'chat') and hasattr(event.chat, 'chat_id'):
        return event.chat.chat_id
    if hasattr(event, 'message') and hasattr(event.message, 'recipient') and hasattr(event.message.recipient, 'chat_id'):
        return event.message.recipient.chat_id
    raise AttributeError(f"Не удалось извлечь chat_id из {type(event).__name__}")

# ---------------------------------------------------------------------------
# Клавиатуры
# ---------------------------------------------------------------------------
def build_main_menu():
    buttons = [
        [CallbackButton(text="Список Wi-Fi точек", payload="list_spots")],
        [CallbackButton(text="Карта Wi-Fi точек", payload="map_spots")],
        [CallbackButton(text="Проблемы с сетью", payload="problem")],
        [CallbackButton(text="Предложить Wi-Fi точку", payload="suggest")],
        [CallbackButton(text="Инструкция по подключению", payload="manual")],
    ]
    payload = ButtonsPayload(buttons=buttons)
    return Attachment(type="inline_keyboard", payload=payload)

def build_back_button():
    buttons = [[CallbackButton(text="Назад в главное меню", payload="main_menu")]]
    payload = ButtonsPayload(buttons=buttons)
    return Attachment(type="inline_keyboard", payload=payload)

# ---------------------------------------------------------------------------
# Обработчики событий
# ---------------------------------------------------------------------------
@dp.bot_started()
async def on_bot_started(event: BotStarted):
    chat_id = get_chat_id(event)
    await bot.send_message(
        chat_id=chat_id,
        text="Привет! Я чат-бот общедоступных Wi-Fi точек.\n\n"
             "Я могу помочь вам:\n"
             "- найти общедоступные Wi-Fi точки\n"
             "- сообщить о проблеме с сетью\n"
             "- предложить новую Wi-Fi точку\n"
             "- узнать, как подключиться к Wi-Fi точкам\n\n"
             "Если что-то пойдёт не так, просто отправьте команду /start.",
        attachments=[build_main_menu()]
    )

@dp.message_created(CommandStart())
async def cmd_start(event: MessageCreated):
    await event.message.answer(
        "Главное меню:",
        attachments=[build_main_menu()]
    )

@dp.message_callback()
async def handle_callback(event: MessageCallback):
    data = event.callback.payload

    if data == "list_spots":
        spots = get_all_spots()
        if spots:
            await event.message.answer(format_all_spots_message(spots))
        else:
            await event.message.answer("База данных пуста.")
        # Кнопка назад
        await event.message.answer("Вы можете вернуться в главное меню.", attachments=[build_back_button()])

    elif data == "map_spots":
        await event.message.answer(
            "Отправьте мне вашу геолокацию (через значок скрепки в поле ввода), и я покажу ближайшие точки на карте.",
            attachments=[build_back_button()]
        )

    elif data == "problem":
        await event.message.answer(
            "Если у вас возникли проблемы с подключением к Wi-Fi точке, опишите ситуацию в ответном сообщении. "
            "Мы передадим информацию администратору.",
            attachments=[build_back_button()]
        )

    elif data == "suggest":
        await event.message.answer(
            "Чтобы предложить новую Wi-Fi точку, напишите её адрес, название и (если знаете) пароль. "
            "Мы рассмотрим ваше предложение!",
            attachments=[build_back_button()]
        )

    elif data == "manual":
        await event.message.answer(
            "Инструкция по подключению:\n\n"
            "1. Включите Wi-Fi на устройстве.\n"
            "2. Найдите сеть с названием, указанным в списке точек.\n"
            "3. Если сеть защищена, введите пароль (также указан в списке).\n"
            "4. Подключитесь и пользуйтесь интернетом!\n\n"
            "Если сеть открытая, пароль не требуется.",
            attachments=[build_back_button()]
        )

    elif data == "main_menu":
        await event.message.answer(
            "Главное меню:",
            attachments=[build_main_menu()]
        )

    await event.answer()

@dp.message_created()
async def handle_all_messages(event: MessageCreated):
    chat_id = get_chat_id(event)
    message_body = event.message.body

    # Попытка извлечь координаты из геолокации
    user_lat = user_lon = None
    if hasattr(message_body, 'location') and message_body.location is not None:
        loc = message_body.location
        if hasattr(loc, 'latitude'):
            user_lat, user_lon = loc.latitude, loc.longitude
        elif isinstance(loc, dict):
            user_lat, user_lon = loc.get('latitude'), loc.get('longitude')

    if not user_lat and hasattr(message_body, 'attachments'):
        for att in message_body.attachments:
            if getattr(att, 'type', '') == 'location':
                payload = getattr(att, 'payload', None)
                if payload:
                    if hasattr(payload, 'latitude'):
                        user_lat, user_lon = payload.latitude, payload.longitude
                    elif isinstance(payload, dict):
                        user_lat, user_lon = payload.get('latitude'), payload.get('longitude')
                break

    if user_lat and user_lon:
        print(f"Получена геолокация: {user_lat}, {user_lon}")
        nearest = find_nearest_spots(user_lat, user_lon)
        if not nearest:
            await event.message.answer("Рядом нет сохранённых Wi-Fi точек.")
        else:
            await event.message.answer(format_spots_message(nearest))
            try:
                await bot.send_location(chat_id=chat_id, latitude=nearest[0][3], longitude=nearest[0][4])
            except Exception as e:
                print(f"Ошибка отправки локации: {e}")
        # Кнопка назад после результата
        await event.message.answer("Вернуться в главное меню:", attachments=[build_back_button()])
        return

    # Текстовые сообщения
    if hasattr(message_body, 'text') and message_body.text:
        text = message_body.text.strip()
        if text in ('/start', '/help'):
            await event.message.answer(
                "Главное меню:",
                attachments=[build_main_menu()]
            )
            return
        # Все остальные тексты (жалобы, предложения и т.п.)
        await event.message.answer(
            "Спасибо за сообщение! Если вы хотите вернуться в главное меню, нажмите кнопку ниже.",
            attachments=[build_main_menu()]
        )

# ---------------------------------------------------------------------------
# Запуск
# ---------------------------------------------------------------------------
async def main():
    print("=" * 50)
    print("Wi-Fi бот для MAX запущен")
    print(f"Точек в базе: {cursor.execute('SELECT COUNT(*) FROM wifi_spots').fetchone()[0]}")
    print("=" * 50)
    await bot.delete_webhook()
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())