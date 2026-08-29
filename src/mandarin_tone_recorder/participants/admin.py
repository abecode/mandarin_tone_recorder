"""Django admin configuration for participants."""

from django.contrib import admin

from mandarin_tone_recorder.participants.models import (
    Consent,
    Participant,
    ParticipantLanguage,
    ParticipantProfile,
    ParticipantProfileSnapshot,
)


admin.site.register(Participant)


class ParticipantLanguageInline(admin.TabularInline):
    model = ParticipantLanguage
    readonly_fields = ("display_name",)
    extra = 0


@admin.register(ParticipantProfile)
class ParticipantProfileAdmin(admin.ModelAdmin):
    inlines = (ParticipantLanguageInline,)
    list_display = (
        "participant",
        "knows_mandarin",
        "speaker_background",
        "mandarin_level",
    )


admin.site.register(Consent)


@admin.register(ParticipantProfileSnapshot)
class ParticipantProfileSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "participant",
        "source",
        "knows_mandarin",
        "speaker_background",
        "mandarin_level",
        "created_at",
    )
    list_filter = ("source", "knows_mandarin", "speaker_background", "mandarin_level")
    readonly_fields = (
        "participant",
        "source",
        "knows_mandarin",
        "speaker_background",
        "mandarin_level",
        "languages",
        "created_at",
    )
    search_fields = ("participant__public_id",)
