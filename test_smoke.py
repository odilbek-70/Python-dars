"""Oddiy tekshiruvlar: ob-havo API, geokodlash, baza, bot ilovasi."""

from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv

# Windows konsolida o'zbekcha/emoji matn uchun UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

from weather import WeatherService, WeatherError
from db import Database, DatabaseError
from ai import GeminiService


async def test_weather() -> None:
    ws = WeatherService()
    geo = await ws.geocode("Toshkent, O'zbekiston")
    print("GEOCODE OK:", geo["display_name"][:60], geo["latitude"], geo["longitude"])

    current = await ws.get_current(geo["latitude"], geo["longitude"])
    print("CURRENT OK:", current["temperature"], "C,", ws.weather_code_to_text(current["weather_code"]))

    daily = await ws.get_daily_forecast(geo["latitude"], geo["longitude"], 7)
    print("DAILY OK:", len(daily["dates"]), "kun, max[0]=", daily["max_temp"][0])

    ai = GeminiService()
    analysis = ai.analyze(current, daily)
    print("AI OK, manba:", analysis["source"])
    print("AI matn:", analysis["analysis"][:100])


def test_db() -> None:
    uri = os.getenv("MONGODB_URI", "").strip()
    if not uri:
        print("DB SKIP: MONGODB_URI yo'q")
        return
    db = Database(uri=uri, database="uz_weather_bot_smoke")
    try:
        db.connect()
        db.create_user(999999999, "Smoke", "smoke_test")
        db.create_settings(999999999)
        user = db.get_user(999999999)
        assert user is not None
        db.db["users"].delete_many({"telegram_id": 999999999})
        db.db["settings"].delete_many({"telegram_id": 999999999})
        print("DB OK: ulanish, yozish, o'qish, o'chirish")
    except DatabaseError as exc:
        print("DB ERROR:", exc)
    finally:
        db.close()


def test_app_build() -> None:
    from telegram.ext import Application
    import bot

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip() or (
        "123456789:AA" + "B" * 30
    )
    app = bot.build_application(token, Database(uri="mongodb://localhost:27017"))
    assert isinstance(app, Application)
    assert app.job_queue is not None
    bot.schedule_daily_job(app, 12345)
    jobs = app.job_queue.get_jobs_by_name("daily_12345")
    assert jobs, "Kunlik ish jadvalga tushmadi"
    bot.remove_daily_job(app, 12345)
    print("APP OK: handlerlar va kunlik jadval ishlaydi")


def main() -> int:
    failed = False
    try:
        test_app_build()
    except Exception as exc:
        failed = True
        print("APP FAIL:", type(exc).__name__, exc)

    try:
        test_db()
    except Exception as exc:
        failed = True
        print("DB FAIL:", type(exc).__name__, exc)

    try:
        asyncio.run(test_weather())
    except WeatherError as exc:
        failed = True
        print("WEATHER FAIL:", exc)
    except Exception as exc:
        failed = True
        print("WEATHER FAIL:", type(exc).__name__, exc)

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())