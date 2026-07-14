"""Views for Mandarin practice workflows."""

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from mandarin_tone_recorder.practice.forms import PracticeDeckForm
from mandarin_tone_recorder.practice.models import PracticeSession
from mandarin_tone_recorder.practice.services import (
    create_practice_session,
    visible_practice_decks,
)


@login_required
@require_http_methods(["GET", "POST"])
def landing(request: HttpRequest) -> HttpResponse:
    """Create practice decks and show decks available to the user."""
    form = PracticeDeckForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        deck = form.save(user=request.user)
        session = create_practice_session(user=request.user, deck=deck)
        return redirect("practice:session", session_id=session.pk)

    return render(
        request,
        "practice/landing.html",
        {
            "form": form,
            "decks": visible_practice_decks(request.user),
        },
    )


@login_required
@require_http_methods(["GET"])
def session_detail(
    request: HttpRequest,
    session_id: int,
) -> HttpResponse:
    """Show the placeholder page for one owned practice session."""
    session = get_object_or_404(
        PracticeSession.objects.select_related("deck").prefetch_related("deck__items"),
        pk=session_id,
        user=request.user,
    )
    first_item = session.deck.items.first()
    return render(
        request,
        "practice/session_detail.html",
        {
            "session": session,
            "first_item": first_item,
        },
    )
