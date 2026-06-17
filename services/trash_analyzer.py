"""Индекс мусорности анкет LeoMatch."""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field

import emoji

from services.leomatch_parser import extract_bio_text
from services.profile_text_analysis import extract_claimed_ages

TRASH_ANALYSIS_VERSION = 7

SOCIAL_LINK_RE = re.compile(
    r"(?:"
    r"instagram\.com/\S+|instagr\.am/\S+|"
    r"\b(?:instagram|insta|inst|ig|инстаграм|инста|инст)\b|"
    r"inst\s*[:@]|"
    r"@\w{2,}"
    r")",
    re.IGNORECASE,
)

# Служебные слова — не учитываются в повторах.
STOP_WORDS = frozenset(
    {
        "я", "ты", "он", "она", "оно", "мы", "вы", "они", "меня", "тебя", "тебе",
        "мне", "мой", "моя", "моё", "мои", "твой", "твоя", "твоё", "твои", "его",
        "её", "их", "ему", "ей", "им", "нам", "вам", "себя", "себе", "собой",
        "и", "в", "во", "на", "над", "под", "с", "со", "к", "ко", "по", "о", "об",
        "от", "до", "из", "за", "для", "при", "про", "без", "у", "а", "но", "или",
        "ли", "же", "бы", "не", "ни", "что", "как", "так", "это", "этот", "эта",
        "эти", "тот", "та", "те", "тут", "там", "здесь", "туда", "сюда", "где",
        "когда", "если", "чтобы", "чтоб", "то", "всё", "все", "всего", "ещё", "уже",
        "очень", "просто", "тоже", "также", "только", "ещё", "да", "нет", "ну",
        "вот", "ещё", "был", "была", "было", "были", "есть", "буду", "будет",
        "the", "a", "an", "and", "or", "to", "in", "on", "at", "of", "for", "is",
        "am", "are", "was", "were", "be", "my", "me", "you", "your", "i", "we",
        # Рядовые слова — не считаются повторами между предложениями.
        "всегда", "часто", "иногда", "никогда", "обычно", "иногда", "ещё",
        "тоже", "также", "потому", "поэтому", "просто", "очень", "может",
        "буду", "будет", "могу", "люблю", "любить", "новое", "новый", "новая",
    }
)

MOBILE_GAME_PATTERNS = (
    r"standoff|стэндоф|stndoff",
    r"brawl\s*stars|бравл\s*старс|бс\b",
    r"мобайл\s*легенд|mobile\s*legends|млбб|mlbb",
    r"играю\s+в\s+мобильные\s+игры|мобильные\s+игры",
    r"го\s+в\s+бс|го\s+в\s+млбб",
)

HOBBY_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bрисую\b", "рисую"),
    (r"\bчитаю\b", "читаю"),
    (r"\bпою\b", "пою"),
    (r"\bтанцую\b", "танцую"),
    (r"\bготовлю\b", "готовлю"),
    (r"\bспорт\b", "спорт"),
    (r"\bфотограф", "фотограф"),
    (r"\bпутешеств", "путешеств"),
    (r"\bкомикс", "комикс"),
    (r"\bфест", "фест"),
    (r"\bконцерт", "концерт"),
    (r"\bиграю\s+на\s+\w+", "играю на"),
    (r"\bхобби\b", "хобби"),
    (r"\bувлечения\b", "увлечения"),
    (r"\bувлекаюсь\b", "увлекаюсь"),
    (r"\bзанимаюсь\b", "занимаюсь"),
    (r"\bколлекци", "коллекци"),
    (r"\bвязан", "вязан"),
    (r"\bшью\b", "шью"),
    (r"\bбегаю\b", "бегаю"),
    (r"\bйога\b", "йога"),
    (r"\bмузык", "музык"),
    (r"\bкино\b", "кино"),
    (r"\bсериал", "сериал"),
)


@dataclass
class TrashTag:
    label: str
    delta: float
    heavy: bool = False

    def display(self) -> str:
        sign = "+" if self.delta >= 0 else "−"
        value = abs(self.delta)
        if value == int(value):
            text = f"{int(value)}%"
        else:
            text = f"{value:.1f}%"
        return f"{sign}{text} {self.label}"


