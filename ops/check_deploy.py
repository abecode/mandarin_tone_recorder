"""Refuse to start a deployment with development storage or host settings."""

import argparse
import os
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mandarin_tone_recorder.settings")


def validate(domain: str, data_dir: Path, *, config=None) -> None:
    if config is None:
        from django.conf import settings

        config = settings
    if config.DEBUG:
        raise RuntimeError("DJANGO_DEBUG must be 0 on the deployment server.")
    if domain not in config.ALLOWED_HOSTS:
        raise RuntimeError(f"Add {domain} to DJANGO_ALLOWED_HOSTS.")
    data_dir = data_dir.resolve()
    if Path(config.DATABASES["default"]["NAME"]).resolve() != data_dir / "django.sqlite3":
        raise RuntimeError("The database must be in the persistent data directory.")
    if Path(config.MEDIA_ROOT).resolve() != data_dir / "media":
        raise RuntimeError("Media must be in the persistent data directory.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("domain")
    parser.add_argument("data_dir", type=Path)
    args = parser.parse_args()
    validate(args.domain, args.data_dir.resolve())
    print("Production host and persistent paths verified.")
