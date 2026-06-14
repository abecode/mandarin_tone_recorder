"""Transactional stimulus assignment and recording-session operations."""

import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from django.core.files import File
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from mandarin_tone_recorder.experiments.models import (
    Enrollment,
    Stimulus,
)
from mandarin_tone_recorder.recordings.models import (
    RecordingAttempt,
    RecordingSession,
)


class RecordingWorkflowError(Exception):
    """Base exception for invalid recording workflow operations."""


class NoStimuliAvailable(RecordingWorkflowError):
    """Raised when an experiment has no eligible active stimuli."""


class SessionNotActive(RecordingWorkflowError):
    """Raised when an operation requires an active recording session."""


class StimulusMismatch(RecordingWorkflowError):
    """Raised when a client submits an attempt for a stale stimulus."""


class TargetContinuationRequired(RecordingWorkflowError):
    """Raised while a target-reached session awaits Continue or Finish."""


@dataclass(frozen=True)
class AttemptResult:
    """State returned after recording one stimulus outcome."""

    attempt: RecordingAttempt
    next_stimulus: Stimulus | None
    session_done: bool
    target_reached_now: bool


def choose_next_stimulus(
    session: RecordingSession,
    *,
    chooser: Callable[[list[Stimulus]], Stimulus] = random.choice,
) -> Stimulus | None:
    """Choose an active, unaccepted, globally under-recorded stimulus."""
    accepted_in_session = RecordingAttempt.objects.filter(
        session=session,
        status=RecordingAttempt.Status.ACCEPTED,
    ).values("stimulus_id")

    candidates = list(
        Stimulus.objects.filter(
            experiment_memberships__experiment=session.enrollment.experiment,
            experiment_memberships__is_active=True,
        )
        .exclude(pk__in=accepted_in_session)
        .annotate(
            accepted_recording_count=Count(
                "recording_attempts",
                filter=Q(
                    recording_attempts__status=RecordingAttempt.Status.ACCEPTED
                ),
            )
        )
        .order_by("stable_id")
    )
    if not candidates:
        return None

    minimum_count = min(
        stimulus.accepted_recording_count for stimulus in candidates
    )
    least_recorded = [
        stimulus
        for stimulus in candidates
        if stimulus.accepted_recording_count == minimum_count
    ]
    return chooser(least_recorded)


@transaction.atomic
def start_recording_session(
    enrollment: Enrollment,
    *,
    now: datetime | None = None,
    chooser: Callable[[list[Stimulus]], Stimulus] = random.choice,
) -> RecordingSession:
    """Start an enrollment and assign its first stimulus."""
    enrollment = Enrollment.objects.select_for_update().select_related(
        "experiment"
    ).get(pk=enrollment.pk)
    if not enrollment.experiment.is_active:
        raise RecordingWorkflowError("Cannot start an inactive experiment.")
    if enrollment.status not in {
        Enrollment.Status.READY,
        Enrollment.Status.ABORTED,
    }:
        raise RecordingWorkflowError("Enrollment cannot start a new session.")
    if enrollment.recording_sessions.filter(
        status=RecordingSession.Status.ACTIVE
    ).exists():
        raise RecordingWorkflowError("Enrollment already has an active session.")

    started_at = now or timezone.now()
    session = RecordingSession.objects.create(
        enrollment=enrollment,
        target_duration_seconds=enrollment.experiment.target_duration_minutes * 60,
        started_at=started_at,
    )
    stimulus = choose_next_stimulus(session, chooser=chooser)
    if stimulus is None:
        raise NoStimuliAvailable("No active stimuli are available for this experiment.")

    session.current_stimulus = stimulus
    session.current_stimulus_index = 1
    session.full_clean()
    session.save(update_fields=("current_stimulus", "current_stimulus_index"))

    enrollment.status = Enrollment.Status.IN_PROGRESS
    enrollment.save(update_fields=("status",))
    return session


def _locked_active_session(session: RecordingSession) -> RecordingSession:
    locked = (
        RecordingSession.objects.select_for_update()
        .select_related("enrollment__experiment", "current_stimulus")
        .get(pk=session.pk)
    )
    if locked.status != RecordingSession.Status.ACTIVE:
        raise SessionNotActive("Recording session is not active.")
    if locked.current_stimulus_id is None or locked.current_stimulus_index is None:
        raise RecordingWorkflowError("Active session has no current stimulus.")
    return locked


def _require_target_acknowledgement(session: RecordingSession) -> None:
    if session.target_reached_at and not session.continued_after_target:
        raise TargetContinuationRequired(
            "Choose Continue or Finish before recording another attempt."
        )


def _validate_current_stimulus(
    session: RecordingSession,
    stimulus: Stimulus,
) -> None:
    if session.current_stimulus_id != stimulus.pk:
        raise StimulusMismatch("Attempt does not match the current stimulus.")