@dataclass
class TrashAnalysisResult:
    score: float
    label: str
    tags: list[TrashTag] = field(default_factory=list)
    auto_100: bool = False

    def tags_json(self) -> str:
        return json.dumps(
            [asdict(tag) for tag in self.tags],
            ensure_ascii=False,
        )

    @classmethod
    def from_json(
        cls,
        score: float | None,
        label: str | None,
        tags_json: str | None,
    ) -> TrashAnalysisResult:
        if score is None:
            return cls(score=0, label="", tags=[], auto_100=False)
        tags: list[TrashTag] = []
        if tags_json:
            try:
                raw = json.loads(tags_json)
                tags = [TrashTag(**item) for item in raw]
            except (json.JSONDecodeError, TypeError):
                pass
        return cls(
            score=score,
            label=label or classify_trash_score(score),
            tags=tags,
            auto_100=any(t.delta >= 100 for t in tags),
        )


def classify_trash_score(score: float) -> str:
    if score <= 20:
        return "✨ Идеально"
    if score <= 40:
        return "👍 Нормально"
    if score <= 60:
        return "🤔 Приемлемо"
    if score <= 80:
        return "😬 Сомнительно"
    if score <= 100:
        return "🗑 Мусор"
    if score <= 200:
        return "🚮 Супер‑мусор"
    if score <= 300:
        return "☣️ Мега‑мусор"
    if score <= 400:
        return "💀 Ультра‑мусор"
    if score <= 500:
        return "🔥 Гипер‑мусор"
    if score <= 1000:
        return "⚰️ Абсолютный мусор"
    return "😈 Мусорная сингулярность"


def format_trash_percent(score: float | None) -> str:
    if score is None:
        return "—"
    if score == int(score):
        return f"{int(score)}%"
    return f"{score:.0f}%"


def under_18_penalty(age: int) -> float:
    if age >= 18:
        return 0.0
    years_below = 18 - age
    return 10 * years_below * (years_below + 1) / 2


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"[.!?\n]+", text or "")
    return [part.strip().casefold() for part in parts if part.strip()]


TEXT_EMOJI_RE = re.compile(r"(?:<3|</3|:\)|:\(|;\)|x[dD]|=\))")


def count_bio_emojis(raw: str) -> int:
    return emoji.emoji_count(raw) + len(TEXT_EMOJI_RE.findall(raw))


