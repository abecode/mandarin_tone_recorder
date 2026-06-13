"""Participant workflow URL configuration."""

from django.urls import path

from mandarin_tone_recorder.participants import views


app_name = "participants"

urlpatterns = [
    path("consent/", views.consent, name="consent"),
    path(
        "mandarin-knowledge/",
        views.mandarin_knowledge,
        name="mandarin-knowledge",
    ),
    path(
        "speaker-background/",
        views.speaker_background,
        name="speaker-background",
    ),
    path("mandarin-level/", views.mandarin_level, name="mandarin-level"),
    path(
        "experiments/<slug:slug>/ready/",
        views.experiment_ready,
        name="experiment-ready",
    ),
]
