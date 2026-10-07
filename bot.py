"""Telegram ob-havo boti: manzil saqlash, kunlik/haftalik prognoz, AI tahlili."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Any

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from weather import WeatherService, WeatherError
from db import Database, DatabaseError
from ai import GeminiService, GeminiError

logger = logging.getLogger(__name__)

MAIN_KEYBOARD = [
    ["📍 Manzilni saqlash", "📍 Manzilni o'chirish"],
    ["📅 7 kunlik prognoz", "🔄 Yangilash"],
    ["⚙️ Sozlamalar", "❌ Dasturdan chiqish"],
]
CONFIRM_KEYBOARD = [["✅ Tasdiqlash", "❌ Bekor qilish"]]
LOCATION_KEYBOARD = [["📍 Joylashmani aniqlash", "✍️ Manzilni yozish"]]
SETTINGS_KEYBOARD = [
    ["⏰ Kundalik xabar: 07:00", "🔕 Kundalik xabarni o'chirish"],
    ["⬅️ Orqaga"],
]

UNKNOWN = "Noma lum"
NO_LOCATION_MESSAGE = (
    "Manzil hali saqlanmagan. Iltimos, Manzilni saqlash tugmasini bosing."
)
ERROR_MESSAGE = "Xatolik yuz berdi. Iltimos, keyinroq qayta urinib koring."


def log_error(exc: Exception, context: str) -> None:
    logger.error("Xatolik: %s | %s: %s", context, type(exc).__name__, exc)


async def safe_reply(update: Update, text: str) -> None:
    """Xavfsiz javob yuborish."""
    if update.message:
        await update.message.reply_text(text)


# ----------------------------------------------------------------------
# Ob-havo xabari
# ----------------------------------------------------------------------
async def send_weather_message(
    context: ContextTypes.DEFAULT_TYPE,
    telegram_id: int,
    current: dict[str, Any],
    daily: dict[str, Any],
    analysis: dict[str, Any],
) -> None:
    ws = WeatherService()
    lines = ["Bugungi ob-havo:"]
    lines.append("Vaqt: " + str(current.get("time") or UNKNOWN))
    lines.append("Harorat: " + str(current.get("temperature")) + " C")
    lines.append("Namlik: " + str(current.get("humidity")) + " %")
    wind = str(current.get("wind_speed")) + " km/s, "
    wind += ws.wind_direction_to_text(current.get("wind_direction"))
    lines.append("Shamol: " + wind)
    lines.append("Ob-havo: " + ws.weather_code_to_text(current.get("weather_code")))

    lines.append("")
    lines.append("7 kunlik prognoz:")
    dates = daily.get("dates", [])
    for i, date in enumerate(dates[:7]):
        max_t = daily.get("max_temp", [])[i] if i < len(daily.get("max_temp", [])) else UNKNOWN
        min_t = daily.get("min_temp", [])[i] if i < len(daily.get("min_temp", [])) else UNKNOWN
        precip = daily.get("precip_prob", [])[i] if i < len(daily.get("precip_prob", [])) else UNKNOWN
        code = daily.get("weather_code", [])[i] if i < len(daily.get("weather_code", [])) else None
        lines.append(
            f"{date}: {max_t} / {min_t} C, yomgir {precip}%, "
            + ws.weather_code_to_text(code)
        )

    lines.append("")
    lines.append("AI tahlili:")
    lines.append(analysis.get("analysis", "Tahlil mavjud emas."))

    await context.bot.send_message(chat_id=telegram_id, text="\n".join(lines))


async def build_weather(
    db: Database,
    telegram_id: int,
    weather_service: WeatherService,
    gemini_service: GeminiService,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    location = db.get_location(telegram_id)
    if not location or not location.get("is_confirmed"):
        raise WeatherError(NO_LOCATION_MESSAGE)
    lat = location["latitude"]
    lon = location["longitude"]
    current = await weather_service.get_current(lat, lon)
    daily = await weather_service.get_daily_forecast(lat, lon, 7)
    analysis = gemini_service.analyze(current, daily)
    return current, daily, analysis


async def send_weather_now(
    context: ContextTypes.DEFAULT_TYPE,
    db: Database,
    weather_service: WeatherService,
    gemini_service: GeminiService,
    telegram_id: int,
) -> None:
    uid = telegram_id
    try:
        current, daily, analysis = await build_weather(db, uid, weather_service, gemini_service)
        await send_weather_message(context, uid, current, daily, analysis)
    except WeatherError as exc:
        await context.bot.send_message(chat_id=uid, text=str(exc))
    except Exception as exc:
        log_error(exc, "send_weather_now")
        await context.bot.send_message(chat_id=uid, text=ERROR_MESSAGE)


async def send_scheduled_weather(
    context: ContextTypes.DEFAULT_TYPE,
    db: Database,
    weather_service: WeatherService,
    gemini_service: GeminiService,
    kind: str,
) -> None:
    """Takrorlanadigan xabar: daily yoki hourly."""
    uid = context.job.data.get("telegram_id")
    if uid is None:
        return
    settings = db.get_settings(uid)
    if not settings:
        return
    field = "last_daily_sent_at" if kind == "daily" else "last_hourly_sent_at"
    last_sent = settings.get(field)
    if last_sent is not None and isinstance(last_sent, datetime):
        if last_sent.tzinfo is None:
            last_sent = last_sent.replace(tzinfo=timezone.utc)
        interval = settings.get("interval_minutes", 1440)
        if datetime.now(timezone.utc) - last_sent < timedelta(minutes=interval):
            return
    try:
        current, daily, analysis = await build_weather(
            db=db,
            telegram_id=uid,
            weather_service=weather_service,
            gemini_service=gemini_service,
        )
        await send_weather_message(context, uid, current, daily, analysis)
        if kind == "daily":
            db.set_last_daily_sent(uid, datetime.now(timezone.utc))
        else:
            db.set_last_hourly_sent(uid, datetime.now(timezone.utc))
    except WeatherError:
        return
    except Exception as exc:
        log_error(exc, "send_scheduled_weather")


# ----------------------------------------------------------------------
# Foydalanuvchi holati (manzil kiritish oqimi)
# ----------------------------------------------------------------------
# user_id -> {"phase": "location_text"|"confirm", "pending": {...}}
USER_STATE: dict[int, dict[str, Any]] = {}


# ----------------------------------------------------------------------
# Start / Menyu
# ----------------------------------------------------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_chat.id
    db: Database = context.application.bot_data["db"]
    if db.get_user(uid) is None:
        db.create_user(
            telegram_id=uid,
            first_name=update.effective_user.first_name or "",
            username=update.effective_user.username,
        )
    if db.get_settings(uid) is None:
        db.create_settings(uid)
    await update.message.reply_text(
        "Salom! Ob-havo botiga xush kelibsiz.\n"
        "Manzilingizni saqlasangiz, har kuni kunlik ob-havo xabarini "
        "yuborib boramiz.",
        reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Buyruqlar:\n"
        "/start - bosh menyu\n"
        "/weather - hozirgi ob-havo\n"
        "/forecast - 7 kunlik prognoz\n"
        "/settings - sozlamalar\n"
        "/setlocation - manzilni o'zgartirish\n"
        "/stop - kunlik xabarni o'chirish"
    )


async def send_main_menu(update: Update, text: str) -> None:
    await update.message.reply_text(
        text, reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
    )


# ----------------------------------------------------------------------
# Manzil oqimi
# ----------------------------------------------------------------------
async def start_location_flow(update: Update) -> None:
    uid = update.effective_chat.id
    USER_STATE[uid] = {"phase": "location_text"}
    await update.message.reply_text(
        "Yashash manzilingizni yozing.\n"
        "Misol: Toshkent viloyati, Ohangaron tumani, Bozsuv qishlog'i\n"
        "Yoki pastdagi tugma orqali joylashmani yuboring.",
        reply_markup=ReplyKeyboardMarkup(LOCATION_KEYBOARD, resize_keyboard=True),
    )


async def handle_location_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
) -> bool:
    uid = update.effective_chat.id
    ws: WeatherService = context.application.bot_data["weather"]
    try:
        geocode = await ws.geocode(text)
    except WeatherError as exc:
        await safe_reply(update, str(exc))
        return True

    USER_STATE[uid] = {
        "phase": "confirm",
        "pending": {
            "name": text,
            "address": geocode["display_name"],
            "latitude": geocode["latitude"],
            "longitude": geocode["longitude"],
        },
    }
    await update.message.reply_text(
        "Topilgan manzil:\n" + geocode["display_name"] + "\n\nTasdiqlaysizmi?",
        reply_markup=ReplyKeyboardMarkup(CONFIRM_KEYBOARD, resize_keyboard=True),
    )
    return True


async def handle_location_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    uid = update.effective_chat.id
    loc = update.message.location
    if loc is None:
        return
    USER_STATE[uid] = {
        "phase": "confirm",
        "pending": {
            "name": "Joylashuv (GPS)",
            "address": f"GPS: {loc.latitude}, {loc.longitude}",
            "latitude": loc.latitude,
            "longitude": loc.longitude,
        },
    }
    await update.message.reply_text(
        "Joylashuv qabul qilindi. Tasdiqlaysizmi?",
        reply_markup=ReplyKeyboardMarkup(CONFIRM_KEYBOARD, resize_keyboard=True),
    )


async def confirm_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_chat.id
    state = USER_STATE.get(uid, {})
    pending = state.get("pending")
    if state.get("phase") != "confirm" or not pending:
        await send_main_menu(update, "Avval manzilni kiriting.")
        return

    db: Database = context.application.bot_data["db"]
    db.create_location(
        telegram_id=uid,
        name=pending["name"],
        latitude=pending["latitude"],
        longitude=pending["longitude"],
        address=pending["address"],
        is_confirmed=True,
    )
    db.update_settings(uid)
    USER_STATE.pop(uid, None)
    await send_main_menu(update, "Manzil tasdiqlandi: " + pending["address"])
    await send_weather_now(
        context=context,
        db=db,
        weather_service=context.application.bot_data["weather"],
        gemini_service=context.application.bot_data["gemini"],
        telegram_id=uid,
    )


async def cancel_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_chat.id
    USER_STATE.pop(uid, None)
    await send_main_menu(update, "Bekor qilindi.")


async def delete_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_chat.id
    db: Database = context.application.bot_data["db"]
    db.delete_location(uid)
    await send_main_menu(update, "Manzil o'chirildi. Yangi manzil kiriting.")


# ----------------------------------------------------------------------
# Sozlamalar
# ----------------------------------------------------------------------
async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_chat.id
    db: Database = context.application.bot_data["db"]
    settings = db.get_settings(uid) or {}
    location = db.get_location(uid)
    status = "yoqilgan" if settings.get("interval_minutes", 1440) > 0 else "o'chirilgan"
    addr = location.get("address") if location else "kiritilmagan"
    text = (
        "Sozlamalar:\n"
        "Manzil: " + str(addr) + "\n"
        "Kundalik xabar: " + status + " (07:00 Toshkent vaqti)"
    )
    await update.message.reply_text(
        text, reply_markup=ReplyKeyboardMarkup(SETTINGS_KEYBOARD, resize_keyboard=True)
    )


async def enable_daily(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_chat.id
    db: Database = context.application.bot_data["db"]
    db.update_settings(uid, interval_minutes=1440, hourly_hour=7, daily_hour=7)
    schedule_daily_job(context.application, uid)
    await show_settings(update, context)


async def disable_daily(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_chat.id
    db: Database = context.application.bot_data["db"]
    db.update_settings(uid, interval_minutes=0)
    remove_daily_job(context.application, uid)
    await update.message.reply_text(
        "Kundalik xabar o'chirildi.",
        reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
    )


def schedule_daily_job(application: Application, uid: int) -> None:
    """Foydalanuvchi uchun kunlik ishni qayta jadvalga qo'yadi."""
    jq = application.job_queue
    if jq is None:
        return
    name = f"daily_{uid}"
    for job in jq.get_jobs_by_name(name):
        job.schedule_removal()
    # PTB run_daily doim UTC bo'yicha ishlaydi: Toshkent 07:00 = UTC 02:00
    jq.run_daily(
        daily_weather_job,
        time=datetime.strptime("02:00", "%H:%M").time(),
        data={"telegram_id": uid},
        name=name,
    )


