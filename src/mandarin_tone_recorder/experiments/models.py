"""Experiment definitions and participant enrollment models."""

from django.db import models

from mandarin_tone_recorder.participants.models import Participant


class Experiment(models.Model):
    """A versioned recording experiment available to participants."""

    class Track(models.TextChoices):
        TONE = "tone", "Tone-based experiment"
        NON_TONE = "non-tone", "Non-tone experiment"

    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    track = models.CharField(choices=Track, max_length=20)
    target_duration_minutes = models.PositiveSmallIntegerField(default=20)
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.name


class Enrollment(models.Model):
    """A participant's routed entry into one experiment."""

    class Status(models.TextChoices):
        READY = "ready", "Ready"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"
        ABORTED = "aborted", "Aborted"

    participant = models.ForeignKey(
        Participant,
        on_delete=models.CASCADE,
        related_name="enrollments",
    )
    experiment = models.ForeignKey(
        Experiment,
        on_delete=models.PROTECT,
        related_name="enrollments",
    )
    status = models.CharField(choices=Status, default=Status.READY, max_length=20)
    routing_reason = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("participant", "experiment"),
                name="unique_participant_experiment_enrollment",
            )
        ]

    def __str__(self) -> str:
        return f"{self.participant} in {self.experiment}"
