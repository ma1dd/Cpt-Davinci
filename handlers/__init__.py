from pyrogram import Client

from config import Settings
from database.repository import ProfileRepository

from .commands import register_commands
from .leomatch import LeoMatchCollector, register_leomatch


def register_handlers(
    app: Client,
    settings: Settings,
    repo: ProfileRepository,
) -> LeoMatchCollector:
    register_commands(app, repo)
    return register_leomatch(app, settings, repo)