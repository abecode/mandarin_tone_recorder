"""Django admin configuration for recording data."""

from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

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
    exclude = ("raw_audio", "wav_audio")
    readonly_fields = ("raw_audio_download", "wav_audio_download")
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

    @admin.display(description="Raw audio")
    def raw_audio_download(self, obj: RecordingAttempt) -> str:
        if not obj.pk or not obj.raw_audio:
            return "-"
        url = reverse("recordings:download-audio", args=(obj.recording_id, "raw"))
        return format_html('<a href="{}">Download raw audio</a>', url)

    @admin.display(description="WAV audio")
    def wav_audio_download(self, obj: RecordingAttempt) -> str:
        if not obj.pk or not obj.wav_audio:
            return "-"
        url = reverse("recordings:download-audio", args=(obj.recording_id, "wav"))
        return format_html('<a href="{}">Download WAV audio</a>', url)
