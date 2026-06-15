"""Однократная синхронизация реакций из истории чата LeoMatch."""
import asyncio
import logging

from config import load_settings
from database.repository import ProfileRepository
from handlers.leomatch import LeoMatchCollector
from services.telegram_client import create_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


async def main() -> None:
    settings = load_settings()
    repo = ProfileRepository(settings.db_path, settings.media_dir.parent)
    repo.init()

    removed = repo.delete_all_reactions()
    print(f"Удалено старых реакций: {removed}")

    collector = LeoMatchCollector(settings, repo)
    async with create_client(settings) as app:
        added = await collector.sync_reactions_from_history(app)
        print(f"Готово: добавлено реакций — {added}")


if __name__ == "__main__":
    asyncio.run(main())
