"""Import and export repo-backed practice decks."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils.text import slugify
import yaml

from mandarin_tone_recorder.practice.models import PracticeDeck, PracticeItem
from mandarin_tone_recorder.practice.services import generate_pinyin_text


DEFAULT_ACTIVITY_TYPE = "reading_speaking"
DEFAULT_RESPONSE_TYPE = "audio"
DEFAULT_PRACTICE_DECK_DIR = Path("content") / "practice_decks"
SLUG_PATTERN = re.compile(r"^[a-z0-9_]+$")


class PracticeDeckFileError(ValueError):
    """Raised when a practice deck YAML file cannot be imported safely."""


@dataclass(frozen=True)
class PracticeDeckImportResult:
    """Summary for one imported practice deck file."""

    deck: PracticeDeck
    path: Path
    created: bool
    item_count: int


@dataclass(frozen=True)
class PracticeDeckImportSummary:
    """Summary for importing a directory of practice deck files."""

    results: tuple[PracticeDeckImportResult, ...]

    @property
    def imported_count(self) -> int:
        return len(self.results)


@dataclass(frozen=True)
class ParsedPracticeItem:
    """One parsed practice item from a YAML deck file."""

    prompt_hanzi: str
    hint_pinyin: str


@dataclass(frozen=True)
class ParsedPracticeDeck:
    """A validated practice deck parsed from YAML."""

    slug: str
    version: int
    title: str
    activity_type: str
    response_type: str
    items: tuple[ParsedPracticeItem, ...]

    @property
    def source_text(self) -> str:
        return "\n".join(item.prompt_hanzi for item in self.items)


def default_practice_deck_directory() -> Path:
    """Return the conventional repository directory for practice deck YAML files."""
    return settings.BASE_DIR / DEFAULT_PRACTICE_DECK_DIR


def parse_practice_deck_yaml(yaml_text: str) -> ParsedPracticeDeck:
    """Parse and validate the repository YAML format for a practice deck."""
    data = yaml.safe_load(yaml_text)
    if not isinstance(data, Mapping):
        raise PracticeDeckFileError("Practice deck YAML must contain a mapping.")

    slug = _required_string(data, "slug")
    if not SLUG_PATTERN.fullmatch(slug):
        raise PracticeDeckFileError(
            "Practice deck slug must use lowercase letters, numbers, and underscores."
        )

    version = data.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise PracticeDeckFileError("Practice deck version must be a positive integer.")

    title = _required_string(data, "title")
    activity_type = _optional_string(
        data,
        "activity_type",
        default=DEFAULT_ACTIVITY_TYPE,
    )
    response = data.get("response", {})
    if response is None:
        response = {}
    if not isinstance(response, Mapping):
        raise PracticeDeckFileError("Practice deck response must be a mapping.")
    response_type = _optional_string(
        response,
        "type",
        default=DEFAULT_RESPONSE_TYPE,
    )

    raw_items = data.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise PracticeDeckFileError("Practice deck items must be a non-empty list.")

    items = tuple(_parse_item(raw_item, index) for index, raw_item in enumerate(raw_items, start=1))
    return ParsedPracticeDeck(
        slug=slug,
        version=version,
        title=title,
        activity_type=activity_type,
        response_type=response_type,
        items=items,
    )


@transaction.atomic
def import_practice_deck_file(
    path: str | Path,
    *,
    base_dir: str | Path | None = None,
) -> PracticeDeckImportResult:
    """Import or refresh one YAML-backed practice deck."""
    path = Path(path)
    parsed = parse_practice_deck_yaml(path.read_text(encoding="utf-8"))
    source_path = _relative_source_path(path, base_dir=base_dir)

    deck = PracticeDeck.objects.filter(slug=parsed.slug, version=parsed.version).first()
    created = deck is None
    if deck is None:
        deck = PracticeDeck.objects.create(**_deck_defaults(parsed, source_path))
        _replace_items(deck, parsed.items)
        return PracticeDeckImportResult(
            deck=deck,
            path=path,
            created=True,
            item_count=len(parsed.items),
        )

    if deck.sessions.exists() and _stored_item_pairs(deck) != _parsed_item_pairs(parsed.items):
        raise PracticeDeckFileError(
            f"Deck {parsed.slug} v{parsed.version} already has sessions; "
            "change the YAML version before changing its items."
        )

    for field, value in _deck_defaults(parsed, source_path).items():
        setattr(deck, field, value)
    deck.save()
    if not deck.sessions.exists():
        _replace_items(deck, parsed.items)

    return PracticeDeckImportResult(
        deck=deck,
        path=path,
        created=created,
        item_count=len(parsed.items),
    )


def import_practice_deck_directory(
    directory: str | Path | None = None,
) -> PracticeDeckImportSummary:
    """Import every YAML practice deck in a directory."""
    directory = Path(directory) if directory is not None else default_practice_deck_directory()
    if not directory.exists():
        raise PracticeDeckFileError(f"Practice deck directory does not exist: {directory}")
    paths = sorted([*directory.glob("*.yaml"), *directory.glob("*.yml")])
    results = tuple(
        import_practice_deck_file(path, base_dir=settings.BASE_DIR) for path in paths
    )
    return PracticeDeckImportSummary(results=results)


def practice_deck_to_data(deck: PracticeDeck) -> dict[str, Any]:
    """Return a YAML-serializable mapping for one practice deck."""
    slug = deck.slug or slugify(deck.title).replace("-", "_")
    version = deck.version or 1
    return {
        "slug": slug,
        "version": version,
        "title": deck.title,
        "activity_type": deck.activity_type,
        "response": {"type": deck.response_type},
        "items": [
            {
                "prompts": {"hanzi": item.prompt_text},
                "hints": {"pinyin": item.pinyin_text},
            }
            for item in deck.items.all()
        ],
    }


def export_practice_deck(deck: PracticeDeck, path: str | Path) -> Path:
    """Write one practice deck to YAML and return the output path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    yaml_text = yaml.safe_dump(
        practice_deck_to_data(deck),
        allow_unicode=True,
        sort_keys=False,
    )
    path.write_text(yaml_text, encoding="utf-8")
    return path


