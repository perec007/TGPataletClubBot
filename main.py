#!/usr/bin/env python3
"""
Telegram-бот мониторинга метеостанций.
Команда /check — принудительный опрос погоды в чат. Автопубликация в канал раз в минуту.
"""
import argparse
import asyncio
import logging
import sys

from bot import publish_weather_to_channel, run_bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


async def main_once(dry_run: bool = False) -> int:
    """Один прогон: собрать данные и опубликовать в канал (или dry-run)."""
    logger.info("Запуск публикации данных мониторинга...")
    try:
        ok = await publish_weather_to_channel(dry_run=dry_run)
        if ok:
            logger.info("Публикация выполнена успешно.")
            return 0
        logger.error("Публикация не выполнена.")
        return 1
    except Exception as e:
        logger.exception("Критическая ошибка: %s", e)
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Telegram-бот мониторинга метеостанций")
    parser.add_argument("--dry-run", action="store_true", help="Собрать данные и график, не отправлять в Telegram")
    parser.add_argument("--once", action="store_true", help="Один прогон в канал и выход (без бота)")
    args = parser.parse_args()

    if args.dry_run:
        exit_code = asyncio.run(main_once(dry_run=True))
        sys.exit(exit_code)
    if args.once:
        exit_code = asyncio.run(main_once(dry_run=False))
        sys.exit(exit_code)

    # Режим по умолчанию: бот с /check и периодическим обновлением погоды (UPDATE_INTERVAL_SECONDS из .env)
    try:
        run_bot()
    except Exception as e:
        logger.exception("Критическая ошибка: %s", e)
        sys.exit(1)
