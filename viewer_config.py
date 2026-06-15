import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class ViewerSettings:
    base_dir: Path
    db_path: Path
    media_dir: Path


def load_viewer_settings() -> ViewerSettings:
    db_path = BASE_DIR / os.getenv("DB_PATH", "data/leomatch.db")
    media_dir = BASE_DIR / os.getenv("MEDIA_DIR", "data/media")
    return ViewerSettings(
        base_dir=BASE_DIR,
        db_path=db_path,
        media_dir=media_dir,
    )
