"""Django admin configuration for participants."""

from django.contrib import admin

from mandarin_tone_recorder.participants.models import (
    Consent,
    Participant,
    ParticipantLanguage,
    ParticipantProfile,
    ParticipantProfileSnapshot,
    ParticipationCode,
)


@admin.register(ParticipationCode)
class ParticipationCodeAdmin(admin.ModelAdmin):
    list_display = ("code", "label", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "label")


@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = ("public_id", "user", "participation_code", "created_at")
    list_filter = ("participation_code",)
    search_fields = ("public_id", "user__username")


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


@admin.register(Consent)
class ConsentAdmin(admin.ModelAdmin):
    list_display = (
        "participant",
        "version",
        "share_recordings_on_huggingface",
        "accepted_at",
        "withdrawn_at",
    )
    list_filter = ("version", "share_recordings_on_huggingface", "accepted_at")
    search_fields = ("participant__public_id",)


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
