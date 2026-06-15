from pyrogram import Client, filters
from pyrogram.types import Message

from database.repository import ProfileRepository


def register_commands(app: Client, repo: ProfileRepository) -> None:
    @app.on_message(filters.me & filters.command("ping", prefixes="."))
    async def ping_handler(_: Client, message: Message) -> None:
        await message.edit("pong")

    @app.on_message(filters.me & filters.command("id", prefixes="."))
    async def id_handler(_: Client, message: Message) -> None:
        chat = message.chat
        reply = message.reply_to_message

        lines = [
            f"Chat ID: `{chat.id}`",
            f"Your ID: `{message.from_user.id}`",
        ]
        if reply:
            lines.append(f"Reply user ID: `{reply.from_user.id}`")
            if reply.forward_from:
                lines.append(f"Forward from ID: `{reply.forward_from.id}`")

        await message.edit("\n".join(lines))

    @app.on_message(filters.me & filters.command("stats", prefixes="."))
    async def stats_handler(_: Client, message: Message) -> None:
        stats = repo.get_stats()
        await message.edit(
            "LeoMatch статистика:\n"
            f"Анкет: {stats.profiles}\n"
            f"Лайков: {stats.likes}\n"
            f"Дизлайков: {stats.dislikes}\n"
            f"С комментарием: {stats.comments}\n"
            f"Взаимных: {stats.mutual_likes}"
        )