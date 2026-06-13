"""Views for consent, participant questions, and experiment routing."""

from collections.abc import Callable
from functools import wraps
from typing import Any

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from mandarin_tone_recorder.participants.forms import (
    ConsentForm,
    MandarinKnowledgeForm,
    MandarinLevelForm,
    SpeakerBackgroundForm,
)
from mandarin_tone_recorder.participants.models import (
    Consent,
    Participant,
    ParticipantProfile,
)
from mandarin_tone_recorder.participants.services import (
    get_session_participant,
    remember_participant,
    route_participant,
)


CONSENT_VERSION = "2026-06-13"
ParticipantView = Callable[..., HttpResponse]


def participant_required(view: ParticipantView) -> ParticipantView:
    """Redirect browsers without accepted consent to the first workflow step."""

    @wraps(view)
    def wrapped(
        request: HttpRequest,
        *args: Any,
        **kwargs: Any,
    ) -> HttpResponse:
        participant = get_session_participant(request)
        if participant is None or not participant.consents.filter(
            version=CONSENT_VERSION,
            withdrawn_at__isnull=True,
        ).exists():
            return redirect("participants:consent")
        return view(request, participant, *args, **kwargs)

    return wrapped


@require_http_methods(["GET", "POST"])
def consent(request: HttpRequest) -> HttpResponse:
    """Explain the study and record affirmative consent."""
    participant = get_session_participant(request)
    if participant and participant.consents.filter(
        version=CONSENT_VERSION,
        withdrawn_at__isnull=True,
    ).exists():
        return redirect("participants:mandarin-knowledge")

    form = ConsentForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        participant = Participant.objects.create(
            user=request.user if request.user.is_authenticated else None
        )
        Consent.objects.create(participant=participant, version=CONSENT_VERSION)
        ParticipantProfile.objects.create(participant=participant)
        remember_participant(request, participant)
        return redirect("participants:mandarin-knowledge")

    return render(
        request,
        "participants/consent.html",
        {"form": form},
    )


@participant_required
@require_http_methods(["GET", "POST"])
def mandarin_knowledge(
    request: HttpRequest,
    participant: Participant,
) -> HttpResponse:
    """Ask whether the participant knows Mandarin and choose the next step."""
    profile = participant.profile
    initial = (
        {"knows_mandarin": profile.knows_mandarin}
        if profile.knows_mandarin is not None
        else None
    )
    form = MandarinKnowledgeForm(
        request.POST if request.method == "POST" else None,
        initial=initial,
    )
    if request.method == "POST" and form.is_valid():
        profile.knows_mandarin = form.cleaned_data["knows_mandarin"]
        if not profile.knows_mandarin:
            profile.speaker_background = ""
            profile.mandarin_level = ""
        profile.save()

        if profile.knows_mandarin:
            return redirect("participants:speaker-background")
        enrollment = route_participant(participant)
        return redirect("participants:experiment-ready", slug=enrollment.experiment.slug)

    return render(
        request,
        "participants/question.html",
        {
            "form": form,
            "heading": "Mandarin experience",
            "step": "Step 2 of 4",
        },
    )


@participant_required
@require_http_methods(["GET", "POST"])
def speaker_background(
    request: HttpRequest,
    participant: Participant,
) -> HttpResponse:
    """Ask Mandarin speakers about their background."""
    profile = participant.profile
    if profile.knows_mandarin is not True:
        return redirect("participants:mandarin-knowledge")

    form = SpeakerBackgroundForm(
        request.POST if request.method == "POST" else None,
        initial={"speaker_background": profile.speaker_background},
    )
    if request.method == "POST" and form.is_valid():
        profile.speaker_background = form.cleaned_data["speaker_background"]
        profile.save()
        return redirect("participants:mandarin-level")

    return render(
        request,
        "participants/question.html",
        {
            "form": form,
            "heading": "Mandarin background",
            "step": "Step 3 of 4",
        },
    )


@participant_required
@require_http_methods(["GET", "POST"])
def mandarin_level(
    request: HttpRequest,
    participant: Participant,
) -> HttpResponse:
    """Ask Mandarin speakers for a broad proficiency self-assessment."""
    profile = participant.profile
    if profile.knows_mandarin is not True:
        return redirect("participants:mandarin-knowledge")
    if not profile.speaker_background:
        return redirect("participants:speaker-background")

    form = MandarinLevelForm(
        request.POST if request.method == "POST" else None,
        initial={"mandarin_level": profile.mandarin_level},
    )
    if request.method == "POST" and form.is_valid():
        profile.mandarin_level = form.cleaned_data["mandarin_level"]
        profile.save()
        enrollment = route_participant(participant)
        return redirect("participants:experiment-ready", slug=enrollment.experiment.slug)

    return render(
        request,
        "participants/question.html",
        {
            "form": form,
            "heading": "Mandarin level",
            "step": "Step 4 of 4",
        },
    )


@participant_required
def experiment_ready(
    request: HttpRequest,
    participant: Participant,
    slug: str,
) -> HttpResponse:
    """Show the placeholder destination for the participant's routed experiment."""
    enrollment = participant.enrollments.select_related("experiment").filter(
        experiment__slug=slug
    ).first()
    if enrollment is None:
        return redirect("participants:mandarin-knowledge")
    return render(
        request,
        "participants/experiment_ready.html",
        {"enrollment": enrollment},
    )
