import asyncio
import logging
import sqlite3
import math

from maxapi import Bot, Dispatcher
from maxapi.types import (
    BotStarted,
    MessageCreated,
    CallbackButton,
    LinkButton,
    ButtonsPayload,
    Attachment,
    MessageCallback,
)
from maxapi.filters.command import CommandStart

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = ""

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

print(f"Точек в базе: {cursor.execute('SELECT COUNT(*) FROM wifi_spots').fetchone()[0]}")

# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------
def get_all_spots():
    cursor.execute('SELECT name, address, password, instructions FROM wifi_spots')
    return cursor.fetchall()

def get_chat_id(event):
    if hasattr(event, 'chat') and hasattr(event.chat, 'chat_id'):
        return event.chat.chat_id
    if hasattr(event, 'message') and hasattr(event.message, 'recipient') and hasattr(event.message.recipient, 'chat_id'):
        return event.message.recipient.chat_id
    raise AttributeError(f"Не удалось извлечь chat_id из {type(event).__name__}")

# ---------------------------------------------------------------------------
# Клавиатуры и константы
# ---------------------------------------------------------------------------
MAP_URL = (
    "http://gis.gmolo.ru:8081/#projectId=16&cameraMode=map"
    "&backgroundColor=F2F2F2&layers=66eeb5ud80000u"
    "&map=12.257798/59.560297/30.097306/0.000000/0.000000"
    "&EXT_CLIENT_ID=3fcd6630-18c2-48df-85b8-93f669775f22"
)

PAGE_SIZE = 5

def build_main_menu():
    buttons = [
        [CallbackButton(text="Список Wi-Fi точек", payload="list_spots")],
        [LinkButton(text="Карта Wi-Fi точек", url=MAP_URL)],
        [CallbackButton(text="Инструкция по подключению", payload="manual")],
    ]
    payload = ButtonsPayload(buttons=buttons)
    return Attachment(type="inline_keyboard", payload=payload)

def build_pagination_keyboard(page: int, total_pages: int):
    buttons = []
    nav_row = []
    if page > 1:
        nav_row.append(CallbackButton(text="◀ Назад", payload=f"page_{page-1}"))
    nav_row.append(CallbackButton(text=f"Стр. {page}/{total_pages}", payload="noop"))
    if page < total_pages:
        nav_row.append(CallbackButton(text="Далее ▶", payload=f"page_{page+1}"))
    if nav_row:
        buttons.append(nav_row)
    buttons.append([CallbackButton(text="Назад в главное меню", payload="main_menu")])
    payload = ButtonsPayload(buttons=buttons)
    return Attachment(type="inline_keyboard", payload=payload)

def build_back_only_keyboard():
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
             "- найти список Wi-Fi точек\n"
             "- открыть карту с точками\n"
             "- узнать, как подключиться к Wi-Fi\n\n"
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

    if data.startswith("page_"):
        try:
            page = int(data.split("_")[1])
        except (IndexError, ValueError):
            return

        spots = get_all_spots()
        total_pages = max(1, math.ceil(len(spots) / PAGE_SIZE))
        if page < 1 or page > total_pages:
            return

        start_idx = (page - 1) * PAGE_SIZE
        end_idx = min(page * PAGE_SIZE, len(spots))
        group = spots[start_idx:end_idx]

        msg = f"Список Wi-Fi точек (с {start_idx+1} по {end_idx}):\n\n"
        for i, spot in enumerate(group, start_idx+1):
            name, address, password, instructions = spot
            msg += f"{i}. {name}\n"
            msg += f"   Адрес: {address}\n"
            if password:
                msg += f"   Пароль: {password}\n"
            msg += f"   Инструкция: {instructions}\n\n"

        # Редактируем текущее сообщение вместо удаления и отправки нового
        try:
            await event.message.edit(
                text=msg,
                attachments=[build_pagination_keyboard(page, total_pages)]
            )
        except Exception:
            # fallback: если edit не работает, отправляем новое (но с очисткой)
            try:
                await event.message.delete()
            except Exception:
                pass
            await event.message.answer(msg, attachments=[build_pagination_keyboard(page, total_pages)])

    elif data == "list_spots":
        spots = get_all_spots()
        if not spots:
            await event.message.answer("База данных пуста.")
            return

        total_pages = max(1, math.ceil(len(spots) / PAGE_SIZE))
        start_idx = 0
        end_idx = min(PAGE_SIZE, len(spots))
        group = spots[start_idx:end_idx]

        msg = f"Список Wi-Fi точек (с 1 по {end_idx}):\n\n"
        for i, spot in enumerate(group, 1):
            name, address, password, instructions = spot
            msg += f"{i}. {name}\n"
            msg += f"   Адрес: {address}\n"
            if password:
                msg += f"   Пароль: {password}\n"
            msg += f"   Инструкция: {instructions}\n\n"

        try:
            await event.message.edit(
                text=msg,
                attachments=[build_pagination_keyboard(1, total_pages)]
            )
        except Exception:
            try:
                await event.message.delete()
            except Exception:
                pass
            await event.message.answer(msg, attachments=[build_pagination_keyboard(1, total_pages)])

    elif data == "manual":
        try:
            await event.message.edit(
                text="Инструкция по подключению:\n\n"
                     "1. Включите Wi-Fi на устройстве.\n"
                     "2. Найдите сеть с названием, указанным в списке точек.\n"
                     "3. Если сеть защищена, введите пароль (также указан в списке).\n"
                     "4. Подключитесь и пользуйтесь интернетом!\n\n"
                     "Если сеть открытая, пароль не требуется.",
                attachments=[build_back_only_keyboard()]
            )
        except Exception:
            await event.message.answer(
                "Инструкция по подключению:\n\n"
                "1. Включите Wi-Fi на устройстве.\n"
                "2. Найдите сеть с названием, указанным в списке точек.\n"
                "3. Если сеть защищена, введите пароль (также указан в списке).\n"
                "4. Подключитесь и пользуйтесь интернетом!\n\n"
                "Если сеть открытая, пароль не требуется.",
                attachments=[build_back_only_keyboard()]
            )

    elif data == "main_menu":
        try:
            await event.message.edit(
                text="Главное меню:",
                attachments=[build_main_menu()]
            )
        except Exception:
            try:
                await event.message.delete()
            except Exception:
                pass
            await event.message.answer(
                "Главное меню:",
                attachments=[build_main_menu()]
            )

@dp.message_created()
async def handle_all_messages(event: MessageCreated):
    message_body = event.message.body
    if hasattr(message_body, 'text') and message_body.text:
        text = message_body.text.strip()
        if text in ('/start', '/help'):
            await event.message.answer(
                "Главное меню:",
                attachments=[build_main_menu()]
            )
            return
        await event.message.answer(
            "Используйте кнопки в главном меню. Если вы хотите вернуться, нажмите /start.",
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
