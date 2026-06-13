"""Convenience entry point for running the Django development server."""

import os

from django.core.management import execute_from_command_line


def main() -> None:
    """Run Django's development server on the recorder's historical port."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mandarin_tone_recorder.settings")
    execute_from_command_line(["django-admin", "runserver", "127.0.0.1:7860"])
