import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Settings:
    api_id: int
    api_hash: str
    session_name: str
    session_string: str | None
    leo_bot_username: str
    db_path: Path
    media_dir: Path
    base_dir: Path
    use_session_string: bool


def _load_use_session_string() -> bool:
    value = os.getenv("USE_SESSION_STRING", "true").strip().lower()
    return value not in {"0", "false", "no", "off"}


def load_settings() -> Settings:
    api_id = os.getenv("API_ID")
    api_hash = os.getenv("API_HASH")
    session_name = os.getenv("SESSION_NAME", "userbot")
    session_string = (os.getenv("SESSION_STRING") or "").strip() or None
    leo_bot_username = os.getenv("LEO_BOT_USERNAME", "leomatchbot")
    db_path = BASE_DIR / os.getenv("DB_PATH", "data/leomatch.db")
    media_dir = BASE_DIR / os.getenv("MEDIA_DIR", "data/media")

    if not api_id or not api_hash:
        raise ValueError(
            "Заполните API_ID и API_HASH в .env (скопируйте из .env.example)"
        )

    return Settings(
        api_id=int(api_id),
        api_hash=api_hash,
        session_name=session_name,
        session_string=session_string,
        leo_bot_username=leo_bot_username.lstrip("@"),
        db_path=db_path,
        media_dir=media_dir,
        base_dir=BASE_DIR,
        use_session_string=_load_use_session_string(),
    )
