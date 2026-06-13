"""Import the generated Mandarin stimulus catalog."""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from mandarin_tone_recorder.experiments.importers import import_stimulus_catalog


class Command(BaseCommand):
    help = "Import tones 1-4 and tone-unspecified prompts from a stimulus CSV."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--csv",
            dest="csv_path",
            type=Path,
            default=settings.BASE_DIR / "stimuli" / "syllables.csv",
            help="Path to the generated stimulus CSV.",
        )

    def handle(self, *args: object, **options: object) -> None:
        csv_path = options["csv_path"]
        if not isinstance(csv_path, Path):
            raise CommandError("Invalid CSV path.")
        if not csv_path.is_file():
            raise CommandError(f"Stimulus CSV does not exist: {csv_path}")

        try:
            result = import_stimulus_catalog(csv_path)
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                "Imported "
                f"{result.base_syllables} base syllables, "
                f"{result.tone_bearing_stimuli} tone-bearing stimuli, and "
                f"{result.tone_unspecified_stimuli} tone-unspecified stimuli; "
                f"skipped {result.skipped_tone_five_rows} tone-5 rows and "
                f"{result.skipped_duplicate_rows} duplicate rows, plus "
                f"{result.skipped_excluded_rows} rows for excluded syllables."
            )
        )
