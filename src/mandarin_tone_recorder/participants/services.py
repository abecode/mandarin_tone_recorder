"""Participant-session, assessment-cycle, and experiment-routing services."""

from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone

from mandarin_tone_recorder.experiments.models import (
    AssessmentCycle,
    Enrollment,
    Experiment,
)
from mandarin_tone_recorder.participants.models import (
    Participant,
    ParticipantProfile,
    ParticipantProfileSnapshot,
)


PARTICIPANT_SESSION_KEY = "participant_public_id"


def get_session_participant(request: HttpRequest) -> Participant | None:
    """Return the participant associated with this browser session."""
    public_id = request.session.get(PARTICIPANT_SESSION_KEY)
    if not public_id:
        return None
    return Participant.objects.filter(public_id=public_id).first()


def remember_participant(request: HttpRequest, participant: Participant) -> None:
    """Associate a participant with the current signed Django session."""
    request.session[PARTICIPANT_SESSION_KEY] = str(participant.public_id)


def create_profile_snapshot(
    profile: ParticipantProfile,
    *,
    source: str,
) -> ParticipantProfileSnapshot:
    """Freeze the current participant profile answers for later analysis."""
    languages = [
        {
            "language_tag": language.language_tag,
            "display_name": language.display_name,
            "relationship": language.relationship,
            "proficiency": language.proficiency,
            "other_language_name": language.other_language_name,
            "sort_order": language.sort_order,
        }
        for language in profile.languages.order_by("sort_order", "id")
    ]
    return ParticipantProfileSnapshot.objects.create(
        participant=profile.participant,
        source=source,
        knows_mandarin=profile.knows_mandarin,
        speaker_background=profile.speaker_background,
        mandarin_level=profile.mandarin_level,
        languages=languages,
    )


def default_assessment_cycle_label() -> str:
    """Return the default label for a newly started assessment cycle."""
    return f"{timezone.localdate():%B %Y} assessment"


@transaction.atomic
def get_or_create_active_assessment_cycle(
    participant: Participant,
    *,
    label: str | None = None,
) -> AssessmentCycle:
    """Return this participant's active assessment cycle, creating one if needed."""
    active_cycle = participant.assessment_cycles.filter(
        status=AssessmentCycle.Status.ACTIVE,
    ).first()
    if active_cycle is not None:
        return active_cycle

    snapshot = create_profile_snapshot(
        participant.profile,
        source=ParticipantProfileSnapshot.Source.ASSESSMENT_CYCLE_START,
    )
    return AssessmentCycle.objects.create(
        participant=participant,
        profile_snapshot=snapshot,
        label=label or default_assessment_cycle_label(),
    )


@transaction.atomic
def route_participant(
    participant: Participant,
    *,
    assessment_cycle: AssessmentCycle | None = None,
) -> Enrollment:
    """Enroll a fully profiled participant in the appropriate experiment."""
    profile = participant.profile
    assessment_cycle = assessment_cycle or get_or_create_active_assessment_cycle(
        participant
    )
    if (
        assessment_cycle.enrollments.exists()
        and not _assessment_cycle_has_historical_data(assessment_cycle)
    ):
        assessment_cycle.profile_snapshot = create_profile_snapshot(
            profile,
            source=ParticipantProfileSnapshot.Source.ASSESSMENT_CYCLE_START,
        )
        assessment_cycle.save(update_fields=("profile_snapshot",))
    experiment_slug = (
        "mandarin-tone-reading"
        if profile.knows_mandarin
        else "mandarin-non-tone-reading"
    )
    experiment = Experiment.objects.get(slug=experiment_slug, is_active=True)
    Enrollment.objects.filter(
        participant=participant,
        assessment_cycle=assessment_cycle,
        status=Enrollment.Status.READY,
    ).exclude(experiment=experiment).delete()

    existing_enrollment = Enrollment.objects.filter(
        participant=participant,
        assessment_cycle=assessment_cycle,
        experiment=experiment,
    ).first()
    if (
        existing_enrollment is not None
        and existing_enrollment.status != Enrollment.Status.READY
    ):
        return existing_enrollment

    snapshot = create_profile_snapshot(
        profile,
        source=ParticipantProfileSnapshot.Source.EXPERIMENT_ROUTING,
    )
    enrollment, _ = Enrollment.objects.get_or_create(
        participant=participant,
        assessment_cycle=assessment_cycle,
        experiment=experiment,
        defaults={
            "profile_snapshot": snapshot,
            "routing_reason": (
                "Participant reported Mandarin knowledge."
                if profile.knows_mandarin
                else "Participant reported no Mandarin knowledge."
            )
        },
    )
    enrollment.profile_snapshot = snapshot
    enrollment.save(update_fields=("profile_snapshot",))
    return enrollment


def _assessment_cycle_has_historical_data(
    assessment_cycle: AssessmentCycle,
) -> bool:
    """Return whether a cycle has data that should keep its snapshot immutable."""
    if assessment_cycle.practice_sessions.exists():
        return True
    return assessment_cycle.enrollments.exclude(
        status=Enrollment.Status.READY,
    ).exists()
