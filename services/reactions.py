from enum import Enum

from pyrogram.types import Message

LIKE_EMOJIS = frozenset(
    "❤️ ❤ 💚 💛 💙 💜 🧡 💖 💗 💓 💕 😍 👍 🔥 ♥".split()
)
DISLIKE_EMOJIS = frozenset("👎 💔 🚫 ❌ 🙅".split())
DISLIKE_TEXTS = frozenset({"1", "👎", "💔", "нет", "no", "skip"})

# Тексты кнопок/меню LeoMatch — не реакции на анкету.
LEOMATCH_UI_TEXTS = frozenset(
    {
        "💌 / 📹",
        "💌",
        "📹",
        "1 🚀",
        "смотреть",
        "вернуться назад",
        "назад",
        "далее",
        "пропустить",
        "отмена",
    }
)
LEOMATCH_UI_PREFIXES = ("💌", "[photo]", "[video]", "[animation]", "[voice]", "[document]")


class ReactionType(str, Enum):
    LIKE = "like"
    DISLIKE = "dislike"
    COMMENT = "comment"
    MESSAGE = "message"


SERVICE_TEXT_MARKERS = (
    "/start",
    "/myprofile",
    "/language",
    "/complaint",
)


def is_service_message(text: str | None) -> bool:
    if not text:
        return False
    lowered = text.strip().lower()
    if lowered.startswith("/"):
        return True
    return any(marker in lowered for marker in SERVICE_TEXT_MARKERS)


def serialize_outgoing_message(message: Message) -> str | None:
    if message.text and message.text.strip():
        return message.text.strip()

    if message.sticker:
        parts = [message.sticker.emoji, message.sticker.set_name]
        label = " ".join(part for part in parts if part)
        return label or "[sticker]"

    if message.animation:
        return message.animation.emoji or "[animation]"

    if message.photo:
        return message.caption.strip() if message.caption else "[photo]"

    if message.video:
        return message.caption.strip() if message.caption else "[video]"

    if message.voice:
        return "[voice]"

    if message.document:
        return message.document.file_name or "[document]"

    return None


def is_leomatch_ui_text(text: str | None) -> bool:
    if not text:
        return False
    stripped = text.strip()
    if not stripped:
        return False
    lowered = stripped.casefold()
    if lowered in LEOMATCH_UI_TEXTS:
        return True
    if any(lowered.startswith(prefix.casefold()) for prefix in LEOMATCH_UI_PREFIXES):
        return True
    if stripped in {"1", "2", "3", "4", "5"}:
        return True
    return False


def should_save_reaction(message: Message) -> bool:
    if is_service_message(message.text):
        return False

    reaction_type = classify_outgoing_message(message)
    if reaction_type in {ReactionType.LIKE, ReactionType.DISLIKE}:
        return True

    if reaction_type != ReactionType.COMMENT:
        return False

    text = (serialize_outgoing_message(message) or "").strip()
    if not text or is_leomatch_ui_text(text):
        return False
    return len(text) >= 3


def classify_outgoing_message(message: Message) -> ReactionType:
    text = serialize_outgoing_message(message) or ""

    if message.sticker:
        sticker_reaction = detect_reaction_from_sticker(message.sticker)
        if sticker_reaction is not None:
            return sticker_reaction

    text_reaction = detect_reaction_from_text(text)
    if text_reaction is not None:
        return text_reaction

    if is_leomatch_ui_text(text):
        return ReactionType.MESSAGE

    if len(text.strip()) >= 3:
        return ReactionType.COMMENT

    return ReactionType.MESSAGE


def detect_reaction_from_text(text: str | None) -> ReactionType | None:
    if not text:
        return None

    stripped = text.strip()
    if not stripped:
        return None

    if stripped in DISLIKE_TEXTS or stripped.casefold() in DISLIKE_TEXTS:
        return ReactionType.DISLIKE

    compact = stripped.replace("\ufe0f", "")
    like_compact = {emoji.replace("\ufe0f", "") for emoji in LIKE_EMOJIS}
    dislike_compact = {emoji.replace("\ufe0f", "") for emoji in DISLIKE_EMOJIS}

    if compact in like_compact:
        return ReactionType.LIKE
    if compact in dislike_compact:
        return ReactionType.DISLIKE

    if any(emoji in stripped for emoji in LIKE_EMOJIS) and len(stripped) <= 6:
        return ReactionType.LIKE
    if any(emoji in stripped for emoji in DISLIKE_EMOJIS) and len(stripped) <= 6:
        return ReactionType.DISLIKE

    if is_leomatch_ui_text(stripped):
        return ReactionType.MESSAGE

    if len(stripped) >= 3:
        return ReactionType.COMMENT

    return None


def classify_callback_data(data: str | bytes | None) -> ReactionType | None:
    if not data:
        return None
    if isinstance(data, bytes):
        text = data.decode("utf-8", errors="ignore").strip()
    else:
        text = data.strip()
    if not text:
        return None

    lowered = text.casefold()
    if lowered in {"like", "yes", "heart", "love", "2", "l"}:
        return ReactionType.LIKE
    if lowered in {"dislike", "skip", "no", "1", "d", "nope"}:
        return ReactionType.DISLIKE

    if any(token in lowered for token in ("like", "heart", "love", "sympath")):
        return ReactionType.LIKE
    if any(token in lowered for token in ("dislike", "skip", "nope", "reject")):
        return ReactionType.DISLIKE

    return detect_reaction_from_text(text)


def callback_source_id(query_id: str) -> int:
    return -abs(hash(f"cb:{query_id}")) % (2**31 - 1)


def detect_reaction_from_sticker(sticker) -> ReactionType | None:
    if sticker is None:
        return None

    if sticker.emoji:
        reaction = detect_reaction_from_text(sticker.emoji)
        if reaction in {ReactionType.LIKE, ReactionType.DISLIKE}:
            return reaction

    alt = " ".join(
        part
        for part in (getattr(sticker, "emoji", None), getattr(sticker, "set_name", None))
        if part
    ).lower()

    if any(word in alt for word in ("heart", "love", "like", "серд")):
        return ReactionType.LIKE
    if any(word in alt for word in ("dislike", "thumb", "no", "dis")):
        return ReactionType.DISLIKE

    return None
