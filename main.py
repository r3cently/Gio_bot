import math
import sqlite3
import logging
import aiohttp
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TELEGRAM_BOT_TOKEN = "6574624892:AAH_HZQI_gDks_JjwCDpxMyZe8SNfK8kqyg"
YANDEX_API_KEY = "dda3ddba-c9ea-4ead-9010-f43fbc15c6e3"
YANDEX_API_KEY_STATIC = "f3a0fe3a-b07e-4840-a1da-06f18b2ddf13"
DB_PATH = "maps.db"
user_nearby_places = {}
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)
user_locations = {}


def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS maps (
            request TEXT PRIMARY KEY,
            ll TEXT,
            spn TEXT,
            pt TEXT,
            company TEXT,
            address TEXT,
            distance TEXT
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS history (
            user_id INTEGER,
            company TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    con.commit()
    con.close()


def get_distance(p1, p2):
    radius = 6371
    lat1, lon1 = map(math.radians, p1[::-1])
    lat2, lon2 = map(math.radians, p2[::-1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius * c


async def get_response(url, params):
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            return await resp.json()


def build_menu():
    keyboard = [
        [KeyboardButton(text="Отправить локацию", request_location=True)],
        [KeyboardButton(text="Показать карту вокруг меня")],
        [KeyboardButton(text="Найти кафе поблизости")],
        [KeyboardButton(text="Найти аптеку поблизости")],
        [KeyboardButton(text="Найти супермаркет поблизости")],
        [KeyboardButton(text="Показать историю")],
        [KeyboardButton(text="Очистить историю")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Отправь локацию или выбери запрос, также можно написать название организации. Если есть вопросы напиши /help",
        reply_markup=build_menu())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отправь свою локацию, а затем выбери, что найти.")


async def location_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_locations[user_id] = (
        update.message.location.longitude,
        update.message.location.latitude
    )
    await update.message.reply_text("Локация получена. Теперь выбери, что искать.", reply_markup=build_menu())


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_location = user_locations.get(user_id)
    text = update.message.text.strip().lower()
    if text == 'очистить историю':
        try:
            con = sqlite3.connect(DB_PATH)
            cur = con.cursor()
            cur.execute('DELETE FROM history WHERE user_id = ?', (user_id,))
            con.commit()
            con.close()
            await update.message.reply_text("История очищена.", reply_markup=build_menu())
        except Exception as e:
            logger.exception('Ошибка при очистке истории:')
            await update.message.reply_text('Ошибка при очистке итсории.')
        return
    if text == "показать историю":
        try:
            con = sqlite3.connect(DB_PATH)
            cur = con.cursor()
            cur.execute('''
                SELECT company, timestamp FROM history
                WHERE user_id = ?
                ORDER BY timestamp DESC
                LIMIT 10
            ''', (user_id,))
            rows = cur.fetchall()
            con.close()

            if not rows:
                await update.message.reply_text("История пуста.")
                return

            message = "<b>Последние запросы:</b>\n"
            for name, ts in rows:
                message += f"• {name} — {ts}\n"

            await update.message.reply_text(message, parse_mode="HTML")
        except Exception as e:
            logger.exception("Ошибка при показе истории:")
            await update.message.reply_text("Ошибка при загрузке истории.")
        return

    if not user_location:
        await update.message.reply_text("Сначала отправь свою локацию.")
        return

    if text == "показать карту вокруг меня":
        ll = f"{user_location[0]},{user_location[1]}"
        map_url = f"https://static-maps.yandex.ru/1.x/?ll={ll}&spn=0.01,0.01&l=map&key={YANDEX_API_KEY_STATIC}"
        await update.message.reply_photo(photo=map_url, caption="Карта вокруг тебя.")
        return

    places = user_nearby_places.get(user_id)
    if places:
        for dist, feature in places:
            org_name = feature["properties"]["CompanyMetaData"].get("name", "")
            if text == org_name.lower():
                meta = feature["properties"]["CompanyMetaData"]
                org_address = meta.get("address", "Без адреса")
                org_description = meta.get("Categories", [])
                org_description_text = ", ".join(
                    [cat.get("name") for cat in org_description]) if org_description else "Без описания"
                rating = meta.get('rating')
                rating_text = f"Рейтинг: {rating}★" if rating else "Рейтинг не указан"
                phone = meta.get("Phones", [])
                phone_text = phone[0].get("formatted") if phone else "Нет номера"
                hours = meta.get("Hours", {}).get("text", "Часы работы не указаны")
                website = meta.get("url", "Нет сайта")

                coords = feature["geometry"]["coordinates"]
                ll = f"{coords[0]},{coords[1]}"
                user_pt = f"{user_location[0]},{user_location[1]}"
                dest_pt = f"{coords[0]},{coords[1]}"
                pt = f"{user_pt},pm2blm~{dest_pt},pm2rdm"
                center_ll = f"{(user_location[0] + coords[0]) / 2},{(user_location[1] + coords[1]) / 2}"
                spn = "0.005,0.005" if dist < 0.5 else "0.09,0.09"

                static_map_url = f"https://static-maps.yandex.ru/1.x/?ll={center_ll}&spn={spn}&l=map&pt={pt}&key={YANDEX_API_KEY_STATIC}"

                caption = (
                    f"<b>{org_name}</b>\n"
                    f"{org_address}\n"
                    f"{org_description_text}\n"
                    f"{rating_text}\n"
                    f"Телефон: {phone_text}\n"
                    f"Время работы: {hours}\n"
                    f"Сайт: {website}\n"
                    f"Расстояние: <b>{round(dist * 1000, 1)} м</b>"
                )

                await update.message.reply_photo(photo=static_map_url, caption=caption, parse_mode="HTML")

                con = sqlite3.connect(DB_PATH)
                cur = con.cursor()
                cur.execute('INSERT INTO history (user_id, company) VALUES (?, ?)', (user_id, org_name))
                con.commit()
                con.close()

                user_nearby_places[user_id] = []

                await update.message.reply_text("Выбери следующее действие:", reply_markup=build_menu())
                return

    query_map = {"найти кафе поблизости": "кафе",
                 "найти аптеку поблизости": "аптека",
                 "найти супермаркет поблизости": "супермаркет"
                 }

    query = query_map.get(text, text)

    try:
        url = "https://search-maps.yandex.ru/v1/"
        params = {
            "text": query,
            "ll": f"{user_location[0]},{user_location[1]}",
            "type": "biz",
            "results": 10,
            "lang": "ru_RU",
            "apikey": YANDEX_API_KEY
        }

        response = await get_response(url, params)
        features = response.get("features", [])
        if not features:
            await update.message.reply_text("Ничего не найдено.")
            return

        places_with_distance = []
        for feature in features:
            coords = feature["geometry"]["coordinates"]
            dist = get_distance(user_location, coords)
            places_with_distance.append((dist, feature))

        places_with_distance.sort(key=lambda x: x[0])
        top_three = places_with_distance[:3]

        if not top_three:
            await update.message.reply_text("Не удалось определить ближайшие места.")
            return

        user_nearby_places[user_id] = top_three

        buttons = [[place[1]["properties"]["CompanyMetaData"]["name"]] for place in top_three]
        markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
        await update.message.reply_text(
            "Выбери организацию, чтобы получить подробную информацию:",
            reply_markup=markup
        )

    except Exception as e:
        logger.exception("Ошибка при поиске:")
        await update.message.reply_text("Произошла ошибка. Попробуйте позже.")


def main():
    init_db()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.LOCATION, location_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.run_polling()


if __name__ == "__main__":
    main()
