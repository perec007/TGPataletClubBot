"""
Telegram-бот для публикации данных мониторинга погоды в канал и команды /check.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from telegram import Bot, Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes

from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHANNEL_ID,
    MESSAGE_TO_EDIT,
    UPDATE_INTERVAL_SECONDS,
    ADMIN_IDS,
    format_datetime_local,
    parse_message_link,
    parse_message_links,
)
from cache import get_cache_info
from scraper import MonitoringScraper, WeatherData, format_wind_direction
from weather_store import add as store_add, get_last_hour as store_get_last_hour, get_last_minutes as store_get_last_minutes, get_last_success_info as store_get_last_success

logger = logging.getLogger(__name__)


def is_admin(user_id: int | None) -> bool:
    """Проверяет, является ли пользователь администратором. Если ADMIN_IDS не задан — разрешено всем."""
    if not ADMIN_IDS:
        return True
    return user_id in ADMIN_IDS if user_id else False


def _append_update_date(text: str) -> str:
    """Добавляет строку с датой обновления в конец сообщения."""
    now = datetime.now(timezone.utc)
    date_str = format_datetime_local(now)
    return text.rstrip() + f"\n\n🕐 Обновлено: {date_str}"


def _get_hourly_stats(records: list) -> str:
    """Формирует статистику за последний час: макс/мин ветер, порывы и осадки."""
    lines = []
    ws = [r.get("wind_speed") for r in records if r.get("wind_speed") is not None]
    wg = [r.get("wind_gusts") for r in records if r.get("wind_gusts") is not None]
    prec = [r.get("precipitation") for r in records if r.get("precipitation") is not None]
    if ws:
        lines.append(f"💨 Ветер: макс {max(ws):.1f} м/с, мин {min(ws):.1f} м/с")
    if wg:
        lines.append(f"🌀 Порывы: макс {max(wg):.1f} м/с, мин {min(wg):.1f} м/с")
    if prec:
        lines.append(f"🌧 Осадки за час: {sum(prec):.1f} мм")
    if lines:
        return "\n\n**Макс. и мин. за час:**\n" + "\n".join(lines)
    return ""


def _get_10min_stats(records: list) -> str:
    """Формирует статистику за последние 10 минут: макс/мин ветер, порывы и осадки."""
    lines = []
    ws = [r.get("wind_speed") for r in records if r.get("wind_speed") is not None]
    wg = [r.get("wind_gusts") for r in records if r.get("wind_gusts") is not None]
    prec = [r.get("precipitation") for r in records if r.get("precipitation") is not None]
    if ws:
        lines.append(f"💨 Ветер: макс {max(ws):.1f} м/с, мин {min(ws):.1f} м/с")
    if wg:
        lines.append(f"🌀 Порывы: макс {max(wg):.1f} м/с, мин {min(wg):.1f} м/с")
    if prec:
        lines.append(f"🌧 Осадки: {sum(prec):.1f} мм")
    if lines:
        return "\n\n**Макс. и мин. за 10 мин.:**\n" + "\n".join(lines)
    return ""


def _get_battery_line(records: list) -> str:
    """Возвращает строку с напряжением аккумулятора из последней записи."""
    if records:
        last = records[-1]
        if last.get("battery") is not None:
            return f"\n\n🔋 Аккумулятор: {last['battery']} В"
    return ""


def _fetch_weather_sync() -> WeatherData:
    """Синхронный скрейп (для запуска в executor, чтобы не блокировать event loop)."""
    scraper = MonitoringScraper()
    return scraper.fetch_weather()


async def send_weather_to_chat(
    chat_id: int | str,
    data: Optional[WeatherData] = None,
    bot: Optional[Bot] = None,
) -> bool:
    """Отправить погоду (текст + график) в указанный чат. Возвращает True при успехе."""
    if data is None:
        # Скрейп синхронный и может долго выполняться — запускаем в потоке
        try:
            data = await asyncio.to_thread(_fetch_weather_sync)
        except Exception as e:
            logger.exception("Ошибка скрейпа при /check: %s", e)
            return False
    store_add(data)
    text = data.to_text()
    has_data = any([data.temperature, data.wind_speed, data.wind_gusts, data.wind_direction, data.precipitation, data.humidity, data.battery])
    if not has_data:
        text += "\n⚠️ Данные не получены. Проверьте доступность страницы и селекторы парсера."
    records_hour = store_get_last_hour()
    records_10min = store_get_last_minutes(10)
    text += _get_10min_stats(records_10min)
    text += _get_hourly_stats(records_hour)
    text += _get_battery_line(records_hour)
    text = _append_update_date(text)
    token = TELEGRAM_BOT_TOKEN
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN не задан")
        return False
    b = bot or Bot(token=token)
    try:
        await b.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.MARKDOWN)
        return True
    except TelegramError as e:
        logger.exception("Ошибка отправки в чат %s: %s", chat_id, e)
        return False
    except Exception as e:
        logger.exception("Ошибка при отправке погоды в чат %s: %s", chat_id, e)
        return False


def _format_weather_line(label: str, value, unit: str) -> str:
    """Форматирование строки погоды с проверкой на None."""
    if value is None:
        return f"{label}: —"
    return f"{label}: {value} {unit}"


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /status — дата последнего успешного скрейпа, объём данных, кеш и текущая погода."""
    if not update.effective_chat:
        return
    user_id = update.effective_user.id if update.effective_user else None
    if not is_admin(user_id):
        logger.info("Пользователь %s не админ — /status отклонено", user_id)
        return
    msg = update.effective_message
    info = store_get_last_success()
    at = info["at"]
    params_count = info["params_count"]
    raw_size = info["raw_size"]
    weather = info.get("weather")
    cache_info = get_cache_info()

    if at is None:
        text = "📋 **Статус**\n\nУспешных скрейпов пока не было."
    else:
        at_str = format_datetime_local(at)
        text = (
            "📋 **Статус**\n\n"
            f"🕐 Последний скрейп: {at_str}\n"
            f"📊 Параметров: {params_count}/7\n"
            f"📦 Сырых данных: {raw_size} байт\n"
        )
        # Информация о кеше
        if cache_info["exists"]:
            age = cache_info["age"]
            ttl = cache_info["ttl"]
            remaining = max(0, ttl - age) if age else 0
            text += f"\n💾 **Кеш**\nВозраст: {age:.0f} сек, TTL: {ttl} сек\nДо обновления: {remaining:.0f} сек\n"
        else:
            text += f"\n💾 **Кеш**: отсутствует (TTL: {cache_info['ttl']} сек)\n"

        if weather:
            text += (
                "\n🌡 **Погода**\n"
                f"🌡 {_format_weather_line('Температура', weather.get('temperature'), '°C')}\n"
                f"💨 {_format_weather_line('Ветер', weather.get('wind_speed'), 'м/с')}\n"
                f"🌀 {_format_weather_line('Порывы', weather.get('wind_gusts'), 'м/с')}\n"
                f"🧭 Направление: {format_wind_direction(weather.get('wind_direction'))}\n"
                f"💧 {_format_weather_line('Влажность', weather.get('humidity'), '%')}\n"
                f"🌧 {_format_weather_line('Осадки', weather.get('precipitation'), 'мм')}\n"
                f"🔋 {_format_weather_line('Аккумулятор', weather.get('battery'), 'В')}"
            )
        # Мин/макс ветра за последний час
        records = store_get_last_hour()
        hourly = _get_hourly_stats(records)
        if hourly:
            text += hourly
    try:
        await (msg.reply_text(text, parse_mode=ParseMode.MARKDOWN) if msg else context.bot.send_message(update.effective_chat.id, text, parse_mode=ParseMode.MARKDOWN))
    except TelegramError as e:
        logger.exception("Ошибка отправки /status: %s", e)