class TrashAnalyzer:
    HEAVY_RULES: tuple[tuple[str, float, str], ...] = (
        (r"(покатай|покататься|катать|машину|на\s+машин)", 25, "Покатай / машину"),
        (r"(бан|забанен)\b.*(пиши|пешите|первый|первые)", 33, "Бан + «пишите первые»"),
        (r"пишите\s+первые", 33, "Пишите первые"),
        (r"(на\s*один\s*раз|интрижк|без\s*обязательств|fwb|ons|ничего\s+серь[её]зного|секс|чисто\s+потрах)", 40, "Разовое / интрижка / секс"),
        (r"(ищу\s+на\s+время|временно|времянк)", 30, "Ищу на время"),
        (r"(только\s+дружб[ау]|не\s+для\s+отношений)", 20, "Только дружба"),
        (r"хотелось\s+бы\s+найти\s+друзей", 60, "Хотелось бы найти друзей"),
        (r"(wlw|влв|women\s*love\s*women)", 33, "WLW"),
        (r"ищу\s+интересного\s+собеседника", 23, "Ищу интересного собеседника"),
        (r"с\s+которым\s+не\s+будет\s+скучно", 30, "«Не будет скучно»"),
        (r"ищу\s+комфортного\s+общения", 28, "Ищу комфортного общения"),
        (r"позовите\s+за\s+свидание", 50, "Позовите за свидание"),
        (r"p\.\s*s\.", 20, "P.S."),
        (r"(овен|телец|близнецы|рак|лев|дева|весы|скорпион|стрелец|козерог|водолей|рыбы|♈|♉|♊|♋|♌|♍|♎|♏|♐|♑|♒|♓)", 20, "Знак зодиака"),
        (r"(он/его|она/её|они/их|местоимения)", 33, "Местоимения"),
        (r"\b(entp|infp|intj|infj|estj|istj|enfp|esfp|istp|estp|enfj|isfj|esfj|intp|isfp|entj)\b", 7, "MBTI"),
        (r"молюсь\s+на\s+(вас|тебя)", 40, "«Молюсь на вас»"),
        (r"(?:ищу|хочу|нужен|нужна|подавай)\s+.*(брюнет|блондин|рыж|кареглаз|голубоглаз|высок|низк)", 25, "Требования к внешности"),
        (r"(?:рост|ищу)\s*(?:от|выше|не\s*(?:менее|меньше))\s*\d{3}|\d{3}\+", 20, "Требования к росту"),
    )

    MEDIUM_RULES: tuple[tuple[str, float, str], ...] = (
        (r"ищу\s+(друга|подружку)(?!.*может\s+отношения)", 25, "Ищу друга/подружку"),
        (r"ищу\s+компанию", 15, "Ищу компанию"),
        (r"(не\s+знаю\s*,?\s*что\s+я\s+тут\s+делаю|ну\s+ладно)", 15, "«Не знаю, что тут делаю»"),
        (r"состою\s+во\s+многих\s+фд", 4, "«Состою во многих фд»"),
    )

    LIGHT_RULES: tuple[tuple[str, float, str], ...] = (
        (r"\bмимо\b", 10, "«мимо»"),
    )

    def analyze(
        self,
        *,
        text: str,
        nickname: str = "",
        photo_face_counts: list[int] | None = None,
        photo_bw_flags: list[bool] | None = None,
        photo_phone_flags: list[bool] | None = None,
        photo_count: int = 0,
        has_video: bool = False,
        profile_age: int | None = None,
        text_age: int | None = None,
        word_count: int | None = None,
    ) -> TrashAnalysisResult:
        raw = (text or "").strip()
        bio = extract_bio_text(raw)
        bio_text = (bio or "").strip()
        has_description = bool(bio_text)
        bio_chars = len(bio_text)
        clean = bio_text.casefold() if has_description else ""
        words = re.findall(r"[а-яёa-z]+", clean) if has_description else []
        wc = word_count if word_count is not None else len(words)
        face_counts = list(photo_face_counts or [])
        bw_flags = list(photo_bw_flags or [])
        phone_flags = list(photo_phone_flags or [])
        tags: list[TrashTag] = []
        heavy_flags = 0

        def add(delta: float, label: str, *, heavy: bool = False) -> None:
            nonlocal heavy_flags
            tags.append(TrashTag(label=label, delta=delta, heavy=heavy))
            if heavy:
                heavy_flags += 1

        if self._unreadable_nick(nickname):
            add(100, "Нечитаемый ник", heavy=True)

        for _, weight, label in self._collect_auto_flags(
            clean=clean,
            raw=raw,
            word_count=wc,
            photo_count=photo_count,
            has_description=has_description,
            has_video=has_video,
        ):
            add(weight, label, heavy=True)

        if not has_description:
            add(100, "Нет описания", heavy=True)
        elif bio_chars < 10:
            add(25, f"Описание < 10 символов ({bio_chars})", heavy=False)

        if has_video:
            add(100, "Видео в анкете", heavy=True)
        else:
            if photo_count == 1:
                add(50, "1 фотография", heavy=False)
            elif photo_count == 2:
                add(-20, "2 фотографии", heavy=False)
            elif photo_count == 3:
                add(-33, "3 фотографии", heavy=False)
            elif photo_count >= 4:
                add(-33, f"{photo_count} фотографий", heavy=False)

            if photo_count > 0 and face_counts:
                no_face_count = sum(1 for c in face_counts if c == 0)
                has_face_count = sum(1 for c in face_counts if c > 0)

                if no_face_count == photo_count:
                    base = 40 + 15 * photo_count
                    if not has_description:
                        base += 25
                    elif wc <= 10:
                        base += 10
                    add(base, f"Лиц не найдено ({photo_count} фото)", heavy=True)
                elif photo_count >= 3 and no_face_count > 0 and has_face_count > 0:
                    add(-12, "Мем / без лица среди фото", heavy=False)

                if photo_count > 1 and all(c == 1 for c in face_counts):
                    add(50, "Все фото — селфи", heavy=True)

            for index, is_bw in enumerate(bw_flags):
                if is_bw:
                    add(23, f"Ч/Б фильтр (фото {index + 1})", heavy=True)

            for index, has_phone in enumerate(phone_flags):
                if has_phone:
                    add(35, f"Телефон в кадре (фото {index + 1})", heavy=True)

        if has_description:
            has_hz_combo = bool(re.search(r"\bхз\b", clean)) and wc < 10
            if has_hz_combo:
                add(70, f"«хз» при < 10 слов ({wc})", heavy=True)
            elif wc <= 10:
                add(25, f"≤10 слов ({wc})", heavy=False)
            elif wc <= 20:
                add(-5, f"11–20 слов ({wc})", heavy=False)
            elif wc <= 30:
                add(-10, f"21–30 слов ({wc})", heavy=False)
            elif wc <= 40:
                add(-15, f"31–40 слов ({wc})", heavy=False)
            elif wc <= 50:
                add(-20, f"41–50 слов ({wc})", heavy=False)
            elif wc <= 60:
                add(-25, f"51–60 слов ({wc})", heavy=False)
            elif wc <= 100:
                pass
            else:
                add(-5, f">100 слов ({wc})", heavy=False)

            if re.search(r"\bхз\b", clean) and not has_hz_combo:
                add(11, "«хз»", heavy=True)

            for pattern, weight, label in self.HEAVY_RULES:
                if re.search(pattern, clean, re.IGNORECASE):
                    add(weight, label, heavy=True)

            for pattern in MOBILE_GAME_PATTERNS:
                if re.search(pattern, clean, re.IGNORECASE):
                    add(30, "Мобильные игры", heavy=True)
                    break

            for pattern, weight, label in self.MEDIUM_RULES:
                if re.search(pattern, clean, re.IGNORECASE):
                    add(weight, label, heavy=False)

            for pattern, weight, label in self.LIGHT_RULES:
                if re.search(pattern, clean, re.IGNORECASE):
                    add(weight, label, heavy=False)

            self._apply_fandom_music_heuristics(clean, add)
            self._apply_positive_bonuses(clean, raw, add)
            self._apply_hobby_bonus(clean, add)

            if check_age := text_age:
                if profile_age is not None and check_age < profile_age:
                    add(10, "Возраст в тексте < профильного", heavy=False)

            if re.search(r"\(\-\d+\-\)", raw):
                add(10, "Возраст (-17-)", heavy=False)

            self._apply_sentence_word_repeats(clean, add)

            emoji_n = count_bio_emojis(raw)
            if 1 <= emoji_n <= 2:
                add(-12, f"Уместные смайлики ({emoji_n})", heavy=False)
            elif emoji_n > 2:
                extra = emoji_n - 2
                add(extra * 5, f"Эмодзи сверх 2 ({extra} шт.)", heavy=False)
            crazy = raw.count("🤪")
            if crazy:
                add(crazy * 13, f"🤪 ×{crazy}", heavy=False)
            if ")))" in raw:
                add(13, "Три скобки )))", heavy=False)
            elif "))" in raw:
                add(8, "Две скобки ))", heavy=False)

            qualities = re.findall(
                r"\b(добрый|добрая|честный|честная|вес[её]лый|вес[её]лая|"
                r"отзывчивый|отзывчивая|заботливый|заботливая|умный|умная|"
                r"красивый|красивая|верный|верная)\b",
                clean,
            )
            if qualities:
                add(-len(qualities) * 7, f"Личные качества ({len(qualities)})", heavy=False)

            has_mobile = any(re.search(p, clean, re.IGNORECASE) for p in MOBILE_GAME_PATTERNS)
            has_social = bool(SOCIAL_LINK_RE.search(clean))
            has_height_req = bool(re.search(r"рост\s*(от|выше)", clean))
            if not has_social and not has_height_req and not has_mobile:
                add(-5, "Нет соцсетей / роста / моб. игр", heavy=False)

        claimed = extract_claimed_ages(raw)
        sub18 = [age for age in claimed if age < 18]
        if sub18:
            youngest = min(sub18)
            penalty = under_18_penalty(youngest)
            add(penalty, f"Возраст {youngest} (< 18)", heavy=True)

        score = sum(tag.delta for tag in tags)

        if heavy_flags >= 3:
            before = score
            score *= 1.5
            tags.append(
                TrashTag(
                    label=f"Синергия ×1.5 ({heavy_flags} тяжёлых)",
                    delta=score - before,
                    heavy=False,
                )
            )

        return TrashAnalysisResult(
            score=score,
            label=classify_trash_score(score),
            tags=tags,
            auto_100=any(t.delta >= 100 for t in tags),
        )

    def _apply_positive_bonuses(self, clean: str, raw: str, add) -> None:
        sentences = split_sentences(clean)
        raw_cf = raw.casefold()

        if re.search(r"\b(привет|хай|здравствуйте|hi|hello|йо+у)\b", clean):
            add(-3, "Приветствие", heavy=False)
        if re.search(
            r"\b(пока|до\s+связи|всем\s+пока|удачи|удачного|"
            r"хорошего\s+дня|хорошего\s+вечера|приятного\s+дня|"
            r"успехов|с\s+наступающим|с\s+праздником)\b",
            clean,
        ):
            add(-12, "Прощание / пожелания", heavy=False)
        if re.search(r"я\s+не\s+кусаюсь", clean):
            add(-9, "«Я не кусаюсь»", heavy=False)
        if re.search(r"не\s+против\s+погулять\s+и\s+поговорить\s+обо\s+вс[её]м", clean):
            add(-12, "«Не против погулять…»", heavy=False)
        if re.search(r"ищу\s+друга\s*/?\s*подружку\s*,?\s*может\s+отношения", clean):
            add(-20, "Друг/подруга, может отношения", heavy=False)
        if re.search(r"(discord|дискорд|\bдс\b)", clean):
            add(-20, "Discord", heavy=False)
        if re.search(r"(компьютерные\s+игры|пк\s+игры|геймер)", clean):
            add(-20, "ПК-игры", heavy=False)
        if re.search(r"(стим|steam)", clean):
            add(-10, "Steam", heavy=False)

        for sentence in sentences:
            if self._is_high_friendliness_sentence(sentence):
                add(-28, "Доброжелательность (высокая)", heavy=False)
                break

        for sentence in sentences:
            if self._is_initiative_sentence(sentence):
                add(-22, "Инициативность", heavy=False)
                break

        if self._is_cuteness_phrase(clean, raw_cf):
            add(-15, "Милота", heavy=False)

        for sentence in sentences:
            if self._is_regular_friendliness_sentence(sentence):
                add(-10, "Доброжелательность", heavy=False)
                break

    @staticmethod
    def _is_high_friendliness_sentence(sentence: str) -> bool:
        has_glad = bool(re.search(r"\b(?:буду\s+)?рад[аы]\b", sentence))
        has_interest = bool(
            re.search(
                r"(?:увлечен|увлечени|попроб(?:овать|ую|уем)|узнать\s+побольше|"
                r"расскаж(?:и|ите)\s+о\s+себе)",
                sentence,
            )
        )
        return has_glad and has_interest

    @staticmethod
    def _is_regular_friendliness_sentence(sentence: str) -> bool:
        if TrashAnalyzer._is_high_friendliness_sentence(sentence):
            return False
        return bool(
            re.search(
                r"\b(?:буду\s+)?рад[аы]\b|"
                r"буду\s+рада\s+пообщаться|"
                r"рада\s+знакомству|"
                r"приятно\s+пообщаться",
                sentence,
            )
        )

    @staticmethod
    def _is_initiative_sentence(sentence: str) -> bool:
        return bool(
            re.search(
                r"(?:^|\s)(?:всегда\s+)?за\s+(?:поиграть|сходить|погулять|встретиться)|"
                r"готова\s+(?:с|по)|"
                r"предлагаю\s+|"
                r"давай(?:те)?\s+(?:с|по|вместе)",
                sentence,
            )
        )

    @staticmethod
    def _is_cuteness_phrase(clean: str, raw_cf: str) -> bool:
        has_busy = bool(re.search(r"(?:часто\s+)?(?:бываю\s+)?занят[аы]?\b", clean))
        has_time = bool(
            re.search(
                r"(?:но|однако).{0,40}(?:найду|найд[ёе]м).{0,30}(?:время|минут)",
                clean,
            )
        )
        has_heart = bool(re.search(r"(<3|❤|♥|💕|💗|🥰)", raw_cf))
        return has_busy and has_time and has_heart

    @staticmethod
    def _apply_sentence_word_repeats(clean: str, add) -> None:
        repeated_in_sentence: set[str] = set()
        for sentence in split_sentences(clean):
            words = [
                w
                for w in re.findall(r"[а-яёa-z]+", sentence)
                if len(w) >= 3 and w not in STOP_WORDS
            ]
            for word, count in Counter(words).items():
                if count >= 3:
                    repeated_in_sentence.add(word)
        if repeated_in_sentence:
            sample = ", ".join(sorted(repeated_in_sentence)[:3])
            add(33, f"Повтор слов в предложении: {sample}", heavy=True)

    def _apply_hobby_bonus(self, clean: str, add) -> None:
        found: set[str] = set()
        for pattern, key in HOBBY_PATTERNS:
            if re.search(pattern, clean):
                found.add(key)
        count = len(found)
        if count == 0:
            return
        bonus = -14 - 2 * (count - 1)
        add(bonus, f"Увлечения ({count})", heavy=False)

    def _collect_auto_flags(
        self,
        *,
        clean: str,
        raw: str,
        word_count: int,
        photo_count: int,
        has_description: bool,
        has_video: bool,
    ) -> list[tuple[str, float, str]]:
        flags: list[tuple[str, float, str]] = []

        if word_count < 5 and photo_count == 0 and not has_video:
            flags.append(("words_lt5_no_photo", 100, "Слов < 5 и нет фото"))
        if has_description and self._is_social_only_bio(clean):
            flags.append(("social_only", 175, "Только ссылка на соцсеть"))
        if has_description and (
            clean == "ну ладно"
            or re.fullmatch(r"не\s+знаю,?\s+что\s+я\s+тут\s+делаю", clean)
        ):
            flags.append(("empty_phrase", 100, "Пустой текст"))
        haystack = clean if has_description else raw.casefold()
        if self._has_relationship_status(haystack):
            flags.append(("in_relationship", 100, "В отношениях"))
        return flags

    @staticmethod
    def _has_relationship_status(text: str) -> bool:
        if re.search(
            r"есть\s+(?:у\s+меня\s+)?(парень|девушка|муж|жена|вторая\s+половинка)|"
            r"\bв\s+отношениях\b|"
            r"(?:^|[.!?\n]\s*)занят[аы]?(?:\s|$|[,.])",
            text,
        ):
            return True
        if re.search(r"\bзанят[аы]?\b", text):
            if re.search(r"(?:бываю|буду|была|часто|сейчас|очень)\s+занят[аы]?\b", text):
                return False
            if re.search(r"занят[аы]?\s*,?\s*но\b", text):
                return False
            return True
        return False

    @staticmethod
    def _is_social_only_bio(clean: str) -> bool:
        if not clean or not SOCIAL_LINK_RE.search(clean):
            return False
        remainder = SOCIAL_LINK_RE.sub(" ", clean)
        remainder = re.sub(r"[^\w\s]", " ", remainder)
        words = [
            w
            for w in remainder.split()
            if len(w) >= 2 and w not in STOP_WORDS
        ]
        return len(words) <= 2

    @staticmethod
    def _unreadable_nick(nickname: str) -> bool:
        if not nickname:
            return False
        return not re.search(r"[a-zA-Zа-яА-ЯёЁ]", nickname)

    @staticmethod
    def _apply_fandom_heuristics(clean: str, add) -> None:
        fandom_markers = ("фд", "фандом", "аниме", "к-pop", "kpop", "bts", "blackpink")
        hobby_markers = ("рисую", "спорт", "читаю", "готовлю", "работаю", "учусь", "хобби")
        has_fandom = any(m in clean for m in fandom_markers)
        has_hobby = any(m in clean for m in hobby_markers)
        if has_fandom and not has_hobby:
            add(18, "Только фандомы", heavy=False)

    def _apply_fandom_music_heuristics(self, clean: str, add) -> None:
        self._apply_fandom_heuristics(clean, add)
        music_markers = ("музык", "слушаю", "playlist", "плейлист", "артист", "групп")
        hobby_markers = ("рисую", "спорт", "читаю", "готовлю", "работаю", "учусь", "хобби", "фд")
        has_music = any(m in clean for m in music_markers)
        has_hobby = any(m in clean for m in hobby_markers)
        if has_music and not has_hobby:
            add(12, "Только музыка", heavy=False)


_analyzer = TrashAnalyzer()


def analyze_trash(
    *,
    raw_text: str,
    nickname: str = "",
    photo_face_counts: list[int] | None = None,
    photo_bw_flags: list[bool] | None = None,
    photo_phone_flags: list[bool] | None = None,
    photo_count: int = 0,
    has_video: bool = False,
    profile_age: int | None = None,
    word_count: int | None = None,
) -> TrashAnalysisResult:
    claimed = extract_claimed_ages(raw_text)
    text_age = min(claimed) if claimed else None
    return _analyzer.analyze(
        text=raw_text,
        nickname=nickname,
        photo_face_counts=photo_face_counts,
        photo_bw_flags=photo_bw_flags,
        photo_phone_flags=photo_phone_flags,
        photo_count=photo_count,
        has_video=has_video,
        profile_age=profile_age,
        text_age=text_age,
        word_count=word_count,
    )
