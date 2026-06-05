from max_chatbot_python import GreenAPIBot, Notification
import sqlite3
import math
import requests

# ========== НАСТРОЙКИ ==========
ID_INSTANCE = "3100644334"
API_TOKEN = "2b317f072c24487a87ab9f1d1d51d2c831918c4368884eef97"

# ========== ПОДКЛЮЧЕНИЕ К БАЗЕ ДАННЫХ ==========
conn = sqlite3.connect('wifi_points.db', check_same_thread=False)
cursor = conn.cursor()

# Создаём таблицу
cursor.execute('DROP TABLE IF EXISTS wifi_spots')
cursor.execute('''
CREATE TABLE wifi_spots (
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

# Добавляем тестовые точки
test_spots = [
    ("Библиотека им. Ленина", "ул. Воздвиженка, 3/5", 55.751244, 37.618423, "", "Сеть Moscow_WiFi без пароля"),
    ("ТЦ Европейский", "пл. Киевского Вокзала, 2", 55.744364, 37.566161, "euro_free", "Пароль: euro_free"),
    ("Кафе Кофеин", "ул. Тверская, 15", 55.765873, 37.605837, "cafein123", "Пароль: cafein123"),
]

for spot in test_spots:
    cursor.execute(
        'INSERT INTO wifi_spots (name, address, latitude, longitude, password, instructions) VALUES (?, ?, ?, ?, ?, ?)',
        spot)
conn.commit()

print("Загружено точек: " + str(len(test_spots)))


# ========== ФУНКЦИЯ РАСЧЁТА РАССТОЯНИЯ ==========
def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    return round(R * c, 2)


# ========== ПОИСК БЛИЖАЙШИХ ТОЧЕК ==========
def find_nearest_spots(user_lat, user_lon, limit=5):
    cursor.execute('SELECT name, address, latitude, longitude, password, instructions FROM wifi_spots')
    spots = cursor.fetchall()
    spots_with_distance = []
    for spot in spots:
        name, address, lat, lon, password, instructions = spot
        distance = calculate_distance(user_lat, user_lon, lat, lon)
        spots_with_distance.append((distance, name, address, lat, lon, password, instructions))
    spots_with_distance.sort(key=lambda x: x[0])
    return spots_with_distance[:limit]


# ========== ОТПРАВКА КНОПКИ ==========
def send_location_button(notification):
    chat_id = notification.event.get('senderData', {}).get('chatId', '')

    url = f"https://3100.api.green-api.com/waInstance{ID_INSTANCE}/sendButtons/{API_TOKEN}"

    payload = {
        "chatId": chat_id,
        "message": "Нажмите на кнопку и отправьте ваше местоположение, чтобы найти ближайший Wi-Fi:",
        "buttons": [
            {
                "buttonId": "request_location",
                "buttonText": "Отправить местоположение"
            }
        ]
    }

    headers = {'Content-Type': 'application/json'}

    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            notification.answer("Чтобы найти Wi-Fi рядом, отправьте мне ваше местоположение через кнопку вложения.")
    except Exception as e:
        print("Ошибка при отправке кнопки: " + str(e))


# ========== ФОРМИРОВАНИЕ ОТВЕТА ==========
def format_spots_message(spots):
    if not spots:
        return "Рядом нет сохранённых Wi-Fi точек."

    message = "Ближайшие точки Wi-Fi:\n\n"
    for i, spot in enumerate(spots, 1):
        distance, name, address, lat, lon, password, instructions = spot
        message = message + str(i) + ". " + name + "\n"
        message = message + "   Адрес: " + address + "\n"
        message = message + "   Расстояние: " + str(distance) + " км\n"
        if password:
            message = message + "   Пароль: " + password + "\n"
        message = message + "   " + instructions + "\n\n"
    return message


# ========== ОСНОВНАЯ ЛОГИКА ==========
bot = GreenAPIBot(ID_INSTANCE, API_TOKEN)


@bot.router.message()
def handle_message(notification: Notification):
    try:
        # Получаем текст сообщения
        message_data = notification.event.get('messageData', {})
        message_text = message_data.get('textMessageData', {}).get('textMessage', '')
        message_lower = message_text.lower().strip()

        # Команда /start
        if message_lower == '/start':
            notification.answer(
                "Здравствуйте! Я бот для поиска бесплатного Wi-Fi.\n\n"
                "Нажмите на кнопку ниже и отправьте ваше местоположение, "
                "я покажу ближайшие точки доступа с паролями."
            )
            send_location_button(notification)
            return

        # Команда /help
        if message_lower == '/help':
            notification.answer(
                "Справка по командам:\n\n"
                "/start - начать работу\n"
                "/help - показать справку\n"
                "/spots - список всех точек Wi-Fi\n\n"
                "Чтобы найти Wi-Fi рядом, отправьте ваше местоположение."
            )
            return

        # Команда /spots - все точки
        if message_lower == '/spots':
            cursor.execute('SELECT name, address, latitude, longitude, password, instructions FROM wifi_spots')
            all_spots = cursor.fetchall()

            if not all_spots:
                notification.answer("База данных пуста. Добавьте точки вручную.")
                return

            message = "Список всех Wi-Fi точек:\n\n"
            for i, spot in enumerate(all_spots, 1):
                name, address, lat, lon, password, instructions = spot
                message = message + str(i) + ". " + name + "\n"
                message = message + "   Адрес: " + address + "\n"
                if password:
                    message = message + "   Пароль: " + password + "\n"
                message = message + "   " + instructions + "\n\n"

            notification.answer(message)
            return

        # Обработка геолокации
        if message_data.get('typeMessage') == 'locationMessage':
            location_data = message_data.get('locationMessageData', {})
            user_lat = location_data.get('latitude')
            user_lon = location_data.get('longitude')

            print("Получена геолокация: " + str(user_lat) + ", " + str(user_lon))

            if user_lat and user_lon:
                nearest_spots = find_nearest_spots(user_lat, user_lon)

                if nearest_spots:
                    text_message = format_spots_message(nearest_spots)
                    nearest = nearest_spots[0]
                    notification.answer(
                        text_message,
                        latitude=nearest[3],
                        longitude=nearest[4]
                    )
                else:
                    notification.answer("К сожалению, рядом нет сохранённых Wi-Fi точек.")
            else:
                notification.answer("Не удалось определить ваше местоположение. Попробуйте ещё раз.")
            return

        # Ответ на непонятное сообщение
        if message_text and not message_lower.startswith('/'):
            notification.answer(
                "Я вас не понял. Отправьте команду /start, чтобы начать работу, "
                "или просто отправьте ваше местоположение."
            )
            return

    except Exception as e:
        print("Ошибка: " + str(e))
        try:
            notification.answer("Произошла ошибка. Попробуйте позже.")
        except:
            pass


# ========== ЗАПУСК ==========
print("=" * 40)
print("Wi-Fi бот для MAX запущен")
print("Инстанс: " + ID_INSTANCE)
print("Точек в базе: " + str(cursor.execute('SELECT COUNT(*) FROM wifi_spots').fetchone()[0]))
print("=" * 40)
print("Бот отправляет кнопки и ищет Wi-Fi по геолокации")
print("=" * 40)

bot.run_forever()