import sqlite3
import re
import math

DB_PATH = 'wifi_points.db'
CSV_PATH = 'wifi.csv'   # укажи своё имя файла

# Подключение к базе
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# Очищаем таблицу перед импортом
cursor.execute('DELETE FROM wifi_spots')
conn.commit()

def parse_wkt_point(wkt_string):
    """
    Извлекает (lon, lat) из строк типа:
    POINT (30.094172 59.562446)
    MULTIPOINT ((30.096713 59.561035))
    и подобных.
    Возвращает (lat, lon) или (None, None)
    """
    # Ищем первое вхождение двух чисел с плавающей точкой, разделённых пробелом
    match = re.search(r'([\d\.]+)\s+([\d\.]+)', wkt_string)
    if match:
        lon = float(match.group(1))
        lat = float(match.group(2))
        # Проверяем реалистичность (долгота в России 20-200, широта 40-80)
        if 20 <= lon <= 200 and 40 <= lat <= 80:
            return lat, lon
    return None, None

rows_added = 0
skipped = 0

with open(CSV_PATH, 'r', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue

        # Разделяем по точке с запятой
        parts = [p.strip().strip('"') for p in line.split(';')]

        if len(parts) < 4:
            print(f'⚠️  Пропущена строка (мало колонок): {line[:100]}...')
            skipped += 1
            continue

        wkt = parts[0]
        lat, lon = parse_wkt_point(wkt)
        if lat is None or lon is None:
            print(f'⚠️  Пропущена строка (не удалось извлечь координаты): {line[:100]}...')
            skipped += 1
            continue

        # Собираем остальные поля (их может быть разное количество)
        name = parts[1] if len(parts) > 1 else ''
        # Адрес может быть разбит на несколько колонок, объединяем всё, что между названием и провайдером
        # Провайдер обычно содержит "ООО", поэтому ищем его
        provider = ''
        address_parts = []
        instructions = ''
        category = ''
        extra = ''

        # Ищем провайдера (содержит "ООО" или "Мбит/с")
        provider_idx = -1
        for i in range(2, len(parts)):
            if 'ООО' in parts[i] or 'Мбит/с' in parts[i]:
                provider_idx = i
                break

        if provider_idx != -1:
            # Всё, что между name и provider_idx - адрес
            address_parts = parts[2:provider_idx]
            provider = parts[provider_idx]
            # После провайдера обычно идёт скорость (может отсутствовать)
            if provider_idx + 1 < len(parts) and 'Мбит/с' in parts[provider_idx + 1]:
                provider += ' ' + parts[provider_idx + 1]
                rest_start = provider_idx + 2
            else:
                rest_start = provider_idx + 1

            # Остаток: инструкция, категория, доп. поле
            rest = parts[rest_start:]
            if rest:
                instructions = rest[0] if len(rest) > 0 else ''
                category = rest[1] if len(rest) > 1 else ''
                extra = rest[2] if len(rest) > 2 else ''
        else:
            # Нет провайдера – просто заполняем что можем
            address_parts = parts[2:] if len(parts) > 2 else []

        address = ', '.join(address_parts).strip().strip('"')

        # Формируем итоговую инструкцию, объединяя provider, instructions, category
        full_instructions = f"{provider}. {instructions} ({category})".strip()
        if extra:
            full_instructions += f", доп: {extra}"

        # Вставляем в базу
        try:
            cursor.execute(
                'INSERT INTO wifi_spots (name, address, latitude, longitude, password, instructions) '
                'VALUES (?, ?, ?, ?, ?, ?)',
                (name, address, lat, lon, '', full_instructions)
            )
            rows_added += 1
        except Exception as e:
            print(f'⚠️  Ошибка вставки строки: {line[:100]}... ({e})')
            skipped += 1

conn.commit()
conn.close()

print(f'\n✅ Импорт завершён.')
print(f'   Добавлено точек: {rows_added}')
print(f'   Пропущено строк: {skipped}')