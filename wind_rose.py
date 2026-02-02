"""
Генерация розы ветра по данным за последние N минут и наложение на фоновое изображение.
На одном графике: скорость ветра (средняя) и порывы (макс) по направлениям.
"""
import io
import logging
import os
from datetime import datetime, timezone
from typing import Any

import matplotlib
# Бэкенд mplcairo поддерживает цветные шрифты (эмодзи) через Raqm
matplotlib.use("module://mplcairo.base")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt

# Регистрируем Noto Color Emoji по пути (matplotlib не находит по имени без этого)
_EMOJI_FONT_PATHS = [
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    "/usr/share/fonts/noto/NotoColorEmoji.ttf",
]
_emoji_font_name = None
for _path in _EMOJI_FONT_PATHS:
    if os.path.isfile(_path):
        try:
            fm.fontManager.addfont(_path)
            _emoji_font_name = fm.FontProperties(fname=_path).get_name()
            break
        except Exception:
            pass

if _emoji_font_name:
    matplotlib.rcParams["font.family"] = ["DejaVu Sans", _emoji_font_name, "DejaVu Sans"]
else:
    matplotlib.rcParams["font.family"] = ["DejaVu Sans"]
import numpy as np
from matplotlib.patches import FancyBboxPatch, Patch, Rectangle
from PIL import Image

from config import format_datetime_local

logger = logging.getLogger(__name__)

NUM_SECTORS = 16
DEG_PER_SECTOR = 360 / NUM_SECTORS


def _aggregate_by_sector(records: list[dict[str, Any]]) -> tuple[list[float], list[float], list[float]]:
    """
    Агрегирует (direction, speed, gusts) по секторам.
    Возвращает (углы в радианах, средние скорости, макс порывы) для 16 секторов.
    """
    sector_speeds: list[list[float]] = [[] for _ in range(NUM_SECTORS)]
    sector_gusts: list[list[float]] = [[] for _ in range(NUM_SECTORS)]
    for r in records:
        direction = r.get("wind_direction")
        speed = r.get("wind_speed")
        gust = r.get("wind_gusts")
        if direction is None:
            continue
        direction = float(direction) % 360
        sector_idx = int(direction / DEG_PER_SECTOR) % NUM_SECTORS
        if speed is not None:
            sector_speeds[sector_idx].append(float(speed))
        if gust is not None:
            sector_gusts[sector_idx].append(float(gust))
    angles_rad = []
    avg_speeds = []
    max_gusts = []
    for i in range(NUM_SECTORS):
        center_deg = (i + 0.5) * DEG_PER_SECTOR
        theta_rad = np.radians(90 - center_deg)
        angles_rad.append(theta_rad)
        avg_speeds.append(np.mean(sector_speeds[i]) if sector_speeds[i] else 0.0)
        max_gusts.append(max(sector_gusts[i]) if sector_gusts[i] else 0.0)
    return angles_rad, avg_speeds, max_gusts


# Символ для легенды (в DejaVu Sans)
_LEGEND_TEMP = "●"   # температура


def _build_combined_stats(records: list[dict[str, Any]], label_speed: str, label_gusts: str) -> str:
    """Формирует одну строку: температура, скорость и порывы."""
    if not records:
        return ""
    last = records[-1]
    parts = []
    if last.get("temperature") is not None:
        parts.append(f"{_LEGEND_TEMP} Темп.: {last['temperature']} °C")
    parts.append(label_speed)
    parts.append(label_gusts)
    return "  ·  ".join(parts)


# Стиль: тёмные панели, читаемые на любом фоне
_BOX_FACE = "#1e2a3a"
_BOX_EDGE = "#3d5a80"
_BOX_ALPHA = 0.94
_TITLE_FACE = "#152238"
_TITLE_EDGE = "#2d4a6f"
_TEXT_COLOR = "#f0f4f8"
_GRID_COLOR = "#b8c9d9"
_GRID_ALPHA = 0.45
# Цвета столбцов: скорость — холодный синий, порывы — тёплый коралловый
_COLOR_SPEED = "#2980b9"
_COLOR_SPEED_EDGE = "#1a5276"
_COLOR_GUST = "#e74c3c"
_COLOR_GUST_EDGE = "#c0392b"