def _next_attempt_number(session: RecordingSession) -> int:
    latest = (
        session.attempts.filter(stimulus_index=session.current_stimulus_index)
        .order_by("-attempt_number")
        .values_list("attempt_number", flat=True)
        .first()
    )
    return (latest or 0) + 1


def _mark_target_reached(
    session: RecordingSession,
    *,
    now: datetime,
) -> bool:
    if session.target_reached_at is not None:
        return False
    elapsed_seconds = (now - session.started_at).total_seconds()
    if elapsed_seconds < session.target_duration_seconds:
        return False
    session.target_reached_at = now
    return True


@transaction.atomic
def record_accepted_attempt(
    session: RecordingSession,
    stimulus: Stimulus,
    *,
    raw_audio: File,
    duration_seconds: float,
    mime_type: str,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    now: datetime | None = None,
    chooser: Callable[[list[Stimulus]], Stimulus] = random.choice,
) -> AttemptResult:
    """Save an accepted recording and advance to the next eligible stimulus."""
    session = _locked_active_session(session)
    _require_target_acknowledgement(session)
    _validate_current_stimulus(session, stimulus)
    completed_at = now or timezone.now()

    attempt = RecordingAttempt(
        session=session,
        stimulus=session.current_stimulus,
        stimulus_index=session.current_stimulus_index,
        attempt_number=_next_attempt_number(session),
        status=RecordingAttempt.Status.ACCEPTED,
        duration_seconds=duration_seconds,
        mime_type=mime_type,
        raw_audio=raw_audio,
        started_at=started_at,
        ended_at=ended_at,
    )
    attempt.full_clean()
    attempt.save()

    target_reached_now = _mark_target_reached(session, now=completed_at)
    next_stimulus = choose_next_stimulus(session, chooser=chooser)
    if next_stimulus is None:
        session.status = RecordingSession.Status.FINISHED
        session.ended_at = completed_at
        session.current_stimulus = None
        session.current_stimulus_index = None
        session.enrollment.status = Enrollment.Status.COMPLETED
        session.enrollment.save(update_fields=("status",))
        session.full_clean()
        session.save()
        return AttemptResult(attempt, None, True, target_reached_now)

    session.current_stimulus = next_stimulus
    session.current_stimulus_index += 1
    session.full_clean()
    session.save(
        update_fields=(
            "current_stimulus",
            "current_stimulus_index",
            "target_reached_at",
        )
    )
    return AttemptResult(attempt, next_stimulus, False, target_reached_now)


@transaction.atomic
def record_retry_attempt(
    session: RecordingSession,
    stimulus: Stimulus,
    *,
    status: str,
    duration_seconds: float | None = None,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
) -> AttemptResult:
    """Record a timeout or speaker rejection without advancing the stimulus."""
    if status not in {
        RecordingAttempt.Status.TIMED_OUT,
        RecordingAttempt.Status.SPEAKER_REJECTED,
    }:
        raise RecordingWorkflowError("Retry status must be timed out or rejected.")

    session = _locked_active_session(session)
    _require_target_acknowledgement(session)
    _validate_current_stimulus(session, stimulus)
    attempt = RecordingAttempt(
        session=session,
        stimulus=session.current_stimulus,
        stimulus_index=session.current_stimulus_index,
        attempt_number=_next_attempt_number(session),
        status=status,
        duration_seconds=duration_seconds,
        started_at=started_at,
        ended_at=ended_at,
    )
    attempt.full_clean()
    attempt.save()
    return AttemptResult(attempt, session.current_stimulus, False, False)


@transaction.atomic
def continue_after_target(session: RecordingSession) -> RecordingSession:
    """Acknowledge the target prompt so later attempts do not prompt again."""
    session = _locked_active_session(session)
    if session.target_reached_at is None:
        raise RecordingWorkflowError("Session has not reached its target duration.")
    session.continued_after_target = True
    session.save(update_fields=("continued_after_target",))
    return session


@transaction.atomic
def finish_recording_session(
    session: RecordingSession,
    *,
    now: datetime | None = None,
) -> RecordingSession:
    """Finish a session normally and complete its enrollment."""
    session = _locked_active_session(session)
    session.status = RecordingSession.Status.FINISHED
    session.ended_at = now or timezone.now()
    session.current_stimulus = None
    session.current_stimulus_index = None
    session.enrollment.status = Enrollment.Status.COMPLETED
    session.enrollment.save(update_fields=("status",))
    session.full_clean()
    session.save()
    return session


@transaction.atomic
def abort_recording_session(
    session: RecordingSession,
    *,
    now: datetime | None = None,
) -> RecordingSession:
    """Abort a session and its enrollment without accepting the current item."""
    session = _locked_active_session(session)
    session.status = RecordingSession.Status.ABORTED
    session.ended_at = now or timezone.now()
    session.current_stimulus = None
    session.current_stimulus_index = None
    session.enrollment.status = Enrollment.Status.ABORTED
    session.enrollment.save(update_fields=("status",))
    session.full_clean()
    session.save()
    return session
