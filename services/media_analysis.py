"""Сжатие фото, детекция лиц, Ч/Б-фильтра и телефона в кадре."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

_FACE_FRONT = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)
_FACE_PROFILE = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_profileface.xml"
)

PHOTO_TYPES = frozenset({"photo"})
VIDEO_TYPES = frozenset({"video", "animation"})


@dataclass(frozen=True)
class PhotoAnalysis:
    face_count: int
    is_bw: bool
    has_phone: bool


def compress_image_file(path: Path, *, max_size: int = 800, quality: int = 70) -> None:
    if not path.is_file():
        return
    if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
        return
    try:
        with Image.open(path) as img:
            img = img.convert("RGB")
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            img.save(path, format="JPEG", quality=quality, optimize=True)
    except OSError:
        return


def _load_bgr(path: Path) -> np.ndarray | None:
    try:
        data = path.read_bytes()
        array = np.frombuffer(data, dtype=np.uint8)
        image = cv2.imdecode(array, cv2.IMREAD_COLOR)
        return image
    except OSError:
        return None


def count_faces_in_image(path: Path) -> int:
    image = _load_bgr(path)
    if image is None:
        return 0

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)
    height, width = gray.shape[:2]
    min_size = max(20, min(width, height) // 12)

    best = 0
    for cascade in (_FACE_FRONT, _FACE_PROFILE):
        if cascade.empty():
            continue
        for neighbors in (6, 4, 3):
            faces = cascade.detectMultiScale(
                gray,
                scaleFactor=1.08,
                minNeighbors=neighbors,
                minSize=(min_size, min_size),
            )
            best = max(best, len(faces))
            if best > 0:
                return best
    return best


def is_grayscale_filter(path: Path) -> bool:
    """Строгая проверка именно Ч/Б-фильтра, а не просто тусклого фото."""
    image = _load_bgr(path)
    if image is None:
        return False

    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    a_std = float(np.std(lab[:, :, 1]))
    b_std = float(np.std(lab[:, :, 2]))
    if a_std >= 7 or b_std >= 7:
        return False

    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    sat_mean = float(np.mean(hsv[:, :, 1]))
    if sat_mean >= 18:
        return False

    b, g, r = cv2.split(image)
    rg = float(np.corrcoef(r.flatten(), g.flatten())[0, 1])
    rb = float(np.corrcoef(r.flatten(), b.flatten())[0, 1])
    return rg > 0.97 and rb > 0.97


def _roi_edge_ratio(gray: np.ndarray, x: int, y: int, w: int, h: int) -> float:
    roi = gray[y : y + h, x : x + w]
    if roi.size == 0:
        return 0.0
    edges = cv2.Canny(roi, 60, 150)
    return float(np.count_nonzero(edges)) / roi.size


def _match_phone_candidate(
    gray: np.ndarray,
    x: int,
    y: int,
    w: int,
    h: int,
) -> bool:
    img_h, img_w = gray.shape[:2]
    if w < 24 or h < 55:
        return False

    area_ratio = (w * h) / (img_w * img_h)
    if not (0.008 < area_ratio < 0.16):
        return False

    aspect = w / h
    cy = (y + h / 2) / img_h
    cx = (x + w / 2) / img_w

    roi = gray[y : y + h, x : x + w]
    if roi.size == 0:
        return False
    mean_brightness = float(np.mean(roi))
    if mean_brightness < 25 or mean_brightness > 220:
        return False

    edge_ratio = _roi_edge_ratio(gray, x, y, w, h)

    if cy > 0.75 and aspect > 0.55:
        return False

    # Телефон в нижней части кадра (зеркальное селфи, рука с телефоном).
    if (
        0.012 <= area_ratio <= 0.025
        and 0.38 <= aspect <= 0.55
        and 0.58 <= cy <= 0.78
        and 0.25 <= cx <= 0.82
        and h >= 70
        and 0.22 <= edge_ratio <= 0.28
    ):
        return True

    # Телефон на уровне пояса / груди, текстурированный чехол.
    if (
        0.04 <= area_ratio <= 0.10
        and 0.42 <= aspect <= 0.55
        and 0.45 <= cy <= 0.65
        and 0.11 <= edge_ratio <= 0.20
    ):
        return True

    # Крупный телефон перед лицом (верхняя часть кадра).
    if (
        0.035 <= area_ratio <= 0.12
        and 0.42 <= aspect <= 0.56
        and 0.12 <= cy <= 0.35
        and 0.04 <= edge_ratio <= 0.075
    ):
        return True

    # Телефон перед лицом (средний размер).
    if 0.012 <= area_ratio <= 0.034 and 0.34 < aspect < 0.56 and 0.12 <= cy <= 0.50:
        min_edge = 0.08 if cy > 0.38 else 0.035
        return min_edge <= edge_ratio <= 0.095

    # Маленький телефон в кадре.
    if (
        0.008 <= area_ratio < 0.012
        and 0.33 < aspect < 0.52
        and 0.28 <= cy <= 0.48
        and 0.045 <= edge_ratio <= 0.095
    ):
        return True

    return False


def _scan_gray_for_phone(gray: np.ndarray, *, morph_close: bool) -> bool:
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    canny_pairs = ((55, 140), (40, 120), (25, 90))

    for low, high in canny_pairs:
        edges = cv2.Canny(blur, low, high)
        if morph_close:
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
            edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if _match_phone_candidate(gray, x, y, w, h):
                return True
    return False


def detect_phone_in_image(path: Path) -> bool:
    """Телефон именно в кадре (зеркальное селфи и т.п.), не «снято на телефон»."""
    image = _load_bgr(path)
    if image is None:
        return False

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if _scan_gray_for_phone(gray, morph_close=False):
        return True
    # Morph только если на «сырых» контурах ничего не нашли (мелкий телефон).
    return _scan_gray_for_phone(gray, morph_close=True)


def count_faces_in_video_first_frame(path: Path) -> int:
    capture = cv2.VideoCapture(str(path))
    try:
        ok, frame = capture.read()
        if not ok or frame is None:
            return 0
        tmp = path.with_suffix(".frame.jpg")
        cv2.imwrite(str(tmp), frame)
        try:
            return count_faces_in_image(tmp)
        finally:
            tmp.unlink(missing_ok=True)
    finally:
        capture.release()


def analyze_photo_file(path: Path) -> PhotoAnalysis:
    return PhotoAnalysis(
        face_count=count_faces_in_image(path),
        is_bw=is_grayscale_filter(path),
        has_phone=detect_phone_in_image(path),
    )


def analyze_media_file(path: Path, media_type: str) -> PhotoAnalysis:
    if media_type in PHOTO_TYPES:
        return analyze_photo_file(path)
    if media_type in VIDEO_TYPES:
        return PhotoAnalysis(
            face_count=count_faces_in_video_first_frame(path),
            is_bw=False,
            has_phone=False,
        )
    return PhotoAnalysis(face_count=0, is_bw=False, has_phone=False)