async def check_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /check — принудительный опрос погоды и вывод в чат."""
    if not update.effective_chat:
        return
    user_id = update.effective_user.id if update.effective_user else None
    if not is_admin(user_id):
        logger.info("Пользователь %s не админ — /check отклонено", user_id)
        return
    chat_id = update.effective_chat.id
    msg = update.effective_message
    try:
        await (msg.reply_text("Запрашиваю данные с метеостанции...") if msg else context.bot.send_message(chat_id, "Запрашиваю данные с метеостанции..."))
    except TelegramError:
        pass
    try:
        ok = await send_weather_to_chat(chat_id, bot=context.bot)
        if not ok and msg:
            await msg.reply_text("Не удалось получить или отправить данные.")
    except Exception as e:
        logger.exception("Ошибка в /check: %s", e)
        if msg:
            try:
                await msg.reply_text(f"Ошибка: {e!s}")
            except TelegramError:
                pass


async def publish_weather_to_channel(
    data: Optional[WeatherData] = None,
    channel_id: Optional[str] = None,
    bot_token: Optional[str] = None,
    dry_run: bool = False,
) -> bool:
    """
    Собрать данные, построить график и отправить в Telegram-канал.
    Возвращает True при успехе.
    """
    channel_id = channel_id or TELEGRAM_CHANNEL_ID
    bot_token = bot_token or TELEGRAM_BOT_TOKEN
    edit_targets = parse_message_links(MESSAGE_TO_EDIT)

    if MESSAGE_TO_EDIT and not edit_targets:
        logger.warning(
            "MESSAGE_TO_EDIT задан, но ни одна ссылка не распознана: %r. "
            "Поддерживаемые форматы: t.me/c/1234567890/123, t.me/username/123, -1001234567890:123",
            MESSAGE_TO_EDIT[:80] if len(MESSAGE_TO_EDIT) > 80 else MESSAGE_TO_EDIT,
        )

    if not dry_run and not bot_token:
        logger.error("TELEGRAM_BOT_TOKEN не задан в .env")
        return False

    if data is None:
        try:
            data = await asyncio.to_thread(_fetch_weather_sync)
        except Exception as e:
            logger.exception("Ошибка скрейпа при публикации в канал: %s", e)
            return False
    store_add(data)

    if dry_run:
        logger.info("Dry-run: данные собраны.")
        logger.info("Текст: %s", data.to_text())
        return True

    if not edit_targets:
        # Без MESSAGE_TO_EDIT ничего не публикуем — сообщения в канал только через /check или /status
        return True

    bot = Bot(token=bot_token)

    # Текстовое сообщение + статистика за 10 мин + час + батарея + дата обновления внизу
    text = data.to_text()
    has_data = any([data.temperature, data.wind_speed, data.wind_gusts, data.wind_direction, data.precipitation, data.humidity, data.battery])
    if not has_data:
        text += "\n⚠️ Данные не получены. Проверьте доступность страницы и селекторы парсера."
    records_hour = store_get_last_hour()
    records_10min = store_get_last_minutes(10)
    text += _get_10min_stats(records_10min)
    text += _get_hourly_stats(records_hour)
    text += _get_battery_line(records_hour)
    text = _append_update_date(text)

    # Редактируем все сообщения из списка
    success = True
    for chat_id_edit, message_id in edit_targets:
        try:
            await bot.edit_message_text(
                chat_id=chat_id_edit,
                message_id=message_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
            )
            logger.info("Сообщение отредактировано: chat_id=%s, message_id=%s", chat_id_edit, message_id)
        except TelegramError as e:
            logger.exception("Ошибка редактирования сообщения chat_id=%s, message_id=%s: %s", chat_id_edit, message_id, e)
            success = False

    return success


async def job_publish_to_channel(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Фоновая задача: публикация погоды в канал или обновление сообщений (раз в минуту)."""
    if not TELEGRAM_CHANNEL_ID and not parse_message_links(MESSAGE_TO_EDIT):
        return
    await publish_weather_to_channel()


