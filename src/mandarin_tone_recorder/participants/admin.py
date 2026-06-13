"""Django admin configuration for participants."""

from django.contrib import admin

from mandarin_tone_recorder.participants.models import (
    Consent,
    Participant,
    ParticipantProfile,
)


admin.site.register(Participant)
admin.site.register(ParticipantProfile)
admin.site.register(Consent)
