"""Gemini tahlili (AI tahlili) — mavjud ob-havo ma'lumotlariga asoslanadi."""

from __future__ import annotations

import logging
from typing import Any

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# AI tahlili uchun API kaliti (.env ichidagi GEMINI_API_KEY)
import os

try:
    from google import genai
except ImportError:  # pragma: no cover - qo'shimcha kutubxona o'rnatilmagan
    genai = None

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip() or None


class GeminiError(Exception):
    """AI xizmatidan xatolik."""


class GeminiService:
    """Gemini orqali tahlil qilish (mavjud ma'lumotlarga asoslanadi)."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or GEMINI_API_KEY

    def analyze(self, current: dict[str, Any], daily: dict[str, Any]) -> dict[str, Any]:
        """
        AI tahlilini qaytaradi.
        AI kaliti mavjud bo'lsa, tahlil beradi; aks holda mavjud ma'lumotlarga
        asoslanib oddiy tavsiyalar beradi.
        """
        if not self._api_key:
            return self._fallback_analysis(current, daily)

        try:
            # AI tahlili uchun so'rov (mavjud ma'lumotlar)
            prompt = self._build_prompt(current, daily)
            # AI tahlilini olish (real ishlatishda genai klia va so'rovni
            # to'g'ri yuborish kerak; bu yerda mavjud ma'lumotlar uchun
            # oddiy tahlil qaytaradi)
            return self._call_gemini(prompt)
        except Exception as exc:  # pragma: no cover - xatoliklarni boshqarish
            logger.warning("Gemini tahlili bajarilmadi: %s", exc)
            return self._fallback_analysis(current, daily)

    def _build_prompt(self, current: dict[str, Any], daily: dict[str, Any]) -> str:
        """AI tahlil uchun so'rov matnini yaratadi."""
        current_temp = current.get("temperature")
        current_weather = current.get("weather_code")
        daily_max = daily.get("max_temp", [])
        daily_min = daily.get("min_temp", [])
        daily_precip = daily.get("precip_prob", [])

        return (
            "Quyidagi ob-havo ma'lumotlariga asoslanib, foydalanuvchi uchun "
            "tovushli va tushunarli tahlil yoz:\n"
            f"Bugungi harorat: {current_temp}°C, ob-havo kodi: {current_weather}\n"
            f"7 kunlik prognoz maksimal haroratlar: {daily_max}\n"
            f"7 kunlik prognoz minimal haroratlar: {daily_min}\n"
            f"7 kunlik prognoz yomg'ir ehtimoli: {daily_precip}\n"
            "Tahlilda quyidagilardan foydalanib, kundalik faoliyat, qorimlik "
            "va ob-havo bo'yicha tavsiyalar bering."
        )

    def _call_gemini(self, prompt: str) -> dict[str, Any]:
        """Gemini API ga so'rov yuboradi."""
        if genai is None:
            raise GeminiError("Gemini kutubxona o'rnatilmagan.")

        client = genai.Client(api_key=self._api_key)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        text = response.text.strip()
        return {"analysis": text, "source": "gemini"}

    def _fallback_analysis(
        self, current: dict[str, Any], daily: dict[str, Any]
    ) -> dict[str, Any]:
        """AI kaliti yo'qligi uchun oddiy tahlil."""
        current_temp = current.get("temperature")
        current_weather = current.get("weather_code")
        daily_max = daily.get("max_temp", [])
        daily_min = daily.get("min_temp", [])
        daily_precip = daily.get("precip_prob", [])

        # Oddiy tavsiyalar
        if current_temp is not None and current_temp < 5:
            advice = "Kundalik faoliyat uchun qorimlik qo'llang; qor bo'lishi mumkin."
        elif current_temp is not None and current_temp > 30:
            advice = "Sovish uchun suv ichishni unutmang; shamol va quvur yordam beradi."
        else:
            advice = "Ob-havo odatda; shaffof havo va qulay ko'nikmalarni tanlang."

        if daily_precip and any(p > 60 for p in daily_precip):
            advice += " Kundalik yomg'ir ehtimoli yuqori, shuning uchun qo'lliq qoplamalarni oling."

        return {
            "analysis": (
                f"Bugungi harorat {current_temp}°C, ob-havo kodi {current_weather}. "
                f"7 kunlik maksimal haroratlar: {daily_max}, minimal haroratlar: {daily_min}. "
                f"Yomg'ir ehtimoli: {daily_precip}. {advice}"
            ),
            "source": "fallback",
        }