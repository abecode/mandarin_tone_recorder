"""URL routes for Mandarin practice."""

from django.urls import path

from mandarin_tone_recorder.practice import views


app_name = "practice"

urlpatterns = [
    path("", views.landing, name="landing"),
]
