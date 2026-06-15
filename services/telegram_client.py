from pathlib import Path

from pyrogram import Client

from config import Settings


def build_client_kwargs(
    settings: Settings,
    *,
    use_session_string: bool = True,
) -> dict:
    kwargs: dict = {
        "name": settings.session_name,
        "api_id": settings.api_id,
        "api_hash": settings.api_hash,
        "workdir": ".",
    }
    if use_session_string and settings.use_session_string and settings.session_string:
        kwargs["session_string"] = settings.session_string.strip()
    return kwargs


def create_client(settings: Settings, *, use_session_string: bool = True) -> Client:
    return Client(**build_client_kwargs(settings, use_session_string=use_session_string))


def session_file_path(settings: Settings) -> Path:
    return settings.base_dir / f"{settings.session_name}.session"


def remove_session_files(settings: Settings) -> list[Path]:
    removed: list[Path] = []
    for pattern in (f"{settings.session_name}.session", f"{settings.session_name}.session-journal"):
        path = settings.base_dir / pattern
        if path.is_file():
            path.unlink()
            removed.append(path)
    return removed
