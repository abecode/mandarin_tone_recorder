"""Views for Mandarin practice workflows."""

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from mandarin_tone_recorder.practice.forms import PracticeDeckForm
from mandarin_tone_recorder.practice.models import PracticeDeck, PracticeSession
from mandarin_tone_recorder.practice.services import (
    complete_practice_attempt,
    create_practice_session,
    record_character_pinyin_hint,
    record_sentence_pinyin_hint,
    start_next_practice_attempt,
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
@require_GET
def deck_detail(
    request: HttpRequest,
    deck_id: int,
) -> HttpResponse:
    """Preview an available practice deck before starting a session."""
    deck = get_object_or_404(
        visible_practice_decks(request.user).prefetch_related("items"),
        pk=deck_id,
    )
    return render(request, "practice/deck_detail.html", {"deck": deck})


@login_required
@require_POST
def start_deck(
    request: HttpRequest,
    deck_id: int,
) -> HttpResponse:
    """Start a practice session for an available deck."""
    deck = get_object_or_404(PracticeDeck, pk=deck_id)
    try:
        session = create_practice_session(user=request.user, deck=deck)
    except ValueError:
        return HttpResponseBadRequest("Practice deck is not available.")
    return redirect("practice:session", session_id=session.pk)


@login_required
@require_GET
def session_detail(
    request: HttpRequest,
    session_id: int,
) -> HttpResponse:
    """Show the current prompt for one owned practice session."""
    session = get_object_or_404(
        PracticeSession.objects.select_related("deck").prefetch_related("deck__items"),
        pk=session_id,
        user=request.user,
    )
    current_attempt = start_next_practice_attempt(session)
    current_item = current_attempt.item if current_attempt is not None else None
    sentence_pinyin_revealed = False
    if current_attempt is not None and current_item is not None:
        hints = current_attempt.hint_events.all()
        sentence_pinyin_revealed = hints.filter(
            hint_type="sentence_pinyin",
        ).exists()
    return render(
        request,
        "practice/session_detail.html",
        {
            "session": session,
            "current_attempt": current_attempt,
            "current_item": current_item,
            "sentence_pinyin_revealed": sentence_pinyin_revealed,
        },
    )


@login_required
@require_POST
def complete_current_attempt(
    request: HttpRequest,
    session_id: int,
) -> HttpResponse:
    """Complete the active prompt attempt and advance the session."""
    session = get_object_or_404(PracticeSession, pk=session_id, user=request.user)
    attempt = session.attempts.filter(completed_at__isnull=True).first()
    if attempt is None:
        return HttpResponseBadRequest("No active practice attempt.")

    try:
        response_time_ms = int(request.POST.get("response_time_ms", ""))
    except ValueError:
        return HttpResponseBadRequest("Response time is required.")
    if response_time_ms < 0:
        return HttpResponseBadRequest("Response time cannot be negative.")

    complete_practice_attempt(attempt, response_time_ms=response_time_ms)
    return redirect("practice:session", session_id=session.pk)


@login_required
@require_POST
def sentence_pinyin_hint(
    request: HttpRequest,
    session_id: int,
) -> JsonResponse:
    """Record that the current prompt's sentence pinyin was revealed."""
    session = get_object_or_404(PracticeSession, pk=session_id, user=request.user)
    attempt = session.attempts.filter(completed_at__isnull=True).first()
    if attempt is None:
        return JsonResponse({"ok": False, "error": "No active practice attempt."}, status=400)
    try:
        revealed_at_ms = int(request.POST.get("revealed_at_ms", ""))
    except ValueError:
        revealed_at_ms = None

    record_sentence_pinyin_hint(attempt=attempt, revealed_at_ms=revealed_at_ms)
    return JsonResponse({"ok": True})


@login_required
@require_POST
def character_pinyin_hint(
    request: HttpRequest,
    session_id: int,
) -> JsonResponse:
    """Record that one current-prompt character's pinyin was revealed."""
    session = get_object_or_404(PracticeSession, pk=session_id, user=request.user)
    attempt = session.attempts.filter(completed_at__isnull=True).first()
    if attempt is None:
        return JsonResponse({"ok": False, "error": "No active practice attempt."}, status=400)

    try:
        character_index = int(request.POST.get("character_index", ""))
    except ValueError:
        return JsonResponse({"ok": False, "error": "Character index is required."}, status=400)

    try:
        revealed_at_ms = int(request.POST.get("revealed_at_ms", ""))
    except ValueError:
        revealed_at_ms = None

    try:
        hint = record_character_pinyin_hint(
            attempt=attempt,
            character_index=character_index,
            revealed_at_ms=revealed_at_ms,
        )
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    return JsonResponse({"ok": True, "character": hint.character})
