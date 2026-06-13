"""Participant-owned recording pages and JSON endpoints."""

import json
from datetime import UTC, datetime
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    JsonResponse,
)
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from mandarin_tone_recorder.experiments.models import Enrollment, Stimulus
from mandarin_tone_recorder.participants.models import Participant
from mandarin_tone_recorder.participants.views import participant_required
from mandarin_tone_recorder.recordings.models import (
    RecordingAttempt,
    RecordingSession,
)
from mandarin_tone_recorder.recordings.services import (
    RecordingWorkflowError,
    abort_recording_session,
    continue_after_target,
    finish_recording_session,
    record_accepted_attempt,
    record_retry_attempt,
    start_recording_session,
)


def stimulus_data(stimulus: Stimulus | None) -> dict[str, Any] | None:
    """Return the browser-facing representation of a stimulus."""
    if stimulus is None:
        return None
    base = stimulus.base_syllable
    return {
        "stable_id": stimulus.stable_id,
        "display_text": stimulus.display_text,
        "condition": stimulus.condition,
        "target_tone": stimulus.target_tone,
        "ascii": base.ascii,
        "pinyin_base": base.pinyin_base,
        "onset": base.onset,
        "rhyme": f"{base.medial}{base.nucleus}{base.coda}",
        "ipa_base": base.ipa_base,
    }


def session_for_participant(
    participant: Participant,
    public_id: str,
) -> RecordingSession | None:
    """Load a recording session only through its owning participant."""
    return (
        RecordingSession.objects.select_related(
            "enrollment__experiment",
            "current_stimulus__base_syllable",
        )
        .filter(
            public_id=public_id,
            enrollment__participant=participant,
        )
        .first()
    )


def parse_timestamp_ms(value: str | None) -> datetime | None:
    """Convert an optional browser epoch-millisecond timestamp."""
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=UTC)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Invalid recording timestamp.") from exc


def workflow_error(exc: RecordingWorkflowError) -> JsonResponse:
    """Return a consistent conflict response for invalid session state."""
    return JsonResponse({"ok": False, "error": str(exc)}, status=409)


@participant_required
@require_POST
def start(
    request: HttpRequest,
    participant: Participant,
    enrollment_id: int,
) -> HttpResponse:
    """Start or resume the participant's routed recording enrollment."""
    enrollment = participant.enrollments.filter(pk=enrollment_id).first()
    if enrollment is None:
        return HttpResponseBadRequest("Enrollment does not belong to participant.")

    active_session = enrollment.recording_sessions.filter(
        status=RecordingSession.Status.ACTIVE
    ).first()
    if active_session is not None:
        return redirect("recordings:session", public_id=active_session.public_id)

    try:
        session = start_recording_session(enrollment)
    except RecordingWorkflowError as exc:
        return HttpResponseBadRequest(str(exc))
    return redirect("recordings:session", public_id=session.public_id)


@participant_required
@require_GET
@ensure_csrf_cookie
def session_page(
    request: HttpRequest,
    participant: Participant,
    public_id: str,
) -> HttpResponse:
    """Render the browser recorder for an owned active session."""
    session = session_for_participant(participant, public_id)
    if session is None:
        return HttpResponseBadRequest("Recording session was not found.")
    if session.status != RecordingSession.Status.ACTIVE:
        return render(
            request,
            "recordings/session_complete.html",
            {"session": session},
        )
    return render(
        request,
        "recordings/recorder.html",
        {
            "session": session,
            "recorder_config": {
                "session_id": str(session.public_id),
                "stimulus": stimulus_data(session.current_stimulus),
                "stimulus_index": session.current_stimulus_index,
                "continued_after_target": session.continued_after_target,
                "target_pending": bool(
                    session.target_reached_at and not session.continued_after_target
                ),
                "max_duration_seconds": getattr(
                    settings,
                    "RECORDING_MAX_DURATION_SECONDS",
                    7,
                ),
                "post_click_buffer_ms": getattr(
                    settings,
                    "RECORDING_POST_CLICK_BUFFER_MS",
                    500,
                ),
            },
        },
    )


