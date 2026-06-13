"""Participant-session and experiment-routing services."""

from django.db import transaction
from django.http import HttpRequest

from mandarin_tone_recorder.experiments.models import Enrollment, Experiment
from mandarin_tone_recorder.participants.models import Participant


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


@transaction.atomic
def route_participant(participant: Participant) -> Enrollment:
    """Enroll a fully profiled participant in the appropriate experiment."""
    profile = participant.profile
    experiment_slug = (
        "mandarin-tone-reading"
        if profile.knows_mandarin
        else "mandarin-non-tone-reading"
    )
    experiment = Experiment.objects.get(slug=experiment_slug, is_active=True)
    Enrollment.objects.filter(
        participant=participant,
        status=Enrollment.Status.READY,
    ).exclude(experiment=experiment).delete()
    enrollment, _ = Enrollment.objects.get_or_create(
        participant=participant,
        experiment=experiment,
        defaults={
            "routing_reason": (
                "Participant reported Mandarin knowledge."
                if profile.knows_mandarin
                else "Participant reported no Mandarin knowledge."
            )
        },
    )
    return enrollment
