"""URL routes for Mandarin practice."""

from django.urls import path

from mandarin_tone_recorder.practice import views


app_name = "practice"

urlpatterns = [
    path("", views.landing, name="landing"),
    path("sessions/<int:session_id>/", views.session_detail, name="session"),
    path(
        "sessions/<int:session_id>/next/",
        views.complete_current_attempt,
        name="complete-current-attempt",
    ),
    path(
        "sessions/<int:session_id>/sentence-pinyin/",
        views.sentence_pinyin_hint,
        name="sentence-pinyin-hint",
    ),
    path(
        "sessions/<int:session_id>/character-pinyin/",
        views.character_pinyin_hint,
        name="character-pinyin-hint",
    ),
]
