"""Experiment definitions and participant enrollment models."""

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from mandarin_tone_recorder.participants.models import Participant


class BaseSyllable(models.Model):
    """The segmental identity shared by one or more rendered prompts."""

    ascii = models.CharField(max_length=40, unique=True)
    pinyin_base = models.CharField(max_length=40, db_index=True)
    onset = models.CharField(blank=True, max_length=20)
    medial = models.CharField(blank=True, max_length=20)
    nucleus = models.CharField(blank=True, max_length=20)
    coda = models.CharField(blank=True, max_length=20)
    ipa_base = models.CharField(blank=True, max_length=80)

    def __str__(self) -> str:
        return self.pinyin_base


class Stimulus(models.Model):
    """A stable prompt that may be assigned in one or more experiments."""

    class Condition(models.TextChoices):
        TONE_BEARING = "tone_bearing", "Tone-bearing prompt"
        TONE_UNSPECIFIED = "tone_unspecified", "Tone-unspecified prompt"

    stable_id = models.CharField(max_length=80, unique=True)
    base_syllable = models.ForeignKey(
        BaseSyllable,
        on_delete=models.PROTECT,
        related_name="stimuli",
    )
    condition = models.CharField(choices=Condition, max_length=30)
    target_tone = models.PositiveSmallIntegerField(
        blank=True,
        null=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    display_text = models.CharField(max_length=80)
    prompt_type = models.CharField(default="pinyin", max_length=30)
    is_attested = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=("condition", "target_tone")),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        condition="tone_bearing",
                        target_tone__gte=1,
                        target_tone__lte=5,
                    )
                    | models.Q(
                        condition="tone_unspecified",
                        target_tone__isnull=True,
                    )
                ),
                name="stimulus_condition_matches_target_tone",
            )
        ]

    def __str__(self) -> str:
        return self.display_text


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
    stimuli = models.ManyToManyField(
        Stimulus,
        related_name="experiments",
        through="ExperimentStimulus",
    )

    def __str__(self) -> str:
        return self.name


class ExperimentStimulus(models.Model):
    """Membership and availability of a stimulus within an experiment."""

    experiment = models.ForeignKey(
        Experiment,
        on_delete=models.CASCADE,
        related_name="stimulus_memberships",
    )
    stimulus = models.ForeignKey(
        Stimulus,
        on_delete=models.PROTECT,
        related_name="experiment_memberships",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("experiment", "stimulus"),
                name="unique_experiment_stimulus",
            )
        ]

    def __str__(self) -> str:
        return f"{self.experiment}: {self.stimulus}"


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