def run_bot(poll_interval_seconds: int | None = None) -> None:
    """Запуск бота: команда /check и обновление «Текущее состояние погоды» по расписанию."""
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN не задан в .env")
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("check", check_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    edit_targets_startup = parse_message_links(MESSAGE_TO_EDIT)
    has_channel_or_edit = TELEGRAM_CHANNEL_ID or edit_targets_startup
    if MESSAGE_TO_EDIT:
        logger.info("MESSAGE_TO_EDIT=%r -> parsed %d link(s): %s", MESSAGE_TO_EDIT, len(edit_targets_startup), edit_targets_startup)
    if ADMIN_IDS:
        logger.info("ADMIN_IDS: %s (команды /check и /status только для них)", ADMIN_IDS)
    else:
        logger.info("ADMIN_IDS не задан — команды /check и /status доступны всем")
    interval = poll_interval_seconds if poll_interval_seconds is not None else UPDATE_INTERVAL_SECONDS
    if has_channel_or_edit and app.job_queue:
        app.job_queue.run_repeating(job_publish_to_channel, interval=interval, first=10)
        mode = f"редактирование {len(edit_targets_startup)} сообщений" if edit_targets_startup else "обновление кеша"
        logger.info("Бот запущен. Команда /check — принудительный опрос. %s: каждые %s сек.", mode, interval)
    else:
        if has_channel_or_edit and not app.job_queue:
            logger.warning("JobQueue недоступен. Установите: pip install \"python-telegram-bot[job-queue]\". Публикация в канал отключена.")
        logger.info("Бот запущен. Команда /check — принудительный опрос.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
