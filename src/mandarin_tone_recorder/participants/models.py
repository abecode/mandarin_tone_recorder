"""Participant identity, consent, and study-background models."""

import uuid

from django.conf import settings
from django.db import models


NATIVE_LANGUAGE_CHOICES = (
    (
        "Common options",
        (
            ("cmn-Hans-CN", "Mandarin Chinese, Mainland China"),
            ("cmn-Hant-TW", "Mandarin Chinese, Taiwan"),
            ("en-US", "English, United States"),
            ("en-GB", "English, United Kingdom"),
            ("en", "English, other region"),
            ("es", "Spanish"),
            ("ja", "Japanese"),
            ("ko", "Korean"),
            ("vi", "Vietnamese"),
        ),
    ),
    (
        "Other listed languages",
        (
            ("yue-Hant-HK", "Cantonese, Hong Kong"),
            ("nan-Hant-TW", "Taiwanese Hokkien / Taiwanese"),
            ("nan", "Hokkien / Min Nan"),
            # Private-use BCP 47 tag using the Glottolog identifier.
            ("x-mmok1234", "Mmuock / Mmock"),
            ("other", "Other language"),
        ),
    ),
)

NATIVE_LANGUAGE_LABELS = {
    value: label
    for _group, choices in NATIVE_LANGUAGE_CHOICES
    for value, label in choices
}


class Participant(models.Model):
    """A study participant who may remain anonymous or later claim an account."""

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="participants",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return str(self.public_id)


class Consent(models.Model):
    """An affirmative response to a specific version of the study consent."""

    participant = models.ForeignKey(
        Participant,
        on_delete=models.CASCADE,
        related_name="consents",
    )
    version = models.CharField(max_length=40)
    accepted_at = models.DateTimeField(auto_now_add=True)
    withdrawn_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("participant", "version"),
                name="unique_participant_consent_version",
            )
        ]

    def __str__(self) -> str:
        return f"{self.participant} consented to {self.version}"


class ParticipantProfile(models.Model):
    """Study answers used to route a participant to an experiment."""

    class SpeakerBackground(models.TextChoices):
        LEARNER = "learner", "Learner"
        NATIVE = "native", "Native speaker"
        HERITAGE = "heritage", "Heritage speaker"

    class MandarinLevel(models.TextChoices):
        BEGINNER = "beginner", "Beginner"
        INTERMEDIATE = "intermediate", "Intermediate"
        ADVANCED = "advanced", "Advanced"

    participant = models.OneToOneField(
        Participant,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    knows_mandarin = models.BooleanField(blank=True, null=True)
    speaker_background = models.CharField(
        blank=True,
        choices=SpeakerBackground,
        max_length=20,
    )
    mandarin_level = models.CharField(
        blank=True,
        choices=MandarinLevel,
        max_length=20,
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Profile for {self.participant}"


class ParticipantLanguage(models.Model):
    """A language associated with a participant's background or proficiency."""

    class Relationship(models.TextChoices):
        NATIVE = "native", "Native or first language"
        HERITAGE = "heritage", "Heritage language"
        LEARNED = "learned", "Learned language"
        OTHER = "other", "Other relationship"

    class Proficiency(models.TextChoices):
        BEGINNER = "beginner", "Beginner"
        INTERMEDIATE = "intermediate", "Intermediate"
        ADVANCED = "advanced", "Advanced"
        NATIVE_LIKE = "native_like", "Native-like"

    profile = models.ForeignKey(
        ParticipantProfile,
        on_delete=models.CASCADE,
        related_name="languages",
    )
    language_tag = models.CharField(max_length=40)
    relationship = models.CharField(
        choices=Relationship,
        max_length=20,
    )
    proficiency = models.CharField(
        blank=True,
        choices=Proficiency,
        max_length=20,
    )
    other_language_name = models.CharField(blank=True, max_length=120)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("profile", "language_tag", "relationship"),
                name="unique_profile_language_relationship",
            )
        ]

    def __str__(self) -> str:
        return f"{self.language_tag} for {self.profile.participant}"

    @property
    def display_name(self) -> str:
        label = NATIVE_LANGUAGE_LABELS.get(self.language_tag, self.language_tag)
        if self.other_language_name:
            return f"{label}: {self.other_language_name}"
        return label
