import asyncio
import logging

from config import load_settings
from database.repository import ProfileRepository
from handlers import register_handlers
from services.telegram_client import create_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


def create_app(settings, repo: ProfileRepository):
    app = create_client(settings)
    collector = register_handlers(app, settings, repo)
    return app, collector


async def main() -> None:
    settings = load_settings()
    repo = ProfileRepository(settings.db_path, settings.media_dir.parent)
    repo.init()
    settings.media_dir.mkdir(parents=True, exist_ok=True)

    if settings.use_session_string and settings.session_string:
        logger.info("Сессия: SESSION_STRING из .env")
    else:
        logger.info("Сессия: файл %s.session", settings.session_name)

    app, collector = create_app(settings, repo)

    async with app:
        me = await app.get_me()
        logger.info("Userbot запущен: %s (@%s)", me.first_name, me.username or "без username")
        logger.info("База данных: %s", settings.db_path)
        logger.info("Медиа: %s", settings.media_dir)
        await collector.bootstrap(app)
        await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Остановлено пользователем")
