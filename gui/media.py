import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from database.viewer_queries import MediaInfo, resolve_media_path

MEDIA_SIZE = 380
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".mkv", ".avi"}


@dataclass
class ResolvedMedia:
    media_type: str
    path: Path
    sort_order: int


def collect_resolved_media(
    media_items: list[MediaInfo],
    base_dir: Path,
) -> list[ResolvedMedia]:
    resolved: list[ResolvedMedia] = []
    for item in media_items:
        path = resolve_media_path(item.local_path, base_dir)
        if path is None:
            continue
        resolved.append(
            ResolvedMedia(
                media_type=item.media_type,
                path=path,
                sort_order=item.sort_order,
            )
        )
    return sorted(resolved, key=lambda item: item.sort_order)


def is_video_path(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS or path.suffix.lower() == ".mp4"


def load_display_image(path: Path, size: int = MEDIA_SIZE) -> Image.Image:
    if is_video_path(path):
        frame = _video_thumbnail(path)
        if frame is not None:
            return frame
        return _placeholder_image("Видео", size)

    with Image.open(path) as image:
        display = image.convert("RGBA" if image.mode in {"RGBA", "P"} else "RGB").copy()
    display.thumbnail((size, size), Image.Resampling.LANCZOS)
    return display


def _video_thumbnail(path: Path) -> Image.Image | None:
    try:
        import cv2
    except ImportError:
        return None

    capture = cv2.VideoCapture(str(path))
    try:
        success, frame = capture.read()
        if not success:
            return None
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(frame)
        image.thumbnail((MEDIA_SIZE, MEDIA_SIZE), Image.Resampling.LANCZOS)
        return image
    finally:
        capture.release()


def _placeholder_image(label: str, size: int) -> Image.Image:
    image = Image.new("RGB", (size, size), color=(35, 35, 40))
    return image


def open_media_externally(path: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(path)  # noqa: S606
        return
    if sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
        return
    subprocess.run(["xdg-open", str(path)], check=False)


def media_caption(item: ResolvedMedia, index: int, total: int) -> str:
    kind = "Видео" if item.media_type in {"video", "animation"} or is_video_path(item.path) else "Фото"
    return f"{kind} {index + 1} / {total}"
