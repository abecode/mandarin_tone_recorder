"""Recording workflow URL configuration."""

from django.urls import path

from mandarin_tone_recorder.recordings import views


app_name = "recordings"

urlpatterns = [
    path("enrollments/<int:enrollment_id>/start/", views.start, name="start"),
    path("sessions/<uuid:public_id>/", views.session_page, name="session"),
    path(
        "sessions/<uuid:public_id>/attempts/accepted/",
        views.accepted_attempt,
        name="accepted-attempt",
    ),
    path(
        "sessions/<uuid:public_id>/attempts/retry/",
        views.retry_attempt,
        name="retry-attempt",
    ),
    path(
        "sessions/<uuid:public_id>/continue/",
        views.continue_session,
        name="continue",
    ),
    path(
        "sessions/<uuid:public_id>/finish/",
        views.finish_session,
        name="finish",
    ),
    path(
        "sessions/<uuid:public_id>/abort/",
        views.abort_session,
        name="abort",
    ),
]
