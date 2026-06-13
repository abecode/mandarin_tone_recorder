"""Django admin configuration for recording data."""

from django.contrib import admin

from mandarin_tone_recorder.recordings.models import (
    RecordingAttempt,
    RecordingSession,
)


@admin.register(RecordingSession)
class RecordingSessionAdmin(admin.ModelAdmin):
    list_display = (
        "public_id",
        "enrollment",
        "status",
        "started_at",
        "target_reached_at",
        "ended_at",
    )
    list_filter = ("status", "continued_after_target")
    search_fields = ("public_id", "enrollment__participant__public_id")


@admin.register(RecordingAttempt)
class RecordingAttemptAdmin(admin.ModelAdmin):
    list_display = (
        "recording_id",
        "session",
        "stimulus",
        "stimulus_index",
        "attempt_number",
        "status",
    )
    list_filter = ("status", "stimulus__condition")
    search_fields = (
        "recording_id",
        "session__public_id",
        "stimulus__stable_id",
    )
