"""Production deployment must not use development host or storage settings."""

from pathlib import Path
from types import SimpleNamespace

from django.test import SimpleTestCase

from ops.check_deploy import validate


class DeploymentSettingsTests(SimpleTestCase):
    def config(self, **overrides: object) -> SimpleNamespace:
        values = {
            "DEBUG": False,
            "ALLOWED_HOSTS": ["study.example.org"],
            "DATABASES": {
                "default": {"NAME": "/var/lib/mandarin-tone-recorder/django.sqlite3"}
            },
            "MEDIA_ROOT": "/var/lib/mandarin-tone-recorder/media",
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_valid_production_paths(self) -> None:
        validate(
            "study.example.org", Path("/var/lib/mandarin-tone-recorder"),
            config=self.config(),
        )

    def test_debug_mode_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "DJANGO_DEBUG"):
            validate(
                "study.example.org", Path("/var/lib/mandarin-tone-recorder"),
                config=self.config(DEBUG=True),
            )

    def test_unknown_host_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "DJANGO_ALLOWED_HOSTS"):
            validate(
                "study.example.org", Path("/var/lib/mandarin-tone-recorder"),
                config=self.config(ALLOWED_HOSTS=["other.example.org"]),
            )
