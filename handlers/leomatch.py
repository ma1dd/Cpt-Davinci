import asyncio
import logging

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message

from config import Settings
from database.repository import ProfileRepository
from services.mutual_match import (
    build_identity_hash_from_text,
    is_mutual_match_message,
    looks_like_profile_text,
)
from services.leomatch_parser import parse_profile_text
from services.profile_storage import save_profile_from_messages
from services.reactions import (
    ReactionType,
    callback_source_id,
    classify_callback_data,
    classify_outgoing_message,
    serialize_outgoing_message,
    should_save_reaction,
)

logger = logging.getLogger(__name__)


class LeoMatchCollector:
    def __init__(self, settings: Settings, repo: ProfileRepository) -> None:
        self.settings = settings
        self.repo = repo
        self.leo_chat_id: int | None = None
        self._active_profile_id: int | None = None
        self._active_message_id: int | None = None

    async def resolve_leo_chat(self, client: Client) -> int:
        if self.leo_chat_id is not None:
            return self.leo_chat_id

        user = await client.get_users(self.settings.leo_bot_username)
        self.leo_chat_id = user.id
        logger.info(
            "LeoMatch bot: @%s (id=%s)",
            user.username or self.settings.leo_bot_username,
            user.id,
        )
        return self.leo_chat_id

    def _is_leo_chat(self, chat_id: int | None) -> bool:
        return chat_id is not None and chat_id == self.leo_chat_id

    async def bootstrap(self, client: Client) -> None:
        chat_id = await self.resolve_leo_chat(client)
        self._active_profile_id = self.repo.get_latest_profile_id(chat_id)
        logger.info(
            "Старт: активная анкета #%s, синхронизация истории в фоне",
            self._active_profile_id,
        )
        asyncio.create_task(self._background_sync(client))

    async def _background_sync(self, client: Client) -> None:
        try:
            added = await self.sync_reactions_from_history(client)
            mutual = await self.sync_mutual_likes_from_history(client)
            logger.info(
                "Фоновая синхронизация: реакций %s, взаимных %s",
                added,
                mutual,
            )
        except Exception:
            logger.exception("Ошибка фоновой синхронизации")

    async def sync_reactions_from_history(
        self,
        client: Client,
        *,
        limit: int = 3000,
    ) -> int:
        chat_id = await self.resolve_leo_chat(client)
        messages: list[Message] = []
        async for message in client.get_chat_history(chat_id, limit=limit):
            messages.append(message)
        messages.reverse()

        active: int | None = None
        added = 0
        for message in messages:
            if not message.outgoing and self._is_incoming_profile(message):
                profile_id = self.repo.get_profile_id_by_message(chat_id, message.id)
                if profile_id is not None:
                    active = profile_id
                continue

            is_outgoing = bool(
                message.outgoing
                or (message.from_user and message.from_user.is_self)
            )
            if not is_outgoing:
                continue

            if self._save_outgoing_reaction(message, active, allow_fallback=False):
                added += 1

        if self._active_profile_id is None:
            self._active_profile_id = self.repo.get_latest_profile_id(chat_id)
        return added

    async def sync_mutual_likes_from_history(
        self,
        client: Client,
        *,
        limit: int = 3000,
    ) -> int:
        chat_id = await self.resolve_leo_chat(client)
        messages: list[Message] = []
        async for message in client.get_chat_history(chat_id, limit=limit):
            messages.append(message)
        messages.reverse()

        marked = 0
        for index, message in enumerate(messages):
            if message.outgoing:
                continue
            if not self._is_mutual_match_message(message):
                continue
            prev_message = None
            for prev in reversed(messages[:index]):
                if prev.outgoing:
                    continue
                text = (prev.caption or prev.text or "").strip()
                if text and looks_like_profile_text(text):
                    prev_message = prev
                    break
            if prev_message is None:
                continue

            profile_text = (prev_message.caption or prev_message.text or "").strip()
            parsed = parse_profile_text(profile_text)
            content_hash = build_identity_hash_from_text(profile_text)
            profile_id = self.repo.find_profile_id_by_identity(
                name=parsed.name,
                age=parsed.age,
                content_hash=content_hash,
            )
            if profile_id is None and self._is_incoming_profile(prev_message):
                profile_id = await self._save_profile(client, prev_message)
            if profile_id is None:
                continue
            self.repo.set_mutual_like(profile_id)
            marked += 1
        return marked

    async def _resolve_active_from_chat(
        self,
        client: Client,
        before_message_id: int,
    ) -> int | None:
        chat_id = await self.resolve_leo_chat(client)
        async for message in client.get_chat_history(chat_id, limit=50):
            if message.id >= before_message_id:
                continue
            if message.outgoing:
                continue
            if not self._is_incoming_profile(message):
                continue
            profile_id = self.repo.get_profile_id_by_message(chat_id, message.id)
            if profile_id is None:
                profile_id = await self._save_profile(client, message)
            if profile_id is not None:
                self._active_profile_id = profile_id
                return profile_id
        return self._active_profile_id

    def _is_mutual_match_message(self, message: Message) -> bool:
        text = (message.text or message.caption or "").strip()
        return is_mutual_match_message(text)

    async def _find_preceding_profile_message(
        self,
        client: Client,
        message: Message,
    ) -> Message | None:
        if message.reply_to_message:
            text = (message.reply_to_message.caption or message.reply_to_message.text or "").strip()
            if looks_like_profile_text(text):
                return message.reply_to_message

        chat_id = message.chat.id
        async for item in client.get_chat_history(chat_id, limit=15):
            if item.id >= message.id:
                continue
            if item.outgoing:
                continue
            text = (item.caption or item.text or "").strip()
            if not text or is_mutual_match_message(text):
                continue
            if looks_like_profile_text(text):
                return item
        return None

    async def _handle_mutual_match(self, client: Client, message: Message) -> None:
        prev_message = await self._find_preceding_profile_message(client, message)
        if prev_message is None:
            return

        profile_text = (prev_message.caption or prev_message.text or "").strip()
        parsed = parse_profile_text(profile_text)
        content_hash = build_identity_hash_from_text(profile_text)
        profile_id = self.repo.find_profile_id_by_identity(
            name=parsed.name,
            age=parsed.age,
            content_hash=content_hash,
        )
        if profile_id is None and self._is_profile_message(prev_message):
            profile_id = await self._save_profile(client, prev_message)
        if profile_id is None:
            return

        self.repo.set_mutual_like(profile_id)
        self._active_profile_id = profile_id
        logger.info("Взаимный лайк -> анкета #%s", profile_id)

    def _is_profile_message(self, message: Message) -> bool:
        if not (message.photo or message.video or message.animation):
            return False
        caption = (message.caption or message.text or "").strip()
        return not caption.startswith("/")

    def _is_incoming_profile(self, message: Message) -> bool:
        caption = (message.caption or message.text or "").strip()
        if caption.startswith("/"):
            return False
        if message.photo or message.video or message.animation:
            return True
        return looks_like_profile_text(caption)

    def _resolve_profile_for_outgoing(
        self,
        message: Message,
        active: int | None,
        *,
        allow_fallback: bool = False,
    ) -> int | None:
        chat_id = message.chat.id
        if message.reply_to_message:
            replied_id = self.repo.get_profile_id_by_message(
                chat_id,
                message.reply_to_message.id,
            )
            if replied_id is not None:
                return replied_id

        if active is not None:
            return active

        if not allow_fallback:
            return None

        return self.repo.get_latest_profile_id(chat_id)

    def _save_outgoing_reaction(
        self,
        message: Message,
        active: int | None,
        *,
        allow_fallback: bool = False,
    ) -> bool:
        if message.text and message.text.strip().startswith("/"):
            return False
        if not should_save_reaction(message):
            return False
        if self.repo.reaction_source_exists(message.id):
            return False

        profile_id = self._resolve_profile_for_outgoing(
            message,
            active,
            allow_fallback=allow_fallback,
        )
        if profile_id is None:
            logger.debug(
                "Реакция msg_id=%s не привязана: нет активной анкеты",
                message.id,
            )
            return False

        payload = serialize_outgoing_message(message) or "[сообщение]"
        reaction_type = classify_outgoing_message(message)
        self.repo.add_reaction(
            profile_id=profile_id,
            reaction_type=reaction_type.value,
            comment_text=payload,
            source_message_id=message.id,
        )
        logger.info(
            "Реакция -> анкета #%s: %s",
            profile_id,
            payload[:80],
        )
        return True

    async def _save_callback_reaction(self, client: Client, query: CallbackQuery) -> bool:
        message = query.message
        if message is None:
            return False

        data_raw = query.data
        if isinstance(data_raw, bytes):
            data = data_raw.decode("utf-8", errors="ignore")
        else:
            data = data_raw or ""

        reaction_type = classify_callback_data(data_raw)
        if reaction_type not in {ReactionType.LIKE, ReactionType.DISLIKE}:
            return False

        source_id = callback_source_id(str(query.id))
        if self.repo.reaction_source_exists(source_id):
            return False

        chat_id = message.chat.id
        profile_id = self.repo.get_profile_id_by_message(chat_id, message.id)
        if profile_id is None:
            profile_id = await self._save_profile(client, message)
        if profile_id is None:
            return False

        label = data.strip() or ("❤️" if reaction_type == ReactionType.LIKE else "👎")
        self.repo.add_reaction(
            profile_id=profile_id,
            reaction_type=reaction_type.value,
            comment_text=label,
            callback_data=data,
            source_message_id=source_id,
        )
        self._active_profile_id = profile_id
        logger.info(
            "Кнопка -> анкета #%s: %s (%s)",
            profile_id,
            label,
            data[:40],
        )
        return True

    async def _collect_messages(self, client: Client, message: Message) -> list[Message]:
        if message.media_group_id:
            return await client.get_media_group(message.chat.id, message.id)
        return [message]

    async def _save_profile(self, client: Client, message: Message) -> int | None:
        messages = await self._collect_messages(client, message)
        profile_id = await save_profile_from_messages(
            client,
            self.repo,
            messages,
            self.settings.media_dir,
        )
        if profile_id is not None:
            self._active_profile_id = profile_id
            self._active_message_id = messages[0].id
            logger.info(
                "Активная анкета #%s (msg_id=%s)",
                profile_id,
                messages[0].id,
            )
        return profile_id

    def register(self, app: Client) -> None:
        @app.on_message(filters.private, group=1)
        async def leo_message_handler(client: Client, message: Message) -> None:
            await self.resolve_leo_chat(client)
            if not self._is_leo_chat(message.chat.id):
                return

            is_own = bool(
                message.from_user and message.from_user.is_self
            ) or bool(message.outgoing)

            if is_own:
                active = self._active_profile_id
                if not (
                    active
                    and self._active_message_id
                    and message.id > self._active_message_id
                ):
                    active = await self._resolve_active_from_chat(client, message.id)
                self._save_outgoing_reaction(
                    message,
                    active,
                    allow_fallback=False,
                )
                return

            if self._is_mutual_match_message(message):
                await self._handle_mutual_match(client, message)
                return

            if not self._is_incoming_profile(message):
                return

            await self._save_profile(client, message)

        @app.on_callback_query(group=1)
        async def leo_callback_handler(_client: Client, query: CallbackQuery) -> None:
            if not query.from_user or not query.from_user.is_self:
                return
            if query.message is None:
                return

            await self.resolve_leo_chat(_client)
            if not self._is_leo_chat(query.message.chat.id):
                return

            await self._save_callback_reaction(_client, query)


def register_leomatch(
    app: Client,
    settings: Settings,
    repo: ProfileRepository,
) -> LeoMatchCollector:
    collector = LeoMatchCollector(settings, repo)
    collector.register(app)
    return collector
