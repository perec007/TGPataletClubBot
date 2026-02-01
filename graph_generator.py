"""
Построение графика погодных данных.
Единый график: осадки, скорость ветра, порывы ветра, температура,
направление ветра, заряд аккумулятора. Поддержка динамики за последний час.
"""
import io
import logging
from typing import Any, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np

from config import get_timezone
from scraper import WeatherData

logger = logging.getLogger(__name__)


def _to_local_times(records: list[dict[str, Any]]) -> list:
    """Конвертировать timestamps в локальную таймзону для отображения."""
    tz = get_timezone()
    return [r["ts"].astimezone(tz) for r in records]

# Кириллица в matplotlib
plt.rcParams["font.family"] = "DejaVu Sans"
plt.rcParams["axes.unicode_minus"] = False


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _norm_series(vals: list[float]) -> list[float]:
    """Нормировка в 0–1 по min/max (для отображения на общей шкале)."""
    clean = [v for v in vals if not np.isnan(v) and v == v]
    if not clean:
        return [np.nan] * len(vals)
    lo, hi = min(clean), max(clean)
    if hi == lo:
        return [0.5 if not np.isnan(v) and v == v else np.nan for v in vals]
    return [(v - lo) / (hi - lo) if not np.isnan(v) and v == v else np.nan for v in vals]


