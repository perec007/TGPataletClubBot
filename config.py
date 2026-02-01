"""Загрузка настроек из .env"""
import os
import re
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()


def get_str(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def get_int(key: str, default: int = 0) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


# Настройки мониторинга
MONITOR_URL = get_str("MONITOR_URL")
MONITOR_LOGIN = get_str("MONITOR_LOGIN")
MONITOR_PASSWORD = get_str("MONITOR_PASSWORD")

# Telegram
TELEGRAM_BOT_TOKEN = get_str("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = get_str("TELEGRAM_CHANNEL_ID")

# Список ID администраторов через запятую. Только они могут использовать /check и /status.
# Если пусто — команды доступны всем.
ADMIN_IDS_RAW = get_str("ADMIN_IDS", "")
ADMIN_IDS: set[int] = set()
if ADMIN_IDS_RAW:
    for part in ADMIN_IDS_RAW.replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit() or (part.startswith("-") and part[1:].isdigit()):
            ADMIN_IDS.add(int(part))

# Ссылка на сообщение для редактирования вместо отправки нового.
# Формат: https://t.me/c/1234567890/123 (приватный канал) или t.me/c/1234567890/123
# Если задано — бот будет редактировать это сообщение при каждой публикации.
MESSAGE_TO_EDIT = get_str("MESSAGE_TO_EDIT")

# Частота обновления «📊 Текущее состояние погоды» (в секундах). По умолчанию 60.
UPDATE_INTERVAL_SECONDS = max(10, get_int("UPDATE_INTERVAL_SECONDS", 60))


def parse_message_link(link: str) -> Optional[tuple[int | str, int]]:
    """
    Парсит ссылку на сообщение Telegram.
    Возвращает (chat_id, message_id) или None.
    Поддерживает:
      - t.me/c/1234567890/123 (приватный канал)
      - t.me/username/123 (публичный канал)
      - -1001234567890:123 (chat_id:message_id)
    """
    if not link or not link.strip():
        return None
    link = link.strip()

    # Формат chat_id:message_id (например -1001234567890:123)
    m = re.match(r"^(-?\d+):(\d+)$", link)
    if m:
        return (int(m.group(1)), int(m.group(2)))

    # t.me/c/1234567890/123 — приватный канал
    m = re.search(r"t\.me/c/(\d+)/(\d+)", link, re.I)
    if m:
        channel_part = int(m.group(1))
        message_id = int(m.group(2))
        chat_id = int(f"-100{channel_part}")
        return (chat_id, message_id)

    # t.me/username/123 или telegram.me/username/123 — публичный канал
    m = re.search(r"(?:t\.me|telegram\.me)/([a-zA-Z0-9_]+)/(\d+)", link, re.I)
    if m:
        username = m.group(1)
        if username.lower() != "c":  # "c" — префикс приватного канала, уже обработан выше
            return (f"@{username}", int(m.group(2)))

    return None


def parse_message_links(raw: str) -> list[tuple[int | str, int]]:
    """
    Парсит несколько ссылок на сообщения Telegram.
    Ссылки разделяются запятой, переносом строки или пробелом.
    Возвращает список (chat_id, message_id) для всех распознанных ссылок.
    """
    if not raw or not raw.strip():
        return []
    # Разделяем по запятой, переносу строки или нескольким пробелам
    parts = re.split(r"[,\n]+", raw)
    results = []
    for part in parts:
        parsed = parse_message_link(part.strip())
        if parsed:
            results.append(parsed)
    return results

# Режим парсинга: playwright (JS) или requests (HTML)
USE_PLAYWRIGHT = get_str("USE_PLAYWRIGHT", "true").lower() in ("true", "1", "yes")

# Кеширование
CACHE_DIR = get_str("CACHE_DIR", "./cache")
CACHE_TTL = get_int("CACHE_TTL", 300)  # TTL кеша в секундах (по умолчанию 5 минут)

# Часовой пояс для отображения времени (Europe/Moscow, Europe/London, UTC и т.д.)
TIMEZONE = get_str("TIMEZONE", "Europe/Moscow")

_tz = None


def get_timezone():
    """Возвращает ZoneInfo для настроенной таймзоны."""
    global _tz
    if _tz is None:
        try:
            _tz = ZoneInfo(TIMEZONE)
        except Exception:
            _tz = ZoneInfo("UTC")
    return _tz


def format_datetime_local(dt: datetime) -> str:
    """Конвертирует datetime (UTC) в локальное время и форматирует строку."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    local = dt.astimezone(get_timezone())
    return local.strftime("%Y-%m-%d %H:%M:%S %Z")
