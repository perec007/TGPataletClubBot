# Telegram-бот мониторинга метеостанций

Бот заходит на страницу мониторинга метеосети по HTTP, авторизуется по логину и паролю, парсит содержимое и публикует текущее состояние погоды в Telegram — текстом (графики отключены).

## Возможности

- Авторизация на странице по логину и паролю
- Парсинг данных: температура, скорость ветра, порывы ветра, направление ветра, осадки, заряд аккумулятора
- **Команда /check** — принудительный опрос погоды и вывод в чат
- **Команда /status** — дата последнего скрейпа, кеш, текущая погода и мин/макс ветра
- **Редактирование сообщения** — при заданном `MESSAGE_TO_EDIT` бот обновляет одно и то же сообщение по расписанию (новые сообщения в канал не отправляются)
- Частота обновления настраивается (`UPDATE_INTERVAL_SECONDS`)
- Кеширование — обращение к сайту не чаще `CACHE_TTL` секунд
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

2. Отредактируйте `.env`: укажите `MONITOR_URL`, `MONITOR_LOGIN`, `MONITOR_PASSWORD`, `TELEGRAM_BOT_TOKEN`.

3. **Telegram Bot Token** — получите у [@BotFather](https://t.me/BotFather), команда `/newbot`.

4. **MESSAGE_TO_EDIT** (обязательно для автообновления) — создайте сообщение в канале, скопируйте ссылку (ПКМ → «Копировать ссылку»), укажите в `.env`. Форматы: `https://t.me/c/1234567890/123` или `-1001234567890:123`. Бот будет редактировать это сообщение по расписанию.

5. **TELEGRAM_CHANNEL_ID** — опционально; сообщения в канал отправляются только в ответ на /check или /status.

## Запуск

Бот (по умолчанию): команды **/check**, **/status** + обновление сообщения по `MESSAGE_TO_EDIT` каждые `UPDATE_INTERVAL_SECONDS` секунд:

```bash
python main.py
```

Один прогон (обновление сообщения или запись в кеш) без бота:

```bash
python main.py --once
```

Тест без отправки в Telegram (проверка сбора данных):

```bash
python main.py --dry-run
```

## Docker

Сборка и запуск через Docker Compose:

```bash
cp .env.example .env
# отредактировать .env: TELEGRAM_BOT_TOKEN, MESSAGE_TO_EDIT и др.
docker compose up -d
```

Один прогон без бота:

```bash
docker compose run --rm app python main.py --once
```

Деплой на сервер (rsync + docker compose на SD-sportdom01-sel):

```bash
./deploy.sh
```

На сервере после первого деплоя отредактируйте `/srv/docker/TGParaletClubBot/.env` — `TELEGRAM_BOT_TOKEN`, `MESSAGE_TO_EDIT` и остальные параметры.

## Структура проекта

```
TGPataletClubBot/
├── main.py            # Точка входа
├── bot.py             # Отправка в Telegram, /check, /status
├── scraper.py         # Скрапинг и авторизация
├── weather_store.py   # Хранение данных за последний час
├── cache.py           # Кеширование (файловый кеш)
├── config.py          # Загрузка настроек из .env
├── graph_generator.py # (не используется — графики отключены)
├── Dockerfile
├── docker-compose.yml # Лимиты памяти/CPU, healthcheck
├── deploy.sh          # Деплой на сервер
├── requirements.txt
├── .env.example
└── README.md
```

## Переменные окружения (.env)

| Переменная | Описание |
|------------|----------|
| `MONITOR_URL` | URL страницы мониторинга |
| `MONITOR_LOGIN`, `MONITOR_PASSWORD` | Учётные данные |
| `TELEGRAM_BOT_TOKEN` | Токен бота от @BotFather |
| `TELEGRAM_CHANNEL_ID` | ID канала (опционально) |
| `MESSAGE_TO_EDIT` | Ссылка на сообщение для редактирования (обязательно для автообновления) |
| `UPDATE_INTERVAL_SECONDS` | Частота обновления (по умолчанию 60) |
| `CACHE_TTL` | TTL кеша в секундах (по умолчанию 300) |
| `CACHE_DIR` | Директория кеша (по умолчанию `./cache`) |
| `TIMEZONE` | Часовой пояс (по умолчанию `Europe/Moscow`) |
| `USE_PLAYWRIGHT` | `true`/`false` — парсинг через Playwright |

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
