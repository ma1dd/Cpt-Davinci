"""
Экспорт или пересоздание сессии Telegram.

  py export_session.py          — экспорт SESSION_STRING из текущей сессии
  py export_session.py --fresh  — удалить старую сессию и войти по телефону
"""
import argparse
import asyncio
import logging

from config import load_settings
from services.telegram_client import create_client, remove_session_files

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Экспорт / пересоздание сессии Telegram")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Удалить dvpro.session и войти по номеру телефона заново",
    )
    args = parser.parse_args()

    settings = load_settings()
    use_string = not args.fresh

    if args.fresh:
        removed = remove_session_files(settings)
        if removed:
            logger.info("Удалены файлы: %s", ", ".join(p.name for p in removed))
        logger.info(
            "Вход по телефону. Zapret/Warp должны быть включены. "
            "SESSION_STRING из .env не используется."
        )

    app = create_client(settings, use_session_string=use_string and settings.use_session_string)

    async with app:
        session_string = await app.export_session_string()
        me = await app.get_me()

    print("\n" + "=" * 60)
    print(f"Аккаунт: {me.first_name} (@{me.username or 'без username'})")
    print("=" * 60)
    print("\nSESSION_STRING (вставь в .env):\n")
    print(session_string)
    print("\n" + "=" * 60)
    print("USE_SESSION_STRING=true")
    logger.info("Готово. Не публикуй эту строку — это полный доступ к аккаунту.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Отменено")
