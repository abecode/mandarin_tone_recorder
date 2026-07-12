"""Models for user-created Mandarin practice sessions."""

from django.conf import settings
from django.db import models


class PracticeDeck(models.Model):
    """A set of practice prompts created from user-provided text."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="practice_decks",
    )
    title = models.CharField(max_length=200)
    source_text = models.TextField()
    is_shared = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at", "id")

    def __str__(self) -> str:
        return self.title


class PracticeItem(models.Model):
    """One sentence or prompt inside a practice deck."""

    deck = models.ForeignKey(
        PracticeDeck,
        on_delete=models.CASCADE,
        related_name="items",
    )
    prompt_text = models.TextField()
    pinyin_text = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("sort_order", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("deck", "sort_order"),
                name="unique_practice_item_sort_order",
            ),
            models.CheckConstraint(
                condition=models.Q(sort_order__gt=0),
                name="practice_item_sort_order_positive",
            ),
        ]

    def __str__(self) -> str:
        return self.prompt_text


class PracticeSession(models.Model):
    """One logged-in user's run through a practice deck."""

    deck = models.ForeignKey(
        PracticeDeck,
        on_delete=models.CASCADE,
        related_name="sessions",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="practice_sessions",
    )
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ("-started_at", "id")

    def __str__(self) -> str:
        return f"{self.user} practicing {self.deck}"


class PracticeAttempt(models.Model):
    """One attempt to read a practice item."""

    session = models.ForeignKey(
        PracticeSession,
        on_delete=models.CASCADE,
        related_name="attempts",
    )
    item = models.ForeignKey(
        PracticeItem,
        on_delete=models.CASCADE,
        related_name="attempts",
    )
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    response_time_ms = models.PositiveIntegerField(blank=True, null=True)
    server_elapsed_ms = models.PositiveIntegerField(blank=True, null=True)

    class Meta:
        ordering = ("started_at", "id")

    def __str__(self) -> str:
        return f"Attempt for {self.item} in {self.session}"


class PracticeHintEvent(models.Model):
    """A pinyin hint revealed during one practice attempt."""

    class HintType(models.TextChoices):
        CHARACTER_PINYIN = "character_pinyin", "Character pinyin"
        SENTENCE_PINYIN = "sentence_pinyin", "Sentence pinyin"

    attempt = models.ForeignKey(
        PracticeAttempt,
        on_delete=models.CASCADE,
        related_name="hint_events",
    )
    hint_type = models.CharField(choices=HintType, max_length=30)
    character = models.CharField(blank=True, max_length=10)
    character_index = models.PositiveIntegerField(blank=True, null=True)
    revealed_at = models.DateTimeField(auto_now_add=True)
    revealed_at_ms = models.PositiveIntegerField(blank=True, null=True)

    class Meta:
        ordering = ("revealed_at", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("attempt", "hint_type"),
                condition=models.Q(hint_type="sentence_pinyin"),
                name="unique_sentence_pinyin_hint_per_attempt",
            ),
            models.UniqueConstraint(
                fields=("attempt", "hint_type", "character_index"),
                condition=models.Q(hint_type="character_pinyin"),
                name="unique_character_pinyin_hint_per_attempt",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        hint_type="sentence_pinyin",
                        character="",
                        character_index__isnull=True,
                    )
                    | models.Q(
                        hint_type="character_pinyin",
                        character__gt="",
                        character_index__isnull=False,
                    )
                ),
                name="practice_hint_fields_match_type",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.hint_type} for {self.attempt}"
