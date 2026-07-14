"""Services for creating practice decks and derived items."""

from collections.abc import Sequence
from typing import Any

from django.db.models import Q, QuerySet
from django.utils import timezone
from pypinyin import Style, lazy_pinyin

from mandarin_tone_recorder.practice.models import (
    PracticeAttempt,
    PracticeDeck,
    PracticeHintEvent,
    PracticeItem,
    PracticeSession,
)


def split_practice_lines(source_text: str) -> list[str]:
    """Return non-empty newline-delimited practice prompts."""
    return [line.strip() for line in source_text.splitlines() if line.strip()]


def generate_pinyin_text(prompt_text: str) -> str:
    """Generate editable numbered pinyin text for a practice prompt."""
    syllables = lazy_pinyin(
        prompt_text,
        style=Style.TONE3,
        neutral_tone_with_five=True,
    )
    return " ".join(syllables)


def create_practice_deck(
    *,
    user: Any,
    title: str,
    source_text: str,
    is_shared: bool = False,
) -> PracticeDeck:
    """Create a deck and one pinyin-bearing item per non-empty source line."""
    prompts = split_practice_lines(source_text)
    if not prompts:
        raise ValueError("Practice deck source text must contain at least one prompt.")

    deck = PracticeDeck.objects.create(
        user=user,
        title=title,
        source_text=source_text,
        is_shared=is_shared,
    )
    items: Sequence[PracticeItem] = [
        PracticeItem(
            deck=deck,
            prompt_text=prompt,
            pinyin_text=generate_pinyin_text(prompt),
            sort_order=index,
        )
        for index, prompt in enumerate(prompts, start=1)
    ]
    PracticeItem.objects.bulk_create(items)
    return deck


def visible_practice_decks(user: Any) -> QuerySet[PracticeDeck]:
    """Return decks visible by default plus decks owned by this user."""
    visibility = Q(user__isnull=True) | Q(is_shared=True)
    if getattr(user, "is_authenticated", False):
        visibility |= Q(user=user)
    return PracticeDeck.objects.filter(visibility).distinct()


def create_practice_session(
    *,
    user: Any,
    deck: PracticeDeck,
) -> PracticeSession:
    """Start a logged-in user's practice run for a visible deck."""
    if not getattr(user, "is_authenticated", False):
        raise ValueError("Practice sessions require a logged-in user.")
    if not visible_practice_decks(user).filter(pk=deck.pk).exists():
        raise ValueError("Practice deck is not visible to this user.")
    session = PracticeSession.objects.create(deck=deck, user=user)
    start_next_practice_attempt(session)
    return session


def start_next_practice_attempt(session: PracticeSession) -> PracticeAttempt | None:
    """Create or return the active attempt for the next uncompleted item."""
    active_attempt = session.attempts.filter(completed_at__isnull=True).first()
    if active_attempt is not None:
        return active_attempt

    completed_item_ids = session.attempts.filter(
        completed_at__isnull=False
    ).values_list("item_id", flat=True)
    next_item = session.deck.items.exclude(pk__in=completed_item_ids).first()
    if next_item is None:
        if session.finished_at is None:
            session.finished_at = timezone.now()
            session.save(update_fields=("finished_at",))
        return None
    return PracticeAttempt.objects.create(session=session, item=next_item)


def complete_practice_attempt(
    attempt: PracticeAttempt,
    *,
    response_time_ms: int,
) -> PracticeAttempt:
    """Complete an active attempt with browser and server timing."""
    if attempt.completed_at is not None:
        raise ValueError("Practice attempt is already complete.")
    now = timezone.now()
    attempt.completed_at = now
    attempt.response_time_ms = response_time_ms
    attempt.server_elapsed_ms = max(
        0,
        round((now - attempt.started_at).total_seconds() * 1000),
    )
    attempt.save(
        update_fields=(
            "completed_at",
            "response_time_ms",
            "server_elapsed_ms",
        )
    )
    start_next_practice_attempt(attempt.session)
    return attempt


def record_sentence_pinyin_hint(
    *,
    attempt: PracticeAttempt,
    revealed_at_ms: int | None = None,
) -> PracticeHintEvent:
    """Record that sentence pinyin was revealed, ignoring duplicate reveals."""
    hint, _created = PracticeHintEvent.objects.get_or_create(
        attempt=attempt,
        hint_type=PracticeHintEvent.HintType.SENTENCE_PINYIN,
        defaults={"revealed_at_ms": revealed_at_ms},
    )
    return hint