def _parse_item(raw_item: Any, index: int) -> ParsedPracticeItem:
    if not isinstance(raw_item, Mapping):
        raise PracticeDeckFileError(f"Practice deck item {index} must be a mapping.")

    prompts = raw_item.get("prompts")
    if not isinstance(prompts, Mapping):
        raise PracticeDeckFileError(f"Practice deck item {index} must have prompts.")
    prompt_hanzi = _required_string(prompts, "hanzi", label=f"item {index} prompt hanzi")

    hints = raw_item.get("hints", {})
    if hints is None:
        hints = {}
    if not isinstance(hints, Mapping):
        raise PracticeDeckFileError(f"Practice deck item {index} hints must be a mapping.")
    hint_pinyin = _optional_string(
        hints,
        "pinyin",
        default=generate_pinyin_text(prompt_hanzi),
    )
    return ParsedPracticeItem(prompt_hanzi=prompt_hanzi, hint_pinyin=hint_pinyin)


def _required_string(
    data: Mapping[str, Any],
    key: str,
    *,
    label: str | None = None,
) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PracticeDeckFileError(f"Practice deck {label or key} must be a string.")
    return value.strip()


def _optional_string(
    data: Mapping[str, Any],
    key: str,
    *,
    default: str,
) -> str:
    value = data.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise PracticeDeckFileError(f"Practice deck {key} must be a string.")
    return value.strip()


def _deck_defaults(parsed: ParsedPracticeDeck, source_path: str) -> dict[str, Any]:
    return {
        "user": None,
        "slug": parsed.slug,
        "version": parsed.version,
        "title": parsed.title,
        "source_text": parsed.source_text,
        "activity_type": parsed.activity_type,
        "response_type": parsed.response_type,
        "is_shared": True,
        "is_builtin": True,
        "source_path": source_path,
    }


def _replace_items(deck: PracticeDeck, items: Iterable[ParsedPracticeItem]) -> None:
    deck.items.all().delete()
    PracticeItem.objects.bulk_create(
        [
            PracticeItem(
                deck=deck,
                prompt_text=item.prompt_hanzi,
                pinyin_text=item.hint_pinyin,
                sort_order=index,
            )
            for index, item in enumerate(items, start=1)
        ]
    )


def _stored_item_pairs(deck: PracticeDeck) -> tuple[tuple[str, str], ...]:
    return tuple(deck.items.values_list("prompt_text", "pinyin_text"))


def _parsed_item_pairs(items: Iterable[ParsedPracticeItem]) -> tuple[tuple[str, str], ...]:
    return tuple((item.prompt_hanzi, item.hint_pinyin) for item in items)


def _relative_source_path(path: Path, *, base_dir: str | Path | None) -> str:
    if base_dir is None:
        return str(path)
    try:
        return str(path.relative_to(Path(base_dir)))
    except ValueError:
        return str(path)
