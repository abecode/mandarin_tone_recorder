"""Django admin configuration for experiments."""

from django.contrib import admin

from mandarin_tone_recorder.experiments.models import (
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