def remove_daily_job(application: Application, uid: int) -> None:
    jq = application.job_queue
    if jq is None:
        return
    for job in jq.get_jobs_by_name(f"daily_{uid}"):
        job.schedule_removal()


async def daily_weather_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Kunlik xabar ishi (job queue tomonidan chaqiriladi)."""
    await send_scheduled_weather(
        context=context,
        db=context.application.bot_data["db"],
        weather_service=context.application.bot_data["weather"],
        gemini_service=context.application.bot_data["gemini"],
        kind="daily",
    )


# ----------------------------------------------------------------------
# Buyruqlar
# ----------------------------------------------------------------------
async def cmd_weather(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_weather_now(
        context=context,
        db=context.application.bot_data["db"],
        weather_service=context.application.bot_data["weather"],
        gemini_service=context.application.bot_data["gemini"],
        telegram_id=update.effective_chat.id,
    )


async def cmd_forecast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_weather(update, context)


async def cmd_setlocation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start_location_flow(update)


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_settings(update, context)


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await disable_daily(update, context)


async def cmd_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Noma'lum buyruq. /help ni bosing.")


# ----------------------------------------------------------------------
# Umumiy xabar handleri (menyu tugmalari)
# ----------------------------------------------------------------------
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_chat.id
    text = (update.message.text or "").strip()
    phase = USER_STATE.get(uid, {}).get("phase")

    if phase == "location_text":
        if text in ("📍 Joylashmani aniqlash", "✍️ Manzilni yozish"):
            await update.message.reply_text("Manzilni matn ko'rinishida yozing.")
            return
        await handle_location_text(update, context, text)
        return

    if phase == "confirm":
        if text == "✅ Tasdiqlash":
            await confirm_location(update, context)
            return
        if text == "❌ Bekor qilish":
            await cancel_location(update, context)
            return

    handlers = {
        "📍 Manzilni saqlash": start_location_flow,
        "📍 Manzilni o'chirish": delete_location,
        "📅 7 kunlik prognoz": cmd_forecast,
        "🔄 Yangilash": cmd_weather,
        "⚙️ Sozlamalar": show_settings,
        "⏰ Kundalik xabar: 07:00": enable_daily,
        "🔕 Kundalik xabarni o'chirish": disable_daily,
        "⬅️ Orqaga": lambda u, c: send_main_menu(u, "Bosh menyu."),
    }
    handler = handlers.get(text)
    if handler is not None:
        await handler(update, context)
        return

    await send_main_menu(update, "Noma'lum tugma. Bosh menyu.")


async def on_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_chat.id
    phase = USER_STATE.get(uid, {}).get("phase")
    if phase in ("location_text", "confirm", None):
        await handle_location_message(update, context)


# ----------------------------------------------------------------------
# Ishga tushirish
# ----------------------------------------------------------------------
def build_application(token: str, db: Database) -> Application:
    """Ilova va handlerlarni yaratadi."""
    app = Application.builder().token(token).build()
    app.bot_data["db"] = db
    app.bot_data["weather"] = WeatherService()
    app.bot_data["gemini"] = GeminiService()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("weather", cmd_weather))
    app.add_handler(CommandHandler("forecast", cmd_forecast))
    app.add_handler(CommandHandler("setlocation", cmd_setlocation))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("location", cmd_setlocation))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(filters.LOCATION, on_location))
    return app


async def reschedule_existing_users(app: Application) -> None:
    """Bazadagi barcha foydalanuvchilar uchun kunlik ishni tiklaydi."""
    db: Database = app.bot_data["db"]
    try:
        users = db.db["settings"].find(
            {"interval_minutes": {"$gt": 0}}, {"telegram_id": 1}
        )
        for doc in users:
            schedule_daily_job(app, doc["telegram_id"])
    except Exception as exc:
        log_error(exc, "reschedule_existing_users")


async def start_port_server(app: Application) -> None:
    """Railway kabi platformalar uchun PORT da kichik HTTP server."""
    import os

    port = os.getenv("PORT", "").strip()
    if not port:
        return

    async def handle_client(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            await reader.read(1024)
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: text/plain\r\n"
                b"Content-Length: 19\r\n"
                b"Connection: close\r\n"
                b"\r\n"
                b"UzWeatherBot: OK\n"
            )
            await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()

    try:
        server = await asyncio.start_server(
            handle_client, host="0.0.0.0", port=int(port)
        )
        app.bot_data["port_server"] = server
        logger.info("PORT server ishga tushdi: %s", port)
    except Exception as exc:
        log_error(exc, "start_port_server")


async def on_startup(app: Application) -> None:
    """Ilova boshlanganda chaqiriladi."""
    await reschedule_existing_users(app)
    await start_port_server(app)
    logger.info("Bot ishga tushdi. Kunlik xabarlar jadvalga qayta tiklandi.")


def main() -> None:
    """Botni ishga tushiradi."""
    import os
    import sys

    from dotenv import load_dotenv

    load_dotenv()

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    mongo_uri = os.getenv("MONGODB_URI", "").strip()
    if not token:
        sys.exit("TELEGRAM_BOT_TOKEN kiritilmagan (.env faylini tekshiring).")
    if not mongo_uri:
        sys.exit("MONGODB_URI kiritilmagan (.env faylini tekshiring).")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    db = Database(uri=mongo_uri, database=os.getenv("MONGODB_DATABASE", "uz_weather_bot"))
    try:
        db.connect()
    except DatabaseError as exc:
        sys.exit(str(exc))

    app = build_application(token, db)
    app.post_init = on_startup

    try:
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    finally:
        db.close()


if __name__ == "__main__":
    main()
