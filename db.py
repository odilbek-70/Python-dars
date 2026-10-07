"""MongoDB bilan ishlash (foydalanuvchi, manzil va xabar sozlamalari)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import PyMongoError

load_dotenv()

logger = logging.getLogger(__name__)

MONGO_DB = "uz_weather_bot"

# MongoDB'da foydalanuvchi, manzil va sozlamalar uchun koleksiyalar
COLLECTIONS = {
    "users": "users",
    "locations": "locations",
    "settings": "settings",
}


class DatabaseError(Exception):
    """MongoDB bilan ishlashda xatolik."""


class Database:
    """MongoDB ulanishini boshqaradi."""

    def __init__(self, uri: str, database: str = MONGO_DB) -> None:
        self._uri = uri
        self._database = database
        self._client: MongoClient | None = None
        self._db: Any = None

    def connect(self) -> None:
        """MongoDB ga ulanadi (sinxron)."""
        try:
            self._client = MongoClient(self._uri, serverSelectionTimeoutMS=5000)
            self._db = self._client[self._database]
            # Uzun muddat ishlamaslik holatini tekshiramiz
            self._client.admin.command("ping")
            logger.info("MongoDB ulanish muvaffaqiyatli.")
        except PyMongoError as exc:
            logger.error("MongoDB ulanishda xatolik: %s", exc)
            raise DatabaseError("MongoDB ulanishi muvaffaqiyatsiz bo'ldi.") from exc

    def close(self) -> None:
        """MongoDB ulanishini yopadi."""
        if self._client is not None:
            self._client.close()
            logger.info("MongoDB ulanishi yopildi.")

    @property
    def db(self) -> Any:
        """Ma'lumotlar bazasini qaytaradi."""
        if self._db is None:
            raise DatabaseError("Baza avtomatik ulanishdan o'tmagan.")
        return self._db

    # ------------------------------------------------------------------
    # Foydalanuvchi
    # ------------------------------------------------------------------
    def get_user(self, telegram_id: int) -> dict[str, Any] | None:
        return self.db[COLLECTIONS["users"]].find_one({"telegram_id": telegram_id})

    def create_user(self, telegram_id: int, first_name: str, username: str | None) -> dict[str, Any]:
        document = {
            "telegram_id": telegram_id,
            "first_name": first_name,
            "username": username,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        self.db[COLLECTIONS["users"]].insert_one(document)
        return document

    def update_user(self, telegram_id: int, **updates: Any) -> None:
        updates["updated_at"] = datetime.now(timezone.utc)
        self.db[COLLECTIONS["users"]].update_one(
            {"telegram_id": telegram_id}, {"$set": updates}, upsert=True
        )

    # ------------------------------------------------------------------
    # Manzil
    # ------------------------------------------------------------------
    def get_location(self, telegram_id: int) -> dict[str, Any] | None:
        return (
            self.db[COLLECTIONS["locations"]]
            .find_one({"telegram_id": telegram_id}, sort=[("created_at", -1)])
        )

    def create_location(
        self,
        telegram_id: int,
        name: str,
        latitude: float,
        longitude: float,
        address: str = "",
        is_confirmed: bool = False,
    ) -> dict[str, Any]:
        document = {
            "telegram_id": telegram_id,
            "name": name,
            "latitude": latitude,
            "longitude": longitude,
            "address": address,
            "is_confirmed": is_confirmed,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        self.db[COLLECTIONS["locations"]].insert_one(document)
        return document

    def update_location(
        self,
        telegram_id: int,
        name: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        address: str | None = None,
        is_confirmed: bool | None = None,
    ) -> None:
        payload: dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
        if name is not None:
            payload["name"] = name
        if latitude is not None:
            payload["latitude"] = latitude
        if longitude is not None:
            payload["longitude"] = longitude
        if address is not None:
            payload["address"] = address
        if is_confirmed is not None:
            payload["is_confirmed"] = is_confirmed
        self.db[COLLECTIONS["locations"]].update_one(
            {"telegram_id": telegram_id}, {"$set": payload}, upsert=True
        )

    def delete_location(self, telegram_id: int) -> None:
        self.db[COLLECTIONS["locations"]].delete_many({"telegram_id": telegram_id})

    # ------------------------------------------------------------------
    # Sozlamalar
    # ------------------------------------------------------------------
    def get_settings(self, telegram_id: int) -> dict[str, Any]:
        return self.db[COLLECTIONS["settings"]].find_one({"telegram_id": telegram_id})

    def create_settings(self, telegram_id: int, **kwargs: Any) -> dict[str, Any]:
        document = {
            "telegram_id": telegram_id,
            "hourly_hour": kwargs.get("hourly_hour", 7),
            "daily_hour": kwargs.get("daily_hour", 7),
            "interval_minutes": kwargs.get("interval_minutes", 1440),
            "last_hourly_sent_at": None,
            "last_daily_sent_at": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        self.db[COLLECTIONS["settings"]].insert_one(document)
        return document

    def update_settings(self, telegram_id: int, **kwargs: Any) -> None:
        kwargs["updated_at"] = datetime.now(timezone.utc)
        self.db[COLLECTIONS["settings"]].update_one(
            {"telegram_id": telegram_id}, {"$set": kwargs}, upsert=True
        )

    def set_last_hourly_sent(self, telegram_id: int, at: datetime) -> None:
        self.db[COLLECTIONS["settings"]].update_one(
            {"telegram_id": telegram_id},
            {"$set": {"last_hourly_sent_at": at, "updated_at": datetime.now(timezone.utc)}},
            upsert=True,
        )

    def set_last_daily_sent(self, telegram_id: int, at: datetime) -> None:
        self.db[COLLECTIONS["settings"]].update_one(
            {"telegram_id": telegram_id},
            {"$set": {"last_daily_sent_at": at, "updated_at": datetime.now(timezone.utc)}},
            upsert=True,
        )