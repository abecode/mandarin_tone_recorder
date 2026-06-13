"""WSGI config for the Mandarin Tone Recorder project."""

import os

from django.core.wsgi import get_wsgi_application


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mandarin_tone_recorder.settings")

application = get_wsgi_application()
