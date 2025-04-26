import math
import sqlite3
import logging
import aiohttp
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TELEGRAM_BOT_TOKEN = "6574624892:AAH_HZQI_gDks_JjwCDpxMyZe8SNfK8kqyg"
YANDEX_API_KEY = ''
DB_PATH = "maps.db"

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
    con.commit()
    con.close()

def get_ll_spn(toponym):
    coordinates_str = toponym['Point']['pos']
    long, lat = map(float, coordinates_str.split())
    return f'{long},{lat}', '0.01,0.01'

def get_distance(p1, p2):
    radius = 6373.0
    lon1, lat1 = map(math.radians, p1)
    lon2, lat2 = map(math.radians, p2)

    d_lon = lon2 - lon1
    d_lat = lat2 - lat1

    a = math.sin(d_lat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(d_lon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    distance = radius * c
    return distance

async def get_response(url, params):
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            return await resp.json()

def build_menu():
    keyboard = [
        [KeyboardButton(text="Отправить локацию", request_location=True)],
        [KeyboardButton(text="Найти кафе поблизости")],
        [KeyboardButton(text="Найти аптеку поблизости")],
        [KeyboardButton(text="Показать карту вокруг меня")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Отправьте свою локацию или выберите действие:",
        reply_markup=build_menu()
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Я помогу вам найти места рядом! Просто отправьте местоположение или запрос.")

async def location_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.location:
        user_id = update.message.from_user.id
        user_locations[user_id] = (
            update.message.location.longitude,
            update.message.location.latitude
        )
        await update.message.reply_text(
            "Локация сохранена! Теперь выберите действие или напишите, что искать.",
            reply_markup=build_menu()
        )

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return

    user_id = update.message.from_user.id
    user_location = user_locations.get(user_id)

    user_text = update.message.text.strip().lower()

    if user_text == "найти кафе поблизости":
        query = "кафе"
    elif user_text == "найти аптеку поблизости":
        query = "аптека"
    elif user_text == "показать карту вокруг меня":
        if not user_location:
            await update.message.reply_text("Сначала отправьте свою локацию!")
            return

        ll = f"{user_location[0]},{user_location[1]}"
        static_map_url = f"https://static-maps.yandex.ru/1.x/?ll={ll}&spn=0.01,0.01&l=map&key={YANDEX_API_KEY}"
        await update.message.reply_photo(photo=static_map_url, caption="Вот карта вокруг вас.")
        return
    else:
        query = user_text

    if not user_location:
        await update.message.reply_text("Сначала отправьте свою локацию!")
        return

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # Проверка, есть ли уже такой запрос
    existing = cur.execute("SELECT * FROM maps WHERE request = ?", (query,)).fetchone()

    if existing:
        ll, spn, pt, company, address, distance = existing[1], existing[2], existing[3], existing[4], existing[5], \
        existing[6]
        static_map_url = f"https://static-maps.yandex.ru/1.x/?ll={ll}&spn={spn}&l=map&pt={pt},pm2rdm&key={YANDEX_API_KEY}"

        await update.message.reply_photo(
            photo=static_map_url,
            caption=f'''Вы уже искали:\n<b>{company}</b>\n{address}\nРасстояние: {str(round(float(distance) * 1000, 1))} м.''',
            parse_mode='HTML'
        )
        con.close()
        return

    try:
        # Новый запрос
        url = "https://geocode-maps.yandex.ru/1.x/"
        params = {
            "geocode": query,
            "format": "json",
            "apikey": YANDEX_API_KEY
        }
        response = await get_response(url, params)
        features = response.get('response', {}).get('GeoObjectCollection', {}).get('featureMember', [])

        if not features:
            await update.message.reply_text("Ничего не найдено.")
            con.close()
            return

        toponym = features[0]['GeoObject']
        ll, spn = get_ll_spn(toponym)
        org_name = toponym['name']
        org_address = toponym['description']
        org_location = list(map(float, ll.split(',')))

        distance = get_distance(user_location, org_location)

        pt = ll
        static_map_url = f"https://static-maps.yandex.ru/1.x/?ll={ll}&spn={spn}&l=map&pt={pt},pm2rdm&key={YANDEX_API_KEY}"

        open_link = f"https://yandex.ru/maps/?ll={ll}&z=16"
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Открыть в Яндекс.Картах", url=open_link)]]
        )

        caption = (
            f"<b>{org_name}</b>\n"
            f"{org_address}\n"
            f"Расстояние: <b>{round(float(distance) * 1000, 1)} м</b>."
        )

        await update.message.reply_photo(
            photo=static_map_url,
            caption=caption,
            parse_mode='HTML',
            reply_markup=keyboard
        )

        # Сохраняем в базу
        cur.execute('''
                INSERT INTO maps (request, ll, spn, pt, company, address, distance)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (query, ll, spn, pt, org_name, org_address, str(distance)))
        con.commit()

    except Exception as e:
        logger.exception("Ошибка при поиске:")
        await update.message.reply_text("Произошла ошибка при поиске. Попробуйте снова.")
    finally:
        con.close()



def main():
    init_db()
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.LOCATION, location_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    application.run_polling()


if __name__ == "__main__":
    main()