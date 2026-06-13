"""Recording session and stimulus-attempt models."""

import uuid
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from mandarin_tone_recorder.experiments.models import (
    Enrollment,
    ExperimentStimulus,
    Stimulus,
)


def recording_upload_to(instance: "RecordingAttempt", filename: str) -> str:
    """Build an opaque, participant-scoped path for an uploaded recording."""
    extension = Path(filename).suffix.lower()
    participant_id = instance.session.enrollment.participant.public_id
    return (
        f"recordings/{participant_id}/{instance.session.public_id}/"
        f"{instance.recording_id}{extension}"
    )


class RecordingSession(models.Model):
    """One time-targeted recording period for an experiment enrollment."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        FINISHED = "finished", "Finished"
        ABORTED = "aborted", "Aborted"

    public_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    enrollment = models.ForeignKey(
        Enrollment,
        on_delete=models.PROTECT,
        related_name="recording_sessions",
    )
    status = models.CharField(
        choices=Status,
        default=Status.ACTIVE,
        max_length=20,
    )
    target_duration_seconds = models.PositiveIntegerField(
        validators=[MinValueValidator(1)]
    )
    started_at = models.DateTimeField(default=timezone.now)
    target_reached_at = models.DateTimeField(blank=True, null=True)
    continued_after_target = models.BooleanField(default=False)
    ended_at = models.DateTimeField(blank=True, null=True)
    current_stimulus = models.ForeignKey(
        Stimulus,
        blank=True,
        null=True,
        on_delete=models.PROTECT,
        related_name="current_in_sessions",
    )
    current_stimulus_index = models.PositiveIntegerField(blank=True, null=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(current_stimulus__isnull=True, current_stimulus_index__isnull=True)
                    | Q(
                        current_stimulus__isnull=False,
                        current_stimulus_index__isnull=False,
                    )
                ),
                name="recording_current_stimulus_fields_match",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status="active", ended_at__isnull=True)
                    | Q(
                        status__in=("finished", "aborted"),
                        ended_at__isnull=False,
                    )
                ),
                name="recording_session_end_matches_status",
            ),
            models.CheckConstraint(
                condition=Q(target_duration_seconds__gt=0),
                name="recording_session_target_duration_positive",
            ),
            models.CheckConstraint(
                condition=Q(current_stimulus_index__isnull=True)
                | Q(current_stimulus_index__gt=0),
                name="recording_current_stimulus_index_positive",
            ),
        ]

    def clean(self) -> None:
        """Validate state that depends on related experiment records."""
        super().clean()
        if (
            self.current_stimulus_id
            and self.enrollment_id
            and not ExperimentStimulus.objects.filter(
                experiment=self.enrollment.experiment,
                stimulus_id=self.current_stimulus_id,
                is_active=True,
            ).exists()
        ):
            raise ValidationError(
                {"current_stimulus": "Stimulus is not active in this experiment."}
            )

    def __str__(self) -> str:
        return str(self.public_id)


class RecordingAttempt(models.Model):
    """One accepted or rejected interaction with a presented stimulus."""

    class Status(models.TextChoices):
        ACCEPTED = "accepted", "Accepted"
        TIMED_OUT = "timed_out", "Timed out"
        SPEAKER_REJECTED = "speaker_rejected", "Speaker rejected"
        ABORTED = "aborted", "Aborted"
        SAVE_FAILED = "save_failed", "Save failed"

    recording_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    session = models.ForeignKey(
        RecordingSession,
        on_delete=models.CASCADE,
        related_name="attempts",
    )
    stimulus = models.ForeignKey(
        Stimulus,
        on_delete=models.PROTECT,
        related_name="recording_attempts",
    )
    stimulus_index = models.PositiveIntegerField(
        validators=[MinValueValidator(1)]
    )
    attempt_number = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
    )
    status = models.CharField(choices=Status, max_length=30)
    duration_seconds = models.FloatField(blank=True, null=True)
    mime_type = models.CharField(blank=True, max_length=100)
    raw_audio = models.FileField(
        blank=True,
        max_length=500,
        upload_to=recording_upload_to,
    )
    wav_audio = models.FileField(
        blank=True,
        max_length=500,
        upload_to=recording_upload_to,
    )
    started_at = models.DateTimeField(blank=True, null=True)
    ended_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("session", "stimulus_index", "attempt_number")
        constraints = [
            models.UniqueConstraint(
                fields=("session", "stimulus_index", "attempt_number"),
                name="unique_session_stimulus_attempt_number",
            ),
            models.CheckConstraint(
                condition=Q(duration_seconds__isnull=True)
                | Q(duration_seconds__gte=0),
                name="recording_attempt_duration_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(stimulus_index__gt=0, attempt_number__gt=0),
                name="recording_attempt_numbers_positive",
            ),
        ]
        indexes = [
            models.Index(fields=("stimulus", "status")),
        ]

    def clean(self) -> None:
        """Validate stimulus membership and attempt timing."""
        super().clean()
        errors: dict[str, str] = {}
        if self.session_id and self.stimulus_id:
            if not ExperimentStimulus.objects.filter(
                experiment=self.session.enrollment.experiment,
                stimulus_id=self.stimulus_id,
                is_active=True,
            ).exists():
                errors["stimulus"] = "Stimulus is not active in this experiment."
        if self.started_at and self.ended_at and self.ended_at < self.started_at:
            errors["ended_at"] = "Attempt cannot end before it starts."
        if self.status == self.Status.ACCEPTED and not self.raw_audio:
            errors["raw_audio"] = "Accepted attempts require an audio file."
        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.session} item {self.stimulus_index} attempt {self.attempt_number}"
