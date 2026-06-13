"""Participant identity, consent, and study-background models."""

import uuid

from django.conf import settings
from django.db import models


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
