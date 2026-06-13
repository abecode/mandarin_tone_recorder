"""ASGI config for the Mandarin Tone Recorder project."""

import os

from django.core.asgi import get_asgi_application


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mandarin_tone_recorder.settings")

application = get_asgi_application()
