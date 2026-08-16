"""Import one repo-backed practice deck from a YAML file."""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from mandarin_tone_recorder.practice.deck_files import (
    PracticeDeckFileError,
    import_practice_deck_file,
)


class Command(BaseCommand):
    help = "Import one YAML practice deck."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "path",
            type=Path,
            help="Path to a .yaml or .yml practice deck file.",
        )

    def handle(self, *args, **options) -> None:
        try:
            result = import_practice_deck_file(
                options["path"],
                base_dir=settings.BASE_DIR,
            )
        except PracticeDeckFileError as exc:
            raise CommandError(str(exc)) from exc

        action = "Created" if result.created else "Updated"
        self.stdout.write(
            f"{action} {result.deck.slug} v{result.deck.version} "
            f"from {result.path} ({result.item_count} item(s))"
        )
        self.stdout.write(self.style.SUCCESS("Imported 1 practice deck."))