@participant_required
@require_POST
def accepted_attempt(
    request: HttpRequest,
    participant: Participant,
    public_id: str,
) -> JsonResponse:
    """Store an accepted audio attempt and return the next state."""
    session = session_for_participant(participant, public_id)
    if session is None:
        return JsonResponse({"ok": False, "error": "Session not found."}, status=404)
    stimulus = Stimulus.objects.filter(stable_id=request.POST.get("stimulus_id")).first()
    audio = request.FILES.get("audio")
    if stimulus is None or audio is None:
        return JsonResponse(
            {"ok": False, "error": "Stimulus and audio are required."},
            status=400,
        )
    try:
        duration_seconds = float(request.POST.get("duration_seconds", ""))
        result = record_accepted_attempt(
            session,
            stimulus,
            raw_audio=audio,
            duration_seconds=duration_seconds,
            mime_type=request.POST.get("mime_type", audio.content_type or ""),
            started_at=parse_timestamp_ms(request.POST.get("started_at_ms")),
            ended_at=parse_timestamp_ms(request.POST.get("ended_at_ms")),
        )
    except (TypeError, ValueError, ValidationError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    except RecordingWorkflowError as exc:
        return workflow_error(exc)

    return JsonResponse(
        {
            "ok": True,
            "session_done": result.session_done,
            "target_reached": result.target_reached_now,
            "next_stimulus": stimulus_data(result.next_stimulus),
            "next_index": (
                None
                if result.session_done
                else result.attempt.stimulus_index + 1
            ),
        }
    )


@participant_required
@require_POST
def retry_attempt(
    request: HttpRequest,
    participant: Participant,
    public_id: str,
) -> JsonResponse:
    """Store a timeout or redo event without advancing the stimulus."""
    session = session_for_participant(participant, public_id)
    if session is None:
        return JsonResponse({"ok": False, "error": "Session not found."}, status=404)
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Invalid JSON."}, status=400)

    stimulus = Stimulus.objects.filter(stable_id=payload.get("stimulus_id")).first()
    status = payload.get("status")
    if stimulus is None:
        return JsonResponse({"ok": False, "error": "Stimulus not found."}, status=400)
    try:
        result = record_retry_attempt(
            session,
            stimulus,
            status=status,
            duration_seconds=float(payload.get("duration_seconds", 0)),
        )
    except (TypeError, ValueError, ValidationError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    except RecordingWorkflowError as exc:
        return workflow_error(exc)
    return JsonResponse(
        {
            "ok": True,
            "next_stimulus": stimulus_data(result.next_stimulus),
            "next_index": result.attempt.stimulus_index,
        }
    )


def session_action(
    participant: Participant,
    public_id: str,
    action: str,
) -> JsonResponse:
    """Run a participant-owned session transition."""
    session = session_for_participant(participant, public_id)
    if session is None:
        return JsonResponse({"ok": False, "error": "Session not found."}, status=404)
    try:
        if action == "continue":
            continue_after_target(session)
        elif action == "finish":
            finish_recording_session(session)
        else:
            abort_recording_session(session)
    except RecordingWorkflowError as exc:
        return workflow_error(exc)
    return JsonResponse({"ok": True})


@participant_required
@require_POST
def continue_session(
    request: HttpRequest,
    participant: Participant,
    public_id: str,
) -> JsonResponse:
    return session_action(participant, public_id, "continue")


@participant_required
@require_POST
def finish_session(
    request: HttpRequest,
    participant: Participant,
    public_id: str,
) -> JsonResponse:
    return session_action(participant, public_id, "finish")


@participant_required
@require_POST
def abort_session(
    request: HttpRequest,
    participant: Participant,
    public_id: str,
) -> JsonResponse:
    return session_action(participant, public_id, "abort")
