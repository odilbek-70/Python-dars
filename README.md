# O'zbekcha Telegram ob-havo boti

Haqiqiy ob-havo ma'lumotlari (Open-Meteo), manzil qidiruvi (OpenStreetMap Nominatim), 
MongoDB'da saqlash va Gemini AI tahlili bilan ishlaydigan Telegram bot.

## Imkoniyatlar

- 📍 **Manzil saqlash** — matn ko'rinishida (viloyat, tuman, qishloq) yoki GPS joylashuv
- 🌡 **Hozirgi ob-havo** — harorat, namlik, shamol, ob-havo holati
- 📅 **7 kunlik prognoz** — maksimal/minimal harorat, yomg'ir ehtimoli
- 🤖 **AI tahlili** — Gemini API bilan prognoz tahlili va tavsiyalar
- ⏰ **Kundalik xabar** — har kuni Toshkent vaqti 07:00 da avtomatik yuboriladi

## O'rnatish

```bash
pip install -r requirements.txt
```

## Sozlash

1. `.env.example` faylini `.env` nusxaga ko'chiring va qiymatlarni kiriting:

```dotenv
TELEGRAM_BOT_TOKEN=      # @BotFather dan oling
MONGODB_URI=mongodb://... # MongoDB ulanish manbasi
MONGODB_DATABASE=uz_weather_bot
GEMINI_API_KEY=           # Google AI Studio kaliti (ixtiyoriy)
```

2. Maxfiy kalitlar `.gitignore` tufayli Git'ga tushmaydi.

## Ishga tushirish

```bash
python bot.py
```

## Buyruqlar

| Buyruq | Vazifa |
|---|---|
| `/start` | Bosh menyu |
| `/weather` | Hozirgi ob-havo |
| `/forecast` | 7 kunlik prognoz |
| `/setlocation` | Manzilni o'zgartirish |
| `/settings` | Sozlamalar |
| `/stop` | Kunlik xabarni o'chirish |
| `/help` | Yordam |

## Tekshiruvlar

```bash
python test_smoke.py
```

Testlar: ob-havo API, geokodlash, MongoDB ulanishi, bot ilovasi va kunlik jadval.

## Railway.com ga yuklash

1. **Kodni GitHub'ga yuklang** — barcha fayllar (`.env` faylini emas, u `.gitignore` da):

```bash
git init
git add .
git commit -m "Ob-havo boti"
git remote add origin https://github.com/<username>/weather-bot.git
git push -u origin main
```

2. [railway.app](https://railway.app) da kirib **New Project → Deploy from GitHub repo** tanlang va repozitoriyni tanlang.

3. **Environment Variables** bo'limida quyidagilarni kiriting:

| O'zgaruvchi | Qiymat |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Yangi bot tokeni (@BotFather dan) |
| `MONGODB_URI` | MongoDB ulanish manbasi |
| `MONGODB_DATABASE` | `uz_weather_bot` |
| `GEMINI_API_KEY` | Google AI Studio kaliti (ixtiyoriy) |

4. Railway avtomatik `Procfile` (`web: python bot.py`) va `requirements.txt` ni ishlatadi, Python versiyasi `.python-version` dan olinadi.

5. PORT server Railway health check uchun avtomatik ishlaydi (bot `PORT` o'zgaruvchisini o'qiydi).

6. **Deploy** tugmasini bosing. Loglarda `Bot ishga tushdi` yozuvi paydo bo'lsa — bot ishlayapti.

> Railway bepul rejimida loyiha uzoq faoliyat ko'rsatmasa uxlashi mumkin. Kunlik xabarlar uchun bot doim ishlab turishi kerak.

## Muhim eslatmalar

- Ob-havo ma'lumotlari **Open-Meteo** manbasidan so'rov paytida olinadi.
- Manzil **Nominatim/OSM** orqali qidiriladi; qishloq xaritada bo'lmasa, GPS
  joylashuvdan foydalaning.
- AI tahlili mavjud prognoz raqamlariga asoslanadi; **100% aniq bashorat**
  kafolatlanmaydi.
- Kundalik xabarlar uchun bot **doim ishlab turishi** kerak (kompyuter yoki server).