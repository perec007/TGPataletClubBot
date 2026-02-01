"""
Кеширование данных погоды в локальный файл.
Обращение к сайту происходит не чаще чем CACHE_TTL секунд.
"""
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

from config import CACHE_DIR, CACHE_TTL

logger = logging.getLogger(__name__)

CACHE_FILE = "weather_cache.json"


def _get_cache_path() -> Path:
    """Путь к файлу кеша."""
    cache_dir = Path(CACHE_DIR)
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / CACHE_FILE


def get_cached_data() -> Optional[dict]:
    """
    Получить закешированные данные, если они свежие (в пределах TTL).
    Возвращает dict с полями WeatherData или None, если кеш устарел/отсутствует.
    """
    cache_path = _get_cache_path()
    if not cache_path.exists():
        logger.debug("Кеш не найден: %s", cache_path)
        return None

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cached = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Ошибка чтения кеша: %s", e)
        return None

    cached_at = cached.get("cached_at", 0)
    age = time.time() - cached_at

    if age > CACHE_TTL:
        logger.info("Кеш устарел: возраст %.1f сек > TTL %d сек", age, CACHE_TTL)
        return None

    logger.info("Используем кеш: возраст %.1f сек (TTL %d сек)", age, CACHE_TTL)
    return cached.get("data")


def save_to_cache(data: dict) -> None:
    """Сохранить данные погоды в кеш."""
    cache_path = _get_cache_path()
    cached = {
        "cached_at": time.time(),
        "data": data,
    }
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cached, f, ensure_ascii=False, indent=2)
        logger.info("Кеш сохранён: %s", cache_path)
    except OSError as e:
        logger.warning("Ошибка сохранения кеша: %s", e)


def get_cache_info() -> dict:
    """Информация о состоянии кеша для /status."""
    cache_path = _get_cache_path()
    if not cache_path.exists():
        return {"exists": False, "age": None, "ttl": CACHE_TTL}

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cached = json.load(f)
        cached_at = cached.get("cached_at", 0)
        age = time.time() - cached_at
        return {"exists": True, "age": age, "ttl": CACHE_TTL}
    except Exception:
        return {"exists": False, "age": None, "ttl": CACHE_TTL}