def generate_wind_rose_png(
    records: list[dict[str, Any]],
    background_path: str,
    title: str = "Скорость и порывы ветра (10 мин)",
) -> bytes:
    """
    Строит одну розу: скорость ветра (синие столбцы) и порывы (красные) по направлениям.
    Добавляет подпись (заголовок) и легенду с температурой, ветром и порывами (текущие и мин/макс).
    Накладывает на фон. Возвращает PNG.
    """
    if not records:
        raise ValueError("Нет данных для розы ветра")
    angles_rad, avg_speeds, max_gusts = _aggregate_by_sector(records)
    if not any(avg_speeds) and not any(max_gusts):
        raise ValueError("Нет данных о ветре (скорость/порывы) в записях")
    if not os.path.isfile(background_path):
        raise FileNotFoundError(f"Фоновое изображение не найдено: {background_path}")
    bg = Image.open(background_path).convert("RGBA")
    w, h = bg.size

    fig = plt.figure(figsize=(w / 100, h / 100), dpi=100, facecolor="none")
    fig.patch.set_alpha(0)
    fig.subplots_adjust(left=0.04, right=0.96, top=0.96, bottom=0.04)
    # Квадратная область для полярной розы (уменьшена на 30%, затем ещё на 10%; смещена вверх на 20%)
    _rose_size = 0.72 * 0.70 * 0.90
    _rose_left = (1 - _rose_size) / 2
    _rose_bottom = 0.14 + 0.20
    ax = fig.add_axes([_rose_left, _rose_bottom, _rose_size, _rose_size], projection="polar", facecolor="none")
    ax.patch.set_alpha(0)

    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    max_r = max(max(avg_speeds) if avg_speeds else 0, max(max_gusts) if max_gusts else 0)
    if max_r == 0:
        max_r = 1
    ax.set_ylim(0, max_r * 1.2)
    ax.set_yticks(np.linspace(0, max_r, 5))
    ax.set_yticklabels(
        [f"{x:.1f}" for x in np.linspace(0, max_r, 5)],
        fontsize=22, color=_TEXT_COLOR, weight="bold",
    )
    ax.set_xticks(np.radians(np.arange(0, 360, 360 // 8)))
    ax.set_xticklabels(
        ["С", "С-В", "В", "Ю-В", "Ю", "Ю-З", "З", "С-З"],
        fontsize=24, weight="bold", color=_TEXT_COLOR,
    )
    ax.grid(color=_GRID_COLOR, linestyle="-", linewidth=0.7, alpha=_GRID_ALPHA)
    ax.spines["polar"].set_color(_GRID_COLOR)
    ax.spines["polar"].set_alpha(0.5)
    ax.spines["polar"].set_linewidth(1.0)

    half_width_rad = np.radians(DEG_PER_SECTOR * 0.24)
    angles_speed = [t - half_width_rad for t in angles_rad]
    angles_gusts = [t + half_width_rad for t in angles_rad]
    bar_width = np.radians(DEG_PER_SECTOR * 0.38)

    # Текущие значения для легенды (последняя запись)
    last = records[-1]
    cur_speed = last.get("wind_speed")
    cur_gusts = last.get("wind_gusts")
    label_speed = f"Скорость: {cur_speed:.1f} м/с" if cur_speed is not None else "Скорость, м/с"
    label_gusts = f"Порывы: {cur_gusts:.1f} м/с" if cur_gusts is not None else "Порывы, м/с"

    # Скорость — единый синий тон, полупрозрачность для читаемости на фоне
    ax.bar(angles_speed, avg_speeds, width=bar_width, bottom=0, color=_COLOR_SPEED,
           edgecolor=_COLOR_SPEED_EDGE, linewidth=1.2, alpha=0.88)
    # Порывы — коралловый, контраст с синим
    ax.bar(angles_gusts, max_gusts, width=bar_width, bottom=0, color=_COLOR_GUST,
           edgecolor=_COLOR_GUST_EDGE, linewidth=1.2, alpha=0.88)

    # Лёгкое кольцо по внешнему радиусу для чёткости круга
    ax.plot(np.linspace(0, 2 * np.pi, 100), [max_r * 1.2] * 100,
            color=_GRID_COLOR, linewidth=1.0, alpha=0.35, zorder=0)

    # Заголовок вверху (опущен ниже)
    fig.text(0.5, 0.96, "Аэродром Паралёт", ha="center", va="top", fontsize=30, weight="bold", color=_TEXT_COLOR)

    # Температура, скорость и порывы — в столбик по левому краю, фон 90% прозрачный, без перекрытия строк
    last = records[-1]
    temp_str = f"{_LEGEND_TEMP} Темп.: {last['temperature']} °C" if last.get("temperature") is not None else None
    _x_left = 0.07
    _sq_size = 0.022
    _gap = 0.012
    _x_text_after_sq = _x_left + _sq_size + _gap
    _line_height = 0.042
    _y1 = 0.118 + 0.10
    _y2 = _y1 - _line_height
    _y3 = _y2 - _line_height
    _gap_before_date = 0.018
    _block_bottom = _y3 - 0.025
    _block_height = _y1 - _block_bottom + 0.012
    _block_width = 0.42

    # Фон блока по левому краю (90% прозрачность)
    fig.add_artist(FancyBboxPatch((_x_left - 0.01, _block_bottom), _block_width, _block_height, boxstyle="round,pad=0.012",
                                  facecolor=_BOX_FACE, alpha=0.1, edgecolor="none", transform=fig.transFigure))

    if temp_str:
        fig.text(_x_left, _y1, temp_str, ha="left", va="bottom", fontsize=20, color=_TEXT_COLOR, weight="bold",
                 family="sans-serif")
    fig.add_artist(Rectangle((_x_left, _y2 - 0.01), _sq_size, _sq_size * 0.85,
                             facecolor=_COLOR_SPEED, edgecolor=_COLOR_SPEED_EDGE, linewidth=0.8, transform=fig.transFigure))
    fig.text(_x_text_after_sq, _y2, label_speed, ha="left", va="bottom", fontsize=20, color=_TEXT_COLOR, weight="bold",
             family="sans-serif")
    fig.add_artist(Rectangle((_x_left, _y3 - 0.01), _sq_size, _sq_size * 0.85,
                             facecolor=_COLOR_GUST, edgecolor=_COLOR_GUST_EDGE, linewidth=0.8, transform=fig.transFigure))
    fig.text(_x_text_after_sq, _y3, label_gusts, ha="left", va="bottom", fontsize=20, color=_TEXT_COLOR, weight="bold",
             family="sans-serif")

    now = datetime.now(timezone.utc)
    date_str = format_datetime_local(now)
    # Дата генерации — ниже блока, с зазором чтобы не перекрывалась с «Порывы»
    _date_y = max(0.0005, _block_bottom - _gap_before_date)
    fig.text(0.07, _date_y, date_str, ha="left", va="bottom", fontsize=18, color=_TEXT_COLOR, family="sans-serif")

    plt.tight_layout(pad=0.03)

    buf = io.BytesIO()
    # Сохраняем без bbox_inches="tight", холст w×h как у фона
    fig.savefig(buf, format="png", dpi=100, transparent=True)
    plt.close(fig)
    buf.seek(0)
    rose_png = Image.open(buf).convert("RGBA")
    if rose_png.size != (w, h):
        rose_png = rose_png.resize((w, h), Image.Resampling.LANCZOS)
    bg.paste(rose_png, (0, 0), rose_png)

    out = io.BytesIO()
    bg.save(out, format="PNG")
    out.seek(0)
    return out.getvalue()


def get_default_background_path() -> str:
    """Путь к фоновому изображению по умолчанию (относительно корня проекта)."""
    base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "assets", "wind_rose_background.png")
