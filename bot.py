import asyncio
import logging
import sqlite3
import math
import os
import re
from dotenv import load_dotenv

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

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в .env")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

conn = sqlite3.connect('wifi_points.db', check_same_thread=False)
cursor = conn.cursor()

print(f"Точек в базе: {cursor.execute('SELECT COUNT(*) FROM wifi_spots').fetchone()[0]}")

def extract_locality(address):
    if not address:
        return ""
    addr = address.strip()
    match = re.search(r'(?:г\.|п\.|д\.|с\.|посёлок|городской\s+посёлок)\s*([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)*)', addr)
    if match:
        return match.group(1)
    parts = [p.strip() for p in addr.split(',')]
    if len(parts) >= 2:
        last = parts[-1]
        if re.match(r'^[А-ЯЁ][а-яё]+$', last):
            return last
    words = addr.split()
    for w in words:
        if w[0].isupper() and len(w) > 1:
            return w
    return ""

def get_all_spots():
    cursor.execute('SELECT address FROM wifi_spots ORDER BY id')
    addresses = [row[0] for row in cursor.fetchall()]
    addresses.sort(key=lambda a: (extract_locality(a).lower(), a.lower()))
    return addresses

def get_chat_id(event):
    if hasattr(event, 'chat') and hasattr(event.chat, 'chat_id'):
        return event.chat.chat_id
    if hasattr(event, 'message') and hasattr(event.message, 'recipient') and hasattr(event.message.recipient, 'chat_id'):
        return event.message.recipient.chat_id
    raise AttributeError(f"Не удалось извлечь chat_id из {type(event).__name__}")

WELCOME_TEXT = (
    "Привет! Я чат-бот общедоступных Wi-Fi точек в Гатчинском округе.\n\n"
    "Я могу помочь Вам:\n"
    "- открыть карту с точками Wi-Fi\n"
    "- найти Wi-Fi точку по списку\n"
    "- узнать, как подключиться к Wi-Fi\n\n"
    "Если что-то пойдёт не так, просто отправьте команду /start."
)

MANUAL_TEXT = (
    "Инструкция по подключению:\n\n"
    "1. Включите Wi-Fi на вашем устройстве.\n"
    "2. Выберите общедоступную сеть из списка или на карте и нажмите «Подключиться».\n"
    "3. При необходимости пройдите авторизацию в открывшемся окне браузера (это требование безопасности).\n"
    "4. После подтверждения доступ в интернет будет открыт.\n\n"
    "Если подключение не удалось:\n"
    "1. Перезагрузите Wi-Fi на устройстве (вкл/выкл).\n"
    "2. Удалите сеть из сохранённых («Забыть сеть») и попробуйте снова.\n"
    "3. Подойдите ближе к точке доступа (роутеру или стойке).\n\n"
    "Если сеть открытая, пароль не требуется."
)

MAP_URL = (
    "http://gis.gmolo.ru:8081/#projectId=16&cameraMode=map"
    "&backgroundColor=F2F2F2&layers=66eeb5ud80000u"
    "&map=12.257798/59.560297/30.097306/0.000000/0.000000"
    "&EXT_CLIENT_ID=3fcd6630-18c2-48df-85b8-93f669775f22"
)

PAGE_SIZE = 15

def build_main_menu():
    buttons = [
        [LinkButton(text="Карта Wi-Fi точек", url=MAP_URL)],
        [CallbackButton(text="Список Wi-Fi точек", payload="list_spots")],
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

@dp.bot_started()
async def on_bot_started(event: BotStarted):
    chat_id = get_chat_id(event)
    await bot.send_message(
        chat_id=chat_id,
        text=WELCOME_TEXT,
        attachments=[build_main_menu()]
    )

@dp.message_created(CommandStart())
async def cmd_start(event: MessageCreated):
    await event.message.answer(
        text=WELCOME_TEXT,
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

        all_addresses = get_all_spots()
        total_items = len(all_addresses)
        total_pages = max(1, math.ceil(total_items / PAGE_SIZE))
        if page < 1 or page > total_pages:
            return

        start_idx = (page - 1) * PAGE_SIZE
        end_idx = min(page * PAGE_SIZE, total_items)
        page_items = all_addresses[start_idx:end_idx]

        msg = f"Список Wi-Fi точек (с {start_idx+1} по {end_idx}):\n\n"
        for i, addr in enumerate(page_items, start_idx+1):
            msg += f"{i}. {addr}\n"

        try:
            await event.message.edit(
                text=msg,
                attachments=[build_pagination_keyboard(page, total_pages)]
            )
        except Exception:
            await event.message.answer(msg, attachments=[build_pagination_keyboard(page, total_pages)])

    elif data == "list_spots":
        all_addresses = get_all_spots()
        if not all_addresses:
            await event.message.answer("База данных пуста.")
            return

        total_items = len(all_addresses)
        total_pages = max(1, math.ceil(total_items / PAGE_SIZE))
        page_items = all_addresses[:PAGE_SIZE]

        msg = f"Список Wi-Fi точек (с 1 по {len(page_items)}):\n\n"
        for i, addr in enumerate(page_items, 1):
            msg += f"{i}. {addr}\n"

        try:
            await event.message.edit(
                text=msg,
                attachments=[build_pagination_keyboard(1, total_pages)]
            )
        except Exception:
            await event.message.answer(msg, attachments=[build_pagination_keyboard(1, total_pages)])

    elif data == "manual":
        try:
            await event.message.edit(text=MANUAL_TEXT, attachments=[build_back_only_keyboard()])
        except Exception:
            await event.message.answer(MANUAL_TEXT, attachments=[build_back_only_keyboard()])

    elif data == "main_menu":
        try:
            await event.message.edit(text=WELCOME_TEXT, attachments=[build_main_menu()])
        except Exception:
            await event.message.answer(text=WELCOME_TEXT, attachments=[build_main_menu()])

@dp.message_created()
async def handle_all_messages(event: MessageCreated):
    message_body = event.message.body
    if hasattr(message_body, 'text') and message_body.text:
        text = message_body.text.strip()
        if text in ('/start', '/help'):
            await event.message.answer(text=WELCOME_TEXT, attachments=[build_main_menu()])
            return
        await event.message.answer(
            "Используйте кнопки в главном меню. Если вы хотите вернуться, нажмите /start.",
            attachments=[build_main_menu()]
        )

async def main():
    print("=" * 50)
    print("Wi-Fi бот для MAX запущен")
    print(f"Точек в базе: {cursor.execute('SELECT COUNT(*) FROM wifi_spots').fetchone()[0]}")
    print("=" * 50)
    await bot.delete_webhook()
    try:
        await dp.start_polling(bot)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\nБот остановлен.")

if __name__ == '__main__':
    asyncio.run(main())