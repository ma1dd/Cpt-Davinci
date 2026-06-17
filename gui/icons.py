from pathlib import Path

import customtkinter as ctk
from PIL import Image

ICON_DIR = Path(__file__).resolve().parent / "etc"
DISPLAY_SIZE = 36


def _load_pil(path: Path, size: int) -> Image.Image:
    with Image.open(path) as image:
        frame = image.convert("RGBA")
    frame.thumbnail((size, size), Image.Resampling.LANCZOS)
    return frame


def load_reaction_icons(size: int = DISPLAY_SIZE) -> dict[str, ctk.CTkImage]:
    mapping = {
        "none": ICON_DIR / "not.png",
        "like": ICON_DIR / "like.png",
        "dislike": ICON_DIR / "dislike.webp",
        "comment": ICON_DIR / "message.png",
        "mutual": ICON_DIR / "like.png",
    }
    icons: dict[str, ctk.CTkImage] = {}
    for key, path in mapping.items():
        if not path.is_file():
            continue
        pil = _load_pil(path, size)
        icons[key] = ctk.CTkImage(light_image=pil, dark_image=pil, size=(size, size))
    return icons


def reaction_icon_key(reaction_type: str, comment_text: str | None = None) -> str:
    if reaction_type == "like":
        return "like"
    if reaction_type == "dislike":
        return "dislike"
    if reaction_type == "mutual":
        return "mutual"
    text = (comment_text or "").strip()
    if text in {"❤️", "❤", "👎"}:
        return "like" if "❤" in text else "dislike"
    return "comment"
