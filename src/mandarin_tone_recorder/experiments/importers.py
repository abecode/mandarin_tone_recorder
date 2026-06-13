"""Import reusable stimulus definitions from the generated stimulus CSV."""

import csv
from dataclasses import dataclass
from pathlib import Path

from django.db import transaction

from mandarin_tone_recorder.experiments.models import (
    BaseSyllable,
    Experiment,
    ExperimentStimulus,
    Stimulus,
)


REQUIRED_COLUMNS = {
    "stimulus_id",
    "onset",
    "medial",
    "nucleus",
    "coda",
    "ipa",
    "pinyin",
    "pinyin_number",
    "ascii",
    "tone",
    "is_attested",
}
TONE_EXPERIMENT_SLUG = "mandarin-tone-reading"
NON_TONE_EXPERIMENT_SLUG = "mandarin-non-tone-reading"
EXCLUDED_BASE_SYLLABLES = frozenset({"m", "n"})


@dataclass(frozen=True)
class ImportResult:
    """Counts describing the stimulus catalog after an import."""

    base_syllables: int
    tone_bearing_stimuli: int
    tone_unspecified_stimuli: int
    skipped_tone_five_rows: int
    skipped_duplicate_rows: int
    skipped_excluded_rows: int


def parse_attested(value: str) -> bool:
    """Map explicit false values to false and unknown values to true."""
    return value.strip().lower() not in {"false", "f", "no", "n", "0"}


def derive_pinyin_base(row: dict[str, str]) -> str:
    """Return unaccented Pinyin from the numbered Pinyin column."""
    numbered = row["pinyin_number"].strip()
    if numbered[-1:] in {"1", "2", "3", "4", "5"}:
        return numbered[:-1]
    return row["ascii"].strip()


def validate_columns(fieldnames: list[str] | None) -> None:
    """Raise a useful error when the CSV cannot populate the catalog."""
    columns = set(fieldnames or [])
    missing = sorted(REQUIRED_COLUMNS - columns)
    if missing:
        raise ValueError(f"Stimulus CSV is missing required columns: {missing}")


@transaction.atomic
def import_stimulus_catalog(csv_path: Path) -> ImportResult:
    """Import tones 1-4 and one tone-unspecified prompt per base syllable."""
    tone_experiment = Experiment.objects.get(
        slug=TONE_EXPERIMENT_SLUG,
        is_active=True,
    )
    non_tone_experiment = Experiment.objects.get(
        slug=NON_TONE_EXPERIMENT_SLUG,
        is_active=True,
    )

    imported_bases: set[str] = set()
    imported_tone_stimuli: set[str] = set()
    imported_unspecified_stimuli: set[str] = set()
    imported_tone_keys: set[tuple[str, int]] = set()
    skipped_tone_five_rows = 0
    skipped_duplicate_rows = 0
    skipped_excluded_rows = 0

    with csv_path.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        validate_columns(reader.fieldnames)

        for line_number, row in enumerate(reader, start=2):
            ascii_base = row["ascii"].strip()
            if not ascii_base:
                raise ValueError(f"Missing ASCII syllable on CSV line {line_number}.")
            if ascii_base in EXCLUDED_BASE_SYLLABLES:
                skipped_excluded_rows += 1
                continue

            try:
                tone = int(row["tone"])
            except ValueError as exc:
                raise ValueError(
                    f"Invalid tone {row['tone']!r} on CSV line {line_number}."
                ) from exc

            if tone == 5:
                skipped_tone_five_rows += 1
                continue
            if tone not in {1, 2, 3, 4}:
                raise ValueError(
                    f"Tone must be between 1 and 5 on CSV line {line_number}."
                )

            tone_key = (ascii_base, tone)
            if tone_key in imported_tone_keys:
                skipped_duplicate_rows += 1
                continue
            imported_tone_keys.add(tone_key)

            pinyin_base = derive_pinyin_base(row)
            base, _ = BaseSyllable.objects.update_or_create(
                ascii=ascii_base,
                defaults={
                    "pinyin_base": pinyin_base,
                    "onset": row["onset"].strip(),
                    "medial": row["medial"].strip(),
                    "nucleus": row["nucleus"].strip(),
                    "coda": row["coda"].strip(),
                    "ipa_base": row["ipa"].strip(),
                },
            )
            imported_bases.add(ascii_base)

            stable_id = row["stimulus_id"].strip()
            if not stable_id:
                raise ValueError(f"Missing stimulus ID on CSV line {line_number}.")
            stimulus, _ = Stimulus.objects.update_or_create(
                stable_id=stable_id,
                defaults={
                    "base_syllable": base,
                    "condition": Stimulus.Condition.TONE_BEARING,
                    "target_tone": tone,
                    "display_text": row["pinyin"].strip(),
                    "prompt_type": "pinyin_tone_marked",
                    "is_attested": parse_attested(row["is_attested"]),
                },
            )
            ExperimentStimulus.objects.update_or_create(
                experiment=tone_experiment,
                stimulus=stimulus,
                defaults={"is_active": True},
            )
            imported_tone_stimuli.add(stable_id)

            unspecified_id = f"{ascii_base}_unspecified"
            unspecified, _ = Stimulus.objects.update_or_create(
                stable_id=unspecified_id,
                defaults={
                    "base_syllable": base,
                    "condition": Stimulus.Condition.TONE_UNSPECIFIED,
                    "target_tone": None,
                    "display_text": pinyin_base,
                    "prompt_type": "pinyin_unaccented",
                    "is_attested": True,
                },
            )
            ExperimentStimulus.objects.update_or_create(
                experiment=non_tone_experiment,
                stimulus=unspecified,
                defaults={"is_active": True},
            )
            imported_unspecified_stimuli.add(unspecified_id)

    ExperimentStimulus.objects.filter(
        experiment=tone_experiment,
        stimulus__condition=Stimulus.Condition.TONE_BEARING,
    ).exclude(stimulus__stable_id__in=imported_tone_stimuli).update(is_active=False)
    ExperimentStimulus.objects.filter(
        experiment=non_tone_experiment,
        stimulus__condition=Stimulus.Condition.TONE_UNSPECIFIED,
    ).exclude(stimulus__stable_id__in=imported_unspecified_stimuli).update(
        is_active=False
    )

    return ImportResult(
        base_syllables=len(imported_bases),
        tone_bearing_stimuli=len(imported_tone_stimuli),
        tone_unspecified_stimuli=len(imported_unspecified_stimuli),
        skipped_tone_five_rows=skipped_tone_five_rows,
        skipped_duplicate_rows=skipped_duplicate_rows,
        skipped_excluded_rows=skipped_excluded_rows,
    )
