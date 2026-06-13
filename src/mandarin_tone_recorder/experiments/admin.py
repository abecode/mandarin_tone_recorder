"""Django admin configuration for experiments."""

from django.contrib import admin

from mandarin_tone_recorder.experiments.models import Enrollment, Experiment


admin.site.register(Experiment)
admin.site.register(Enrollment)
