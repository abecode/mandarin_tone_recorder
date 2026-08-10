"""Import repo-backed practice decks from YAML files."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from mandarin_tone_recorder.practice.deck_files import (
    PracticeDeckFileError,
    default_practice_deck_directory,
    import_practice_deck_directory,
)


class Command(BaseCommand):
    help = "Import YAML practice decks from content/practice_decks."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--directory",
            type=Path,
            default=default_practice_deck_directory(),
            help="Directory containing .yaml or .yml practice deck files.",
        )

    def handle(self, *args, **options) -> None:
        try:
            summary = import_practice_deck_directory(options["directory"])
        except PracticeDeckFileError as exc:
            raise CommandError(str(exc)) from exc

        for result in summary.results:
            action = "Created" if result.created else "Updated"
            self.stdout.write(
                f"{action} {result.deck.slug} v{result.deck.version} "
                f"from {result.path} ({result.item_count} item(s))"
            )
        self.stdout.write(
            self.style.SUCCESS(f"Imported {summary.imported_count} practice deck(s).")
        )