def generate_weather_chart_timeseries(records: list[dict[str, Any]], width: int = 12, height: int = 6) -> Optional[bytes]:
    """
    Строит единый график динамики за последний час: время по X.
    Левая ось Y: только температура (°C). Правая ось: осадки (мм). Вторая правая: ветер и батарея (норм. 0–1).
    """
    if len(records) < 2:
        return None
    times = _to_local_times(records)
    fig, ax_temp = plt.subplots(figsize=(width, height))
    ax_precip = ax_temp.twinx()
    ax_other = ax_temp.twinx()
    ax_other.spines["right"].set_position(("outward", 55))
    has_any = False
    # Левая ось — только температура (°C), свой масштаб
    temp = [_safe_float(r.get("temperature")) for r in records]
    if any(t is not None for t in temp):
        vals = [t if t is not None else np.nan for t in temp]
        ax_temp.plot(times, vals, color="#e74c3c", linewidth=2, label="Температура, °C")
        ax_temp.set_ylabel("Температура, °C", color="#e74c3c", fontsize=9)
        ax_temp.tick_params(axis="y", labelcolor="#e74c3c")
        has_any = True
    # Первая правая ось — только осадки (мм), свой масштаб
    precip = [_safe_float(r.get("precipitation")) for r in records]
    if any(p is not None for p in precip):
        vals = [p if p is not None else np.nan for p in precip]
        ax_precip.plot(times, vals, color="#2ecc71", linewidth=1.5, label="Осадки, мм")
        ax_precip.set_ylabel("Осадки, мм", color="#2ecc71", fontsize=9)
        ax_precip.tick_params(axis="y", labelcolor="#2ecc71")
        ax_precip.set_ylim(bottom=0)
        has_any = True
    # Вторая правая ось — ветер и батарея (нормированные 0–1 для видимости)
    ws = [_safe_float(r.get("wind_speed")) for r in records]
    wg = [_safe_float(r.get("wind_gusts")) for r in records]
    battery = [_safe_float(r.get("battery")) for r in records]
    wd = [_safe_float(r.get("wind_direction")) for r in records]
    if any(w is not None for w in ws):
        vals = [w if w is not None else np.nan for w in ws]
        norm = _norm_series(vals)
        ax_other.plot(times, norm, color="#3498db", linewidth=1.5, linestyle="-", label="Ветер, м/с (норм.)")
        has_any = True
    if any(g is not None for g in wg):
        vals = [g if g is not None else np.nan for g in wg]
        norm = _norm_series(vals)
        ax_other.plot(times, norm, color="#9b59b6", linewidth=1.5, linestyle="-", label="Порывы, м/с (норм.)")
        has_any = True
    if any(b is not None for b in battery):
        vals = [b if b is not None else np.nan for b in battery]
        norm = _norm_series(vals)
        ax_other.plot(times, norm, color="#1abc9c", linewidth=1.5, linestyle="--", label="Батарея, % (норм.)")
        has_any = True
    if any(d is not None for d in wd):
        vals = [d if d is not None else np.nan for d in wd]
        norm = _norm_series(vals)
        ax_other.plot(times, norm, color="#f39c12", linewidth=1.5, linestyle=":", label="Направление, ° (норм.)")
        has_any = True
    if not has_any:
        plt.close(fig)
        return None
    ax_other.set_ylabel("Ветер / батарея (норм. 0–1)", fontsize=8)
    ax_other.set_ylim(0, 1)
    ax_temp.set_xlabel("Время")
    ax_temp.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax_temp.xaxis.set_major_locator(mdates.MinuteLocator(interval=max(1, len(times) // 10)))
    fig.autofmt_xdate()
    ax_temp.grid(True, alpha=0.3)
    ax_temp.legend(loc="upper left", fontsize=8)
    ax_precip.legend(loc="upper center", fontsize=8)
    ax_other.legend(loc="upper right", fontsize=8)
    plt.title("Динамика за последний час", fontsize=12, fontweight="bold")
    plt.tight_layout()
    buf = io.BytesIO()
    try:
        plt.savefig(buf, format="png", dpi=100, bbox_inches="tight")
        buf.seek(0)
        return buf.getvalue()
    except Exception as e:
        logger.exception("Ошибка построения графика динамики: %s", e)
        return None
    finally:
        plt.close(fig)


def generate_weather_chart(data: WeatherData, width: int = 10, height: int = 10) -> Optional[bytes]:
    """
    Строит единый график с погодными данными.
    Возвращает PNG в виде bytes или None при ошибке.
    """
    series = data.to_graph_series()
    if not series:
        logger.warning("Нет данных для графика")
        return None

    # Параметры для отображения (название, цвет, единицы)
    params = {
        "temperature": ("Температура, °C", "#e74c3c", "°C"),
        "wind_speed": ("Скорость ветра, м/с", "#3498db", "м/с"),
        "wind_gusts": ("Порывы ветра, м/с", "#9b59b6", "м/с"),
        "wind_direction": ("Направление ветра, °", "#f39c12", "°"),
        "precipitation": ("Осадки, мм", "#2ecc71", "мм"),
        "battery": ("Заряд аккумулятора, %", "#1abc9c", "%"),
    }

    available = [k for k in params if k in series and series[k]]
    if not available:
        return None

    n = len(available)
    fig, axes = plt.subplots(n, 1, figsize=(width, 2.5 * n), sharex=False)
    if n == 1:
        axes = [axes]

    x_pos = np.arange(1)
    x_labels = ["Текущее"]

    for ax, key in zip(axes, available):
        title, color, unit = params[key]
        vals = series[key]
        if not vals:
            continue
        val = vals[0]
        bars = ax.bar(x_pos, [val], color=color, edgecolor="black", linewidth=0.5)
        ax.set_ylabel(unit, fontsize=10)
        ax.set_title(title, fontsize=11)
        ax.set_xticks(x_pos)
        ax.set_xticklabels(x_labels)
        if key == "temperature" and val < 0:
            ax.set_ylim(top=5)
            ax.axhline(0, color="gray", linewidth=0.5)
        else:
            ax.set_ylim(bottom=0)
        # Показать значение на столбце
        for bar in bars:
            h = bar.get_height()
            va = "bottom" if h >= 0 else "top"
            offset = 5 if h >= 0 else -5
            ax.annotate(
                f"{h:.1f}",
                xy=(bar.get_x() + bar.get_width() / 2, h),
                xytext=(0, offset),
                textcoords="offset points",
                ha="center",
                va=va,
                fontsize=10,
                fontweight="bold",
            )
        ax.grid(axis="y", alpha=0.3)

    plt.suptitle("Мониторинг метеостанции — текущие показатели", fontsize=14, fontweight="bold", y=1.02)
    plt.tight_layout()

    buf = io.BytesIO()
    try:
        plt.savefig(buf, format="png", dpi=100, bbox_inches="tight")
        buf.seek(0)
        return buf.getvalue()
    except Exception as e:
        logger.exception("Ошибка построения графика: %s", e)
        return None
    finally:
        plt.close(fig)
