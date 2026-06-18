import asyncio
import logging
import sqlite3
import math
import re
import os
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
dp = Dispatcher()          # ← эта строка была потеряна

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

WELCOME_TEXT = (
    "Привет! Я чат-бот общедоступных Wi-Fi точек.\n\n"
    "Я могу помочь вам:\n"
    "- открыть карту с точками\n"
    "- найти список Wi-Fi точек\n"
    "- узнать, как подключиться к Wi-Fi\n\n"
    "Если что-то пойдёт не так, просто отправьте команду /start."
)

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

# ---------------------------------------------------------------------------
# Очистка и форматирование
# ---------------------------------------------------------------------------
REMOVE_PHRASES = [
    r'Доступная\s+для\s+подключения\s*(?:\([^)]*\))?\s*',
    r'Открытая\s+сеть\s*(?:\([^)]*\))?\s*',
    r'Общественное\s+пространство\s*',
    r'Остановки\s+общ\.?\s*транспорта\s*',
    r'Соц\.?\s*объекты\s*',
    r'Доступна\s+авторизация\s+через\s+ГосУслуги\s*,?\s*',
]

def remove_junk_phrases(text: str) -> str:
    for phrase in REMOVE_PHRASES:
        text = re.sub(phrase, '', text, flags=re.IGNORECASE)
    return text.strip()

def clean_field(field: str) -> str:
    if not field:
        return ""
    field = re.sub(r'\(.*?\)', '', field)
    field = re.sub(r',\s*\d+\s*$', '', field)
    field = remove_junk_phrases(field)
    field = field.strip().strip(',;').strip()
    field = re.sub(r',\s*,', ',', field)
    field = re.sub(r'\s{2,}', ' ', field)
    field = re.sub(r'[«»""]', '', field)
    field = field.strip().strip(',;').strip()
    return field

def contains_house_number(text: str) -> bool:
    return bool(re.search(r'[а-яё\s]+,\s*\d+[а-я]?', text, re.IGNORECASE))

def extract_address_and_name(name: str, address: str, password: str):
    addr = clean_field(address)
    nm = clean_field(name) if name and name.strip() else ""
    nm = re.sub(r'[«»""]', '', nm)

    if addr and not contains_house_number(addr) and nm:
        if contains_house_number(nm) or re.search(r'д\.\s*\d+', nm, re.IGNORECASE):
            addr = f"{addr}, {nm}"
            nm = ""
        elif re.search(r'«[^»]*»', nm):
            pass
        else:
            pass

    if addr and not contains_house_number(addr):
        orig_addr = address or ""
        match = re.search(r'д\.\s*(\d+[а-я]?)', orig_addr, re.IGNORECASE)
        if match:
            addr += f", д. {match.group(1)}"

    if not addr and nm:
        pass
    elif not nm and not addr:
        nm = ""

    return addr, nm

def format_spot_line(index, name, address, password):
    addr, nm = extract_address_and_name(name, address, password)
    if addr and nm:
        line = f"{index}. Адрес: {addr} — {nm}\n"
    elif addr:
        line = f"{index}. Адрес: {addr}\n"
    elif nm:
        line = f"{index}. {nm}\n"
    else:
        line = f"{index}. Без названия\n"
    if password and password.strip():
        line += f"   Пароль: {password.strip()}\n"
    return line

# ---------------------------------------------------------------------------
# Обработчики событий
# ---------------------------------------------------------------------------
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

        spots = get_all_spots()
        total_pages = max(1, math.ceil(len(spots) / PAGE_SIZE))
        if page < 1 or page > total_pages:
            return

        start_idx = (page - 1) * PAGE_SIZE
        end_idx = min(page * PAGE_SIZE, len(spots))
        group = spots[start_idx:end_idx]

        msg = f"Список Wi-Fi точек (с {start_idx+1} по {end_idx}):\n\n"
        for i, spot in enumerate(group, start_idx+1):
            name, address, password, _ = spot
            msg += format_spot_line(i, name, address, password)

        try:
            await event.message.edit(
                text=msg,
                attachments=[build_pagination_keyboard(page, total_pages)]
            )
        except Exception:
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
            name, address, password, _ = spot
            msg += format_spot_line(i, name, address, password)

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
                text=WELCOME_TEXT,
                attachments=[build_main_menu()]
            )
        except Exception:
            try:
                await event.message.delete()
            except Exception:
                pass
            await event.message.answer(
                text=WELCOME_TEXT,
                attachments=[build_main_menu()]
            )

@dp.message_created()
async def handle_all_messages(event: MessageCreated):
    message_body = event.message.body
    if hasattr(message_body, 'text') and message_body.text:
        text = message_body.text.strip()
        if text in ('/start', '/help'):
            await event.message.answer(
                text=WELCOME_TEXT,
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
    try:
        await dp.start_polling(bot)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\nБот остановлен.")
    finally:
        if hasattr(bot, 'session') and bot.session:
            await bot.session.close()
        print("Соединения закрыты.")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Остановка по требованию пользователя.")