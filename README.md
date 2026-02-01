# Telegram-бот мониторинга метеостанций

Бот заходит на страницу мониторинга метеосети по HTTP, авторизуется по логину и паролю, парсит содержимое и публикует текущее состояние погоды в Telegram-канал — текстом и в виде графика.

## Возможности

- Авторизация на странице по логину и паролю
- Парсинг данных: температура, скорость ветра, порывы ветра, направление ветра, осадки, заряд аккумулятора
- **Команда /check** — принудительный опрос погоды и вывод текста и графика в чат
- Автопубликация в Telegram-канал **раз в 1 минуту**
- Построение единого графика по всем параметрам
- Настройки в `.env`

## Установка

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

> **Примечание:** Playwright нужен для парсинга страниц с динамической загрузкой данных через JavaScript. Если Playwright не устанавливается или не работает (например, на ARM Mac), задайте `USE_PLAYWRIGHT=false` в `.env` — бот будет использовать только requests (данные могут быть неполными).

## Настройка

1. Скопируйте `.env.example` в `.env`:
   ```bash
   cp .env.example .env
   ```

2. Отредактируйте `.env`: укажите `MONITOR_URL`, `MONITOR_LOGIN`, `MONITOR_PASSWORD`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHANNEL_ID`.

3. **Telegram Bot Token** — получите у [@BotFather](https://t.me/BotFather), команда `/newbot`.

4. **ID канала** — добавьте бота в канал как администратора. Канал может быть публичным (`@channel_name`) или приватным (числовой ID вида `-1001234567890`).

## Запуск

Бот (по умолчанию): команда **/check** в чате + автоматическая публикация в канал раз в 1 минуту:

```bash
python main.py
```

Один прогон в канал без бота (для cron и т.п.):

```bash
python main.py --once
```

Тест без отправки в Telegram (проверка сбора данных и построения графика):

```bash
python main.py --dry-run
```

## Docker

Сборка и запуск через Docker Compose (бот с /check и публикацией в канал раз в 1 минуту):

```bash
cp .env.example .env
# отредактировать .env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID
docker compose up -d
```

Один прогон в канал без бота:

```bash
docker compose run --rm app python main.py --once
```

Деплой на сервер (rsync + docker compose на SD-sportdom01-sel):

```bash
./deploy.sh
```

На сервере после первого деплоя нужно задать реальные `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHANNEL_ID` в `/srv/docker/TGParaletClubBot/.env`.

## Структура проекта

```
TGPataletClubBot/
├── main.py           # Точка входа
├── bot.py            # Отправка в Telegram
├── scraper.py        # Скрапинг и авторизация
├── graph_generator.py # Построение графика
├── config.py         # Загрузка настроек из .env
├── Dockerfile
├── docker-compose.yml
├── deploy.sh         # Деплой на сервер
├── requirements.txt
├── .env.example
└── README.md
```

## Адаптация под страницу

Если структура страницы отличается от ожидаемой, в `scraper.py` можно:

1. Расширить `LABEL_MAP` — маппинг подписей на поля.
2. Добавить парсеры в `_parse_table`, `_parse_divs_spans`, `_parse_text_blocks`.
3. При необходимости включить логирование и сохранять HTML для отладки:

```python
with open("debug.html", "w", encoding="utf-8") as f:
    f.write(resp.text)
```

## Лицензия

MIT
