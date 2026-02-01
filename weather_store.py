"""
Хранение последнего часа погодных данных для построения графика динамики
и информации о последнем успешном скрейпе.
"""
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional

from scraper import WeatherData

# До 61 точки (0..60 минут)
MAX_POINTS = 61
_store: deque[dict[str, Any]] = deque(maxlen=MAX_POINTS)

# Последний успешный скрейп
_last_success_at: Optional[datetime] = None
_last_success_params_count: int = 0
_last_success_raw_size: int = 0


def _count_params(data: WeatherData) -> int:
    """Количество полученных параметров (не None)."""
    return sum(
        1
        for v in (
            data.temperature,
            data.wind_speed,
            data.wind_gusts,
            data.wind_direction,
            data.precipitation,
            data.battery,
        )
        if v is not None
    )


def add(data: WeatherData) -> None:
    """Добавить срез погоды (после каждого успешного скрейпа)."""
    ts = datetime.now(timezone.utc)
    global _last_success_at, _last_success_params_count, _last_success_raw_size
    _last_success_at = ts
    _last_success_params_count = _count_params(data)
    _last_success_raw_size = len(data.raw_text or "")
    record = {
        "ts": ts,
        "temperature": data.temperature,
        "wind_speed": data.wind_speed,
        "wind_gusts": data.wind_gusts,
        "wind_direction": data.wind_direction,
        "precipitation": data.precipitation,
        "battery": data.battery,
    }
    _store.append(record)


def get_last_hour() -> list[dict[str, Any]]:
    """Список записей за последний час (от старых к новым)."""
    return list(_store)


def get_last_record() -> Optional[dict[str, Any]]:
    """Последняя запись погоды (или None, если нет данных)."""
    return _store[-1] if _store else None


def get_last_success_info() -> dict[str, Any]:
    """
    Информация о последнем успешном скрейпе для /status.
    Возвращает: at (datetime | None), params_count (int), raw_size (int), weather (dict | None).
    """
    return {
        "at": _last_success_at,
        "params_count": _last_success_params_count,
        "raw_size": _last_success_raw_size,
        "weather": get_last_record(),
    }
