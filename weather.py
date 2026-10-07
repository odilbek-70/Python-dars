"""Haqiqiy ob-havo va prognozlar uchun xizmatlar."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Open-Meteo API manba URL-lari
BASE_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODING_URL = "https://nominatim.openstreetmap.org/search"

# Open-Meteo manbasi va shimoliy kengliklar (O'zbekiston uchun)
OPEN_METEO_LAT_RANGE = (34.0, 46.0)
OPEN_METEO_LON_RANGE = (55.0, 74.0)

# HTTP sarlavhalari: Nominatim/User-Agent talab qiladi
DEFAULT_HEADERS = {
    "User-Agent": "UzWeatherBot/1.0 (Telegram ob-havo boti)",
    "Accept": "application/json",
}


class WeatherError(Exception):
    """Ob-havo yoki manzil xatoligi."""


class WeatherService:
    """Open-Meteo API orqali ob-havo ma'lumotlarini olish."""

    def __init__(self, timeout: float = 15.0) -> None:
        self._timeout = timeout

    async def get_current(self, latitude: float, longitude: float) -> dict[str, Any]:
        """Hozirgi ob-havo ma'lumotlarini olish."""
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,cloud_cover,wind_speed_10m,wind_direction_10m",
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
            "timezone": "auto",
        }
        async with httpx.AsyncClient(
            timeout=self._timeout, headers=DEFAULT_HEADERS
        ) as client:
            response = await client.get(BASE_URL, params=params)
            response.raise_for_status()
            data = response.json()

        current = data.get("current", {})
        if not current:
            raise WeatherError("Hozirgi ob-havo ma'lumotlari topilmadi.")

        return {
            "temperature": current.get("temperature_2m"),
            "apparent_temperature": current.get("apparent_temperature"),
            "humidity": current.get("relative_humidity_2m"),
            "precipitation": current.get("precipitation"),
            "weather_code": current.get("weather_code"),
            "cloud_cover": current.get("cloud_cover"),
            "wind_speed": current.get("wind_speed_10m"),
            "wind_direction": current.get("wind_direction_10m"),
            "time": current.get("time"),
        }

    async def get_daily_forecast(
        self, latitude: float, longitude: float, days: int = 7
    ) -> dict[str, Any]:
        """7 kunlik prognoz ma'lumotlarini olish."""
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code,precipitation_sum,wind_speed_10m_max",
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
            "timezone": "auto",
            "forecast_days": days,
        }
        async with httpx.AsyncClient(
            timeout=self._timeout, headers=DEFAULT_HEADERS
        ) as client:
            response = await client.get(BASE_URL, params=params)
            response.raise_for_status()
            data = response.json()

        daily = data.get("daily", {})
        if not daily:
            raise WeatherError("Prognoz ma'lumotlari topilmadi.")

        return {
            "dates": daily.get("time", []),
            "max_temp": daily.get("temperature_2m_max", []),
            "min_temp": daily.get("temperature_2m_min", []),
            "precip_prob": daily.get("precipitation_probability_max", []),
            "weather_code": daily.get("weather_code", []),
            "precip_sum": daily.get("precipitation_sum", []),
            "wind_speed": daily.get("wind_speed_10m_max", []),
        }

    async def geocode(self, address: str) -> dict[str, Any]:
        """Manzil nomini koordinataga aylantiradi (Nominatim / OSM)."""
        headers = {**DEFAULT_HEADERS, "Accept-Language": "uz,en"}
        async with httpx.AsyncClient(timeout=self._timeout, headers=headers) as client:
            response = await client.get(
                GEOCODING_URL,
                params={"q": address, "format": "json", "limit": 1},
            )
            response.raise_for_status()
            results = response.json()

        if not results:
            raise WeatherError(f"Manzil topilmadi: {address}")

        location = results[0]
        latitude = float(location["lat"])
        longitude = float(location["lon"])

        if not (OPEN_METEO_LAT_RANGE[0] <= latitude <= OPEN_METEO_LAT_RANGE[1]):
            raise WeatherError("Manzil O'zbekiston hududida emas.")
        if not (OPEN_METEO_LON_RANGE[0] <= longitude <= OPEN_METEO_LON_RANGE[1]):
            raise WeatherError("Manzil O'zbekiston hududida emas.")

        return {
            "latitude": latitude,
            "longitude": longitude,
            "display_name": location.get("display_name", address),
        }

    async def get_current_by_address(self, address: str) -> dict[str, Any]:
        """Manzil nomidan geokodlash orqali hozirgi ob-havo ma'lumotlarini olish."""
        geo = await self.geocode(address)
        return await self.get_current(geo["latitude"], geo["longitude"])

    async def get_daily_by_address(self, address: str, days: int = 7) -> dict[str, Any]:
        """Manzil nomidan geokodlash orqali prognoz ma'lumotlarini olish."""
        geo = await self.geocode(address)
        return await self.get_daily_forecast(geo["latitude"], geo["longitude"], days)

    @staticmethod
    def weather_code_to_text(code: int | None) -> str:
        """Open-Meteo weather_code ni o'zbekcha matnga aylantiradi."""
        if code is None:
            return "Noma'lum"

        codes = {
            0: "Aniq yorug'lik",
            1: "Havo shaffof, yorug'lik kuchaymoqda",
            2: "Havo shaffof, yorug'lik kamaymoqda",
            3: "Bulutli",
            45: "Tuyumli",
            48: "Tuyumli, qor yoki qorli",
            51: "Yomg'ir (ichakli)",
            53: "Yomg'ir (ichakli, kuchaymoqda)",
            55: "Yomg'ir (ichakli, kuchaymoqda)",
            56: "Yomg'ir (ichakli, qorli)",
            57: "Yomg'ir (ichakli, qorli)",
            61: "Yomg'ir (quruq)",
            63: "Yomg'ir (quruq, kuchaymoqda)",
            65: "Yomg'ir (quruq, kuchaymoqda)",
            66: "Yomg'ir (quruq, qorli)",
            67: "Yomg'ir (quruq, qorli)",
            71: "Qor (ichakli)",
            73: "Qor (ichakli, kuchaymoqda)",
            75: "Qor (ichakli, kuchaymoqda)",
            77: "Qor (ichakli)",
            80: "Yomg'ir (quruq, tushgan)",
            81: "Yomg'ir (quruq, tushgan, kuchaymoqda)",
            82: "Yomg'ir (quruq, tushgan, kuchaymoqda)",
            85: "Yomg'ir (quruq, tushgan, kuchaymoqda)",
            86: "Yomg'ir (quruq, tushgan, qorli)",
            95: "Yomg'ir (quruq, tushgan, qorli)",
            96: "Tuyumli, yomg'ir (quruq, tushgan, qorli)",
            99: "Tuyumli, yomg'ir (quruq, tushgan, qorli)",
        }
        return codes.get(code, "Noma'lum")

    @staticmethod
    def wind_direction_to_text(direction: int | None) -> str:
        """Shamol yo'nalishini o'zbekcha matnga aylantiradi."""
        if direction is None:
            return "Noma'lum"

        directions = [
            "Shimol",
            "Shim-Sharq",
            "Sharq",
            "Janub-Sharq",
            "Janub",
            "Janub-G'arb",
            "G'arb",
            "Shim-G'arb",
        ]
        index = int(direction // 45) % 8
        return directions[index]
