"""Django admin configuration for experiments."""

from django.contrib import admin

from mandarin_tone_recorder.experiments.models import (
    AssessmentCycle,
    BaseSyllable,
    Enrollment,
    Experiment,
    ExperimentStimulus,
    Stimulus,
)


admin.site.register(BaseSyllable)
admin.site.register(Stimulus)
admin.site.register(Experiment)
admin.site.register(ExperimentStimulus)
admin.site.register(Enrollment)


@admin.register(AssessmentCycle)
class AssessmentCycleAdmin(admin.ModelAdmin):
    list_display = (
        "label",
        "participant",
        "status",
        "started_at",
        "completed_at",
        "closed_at",
    )
    list_filter = ("status", "started_at", "completed_at", "closed_at")
    search_fields = ("label", "participant__public_id")
