"""Bootstrap the database from the stimulus CSV.

This script creates base syllables and concrete stimuli:

- tone-bearing stimuli for tones 1-4
- tone-unspecified stimuli with no tone cue

It can be run repeatedly; existing rows are skipped.
"""

from pathlib import Path

import pandas as pd
from sqlmodel import Session, select

from mandarin_tone_recorder.config import STIMULI_CSV
from mandarin_tone_recorder.database import engine, init_db
from mandarin_tone_recorder.models import BaseSyllable, ExperimentCondition, Stimulus


def derive_initial(row: dict) -> str:
    """Derive an intuitive Mandarin initial from a stimulus row.

    For now this defaults to the existing onset field. If the CSV later has an
    explicit ``initial`` column, that value is preferred.
    """
    return str(row.get("initial") or row.get("onset") or "")


def derive_rhyme(row: dict) -> str:
    """Derive an intuitive Mandarin rhyme from a stimulus row.

    If the CSV has an explicit ``rhyme`` column, it is used. Otherwise this
    concatenates medial + nucleus + coda. This is simple but useful and keeps
    the more detailed fields available.
    """
    if row.get("rhyme"):
        return str(row["rhyme"])

    return (
        str(row.get("medial") or "")
        + str(row.get("nucleus") or "")
        + str(row.get("coda") or "")
    )


def normalize_ascii(row: dict) -> str:
    """Return the tone-less ASCII syllable form."""
    ascii_value = str(row.get("ascii") or "")
    tone = str(row.get("tone") or "")

    if tone and ascii_value.endswith(tone):
        return ascii_value[: -len(tone)]

    return ascii_value


def import_stimuli(csv_path: Path = STIMULI_CSV) -> None:
    """Import the stimulus CSV into the database.

    The importer assumes the CSV may contain tone-bearing rows. Neutral tone
    rows are not imported as tone-bearing stimuli. A separate tone-unspecified
    stimulus is created once per base syllable.
    """
    init_db()

    df = pd.read_csv(csv_path).fillna("")

    with Session(engine) as session:
        for _, series in df.iterrows():
            row = series.to_dict()

            tone_raw = str(row.get("tone") or "")
            target_tone = int(tone_raw) if tone_raw in {"1", "2", "3", "4"} else None

            base_ascii = normalize_ascii(row)
            if not base_ascii:
                continue

            base = session.exec(
                select(BaseSyllable).where(BaseSyllable.ascii == base_ascii)
            ).first()

            if base is None:
                base = BaseSyllable(
                    ascii=base_ascii,
                    pinyin_base=str(row.get("pinyin_base") or base_ascii),
                    initial=derive_initial(row),
                    rhyme=derive_rhyme(row),
                    onset=str(row.get("onset") or ""),
                    medial=str(row.get("medial") or ""),
                    nucleus=str(row.get("nucleus") or ""),
                    coda=str(row.get("coda") or ""),
                    ipa_base=str(row.get("ipa") or ""),
                )
                session.add(base)
                session.commit()
                session.refresh(base)

            if target_tone is not None:
                stimulus_id = str(row.get("stimulus_id") or f"{base_ascii}{target_tone}")

                existing = session.exec(
                    select(Stimulus).where(Stimulus.stimulus_id == stimulus_id)
                ).first()

                if existing is None:
                    stimulus = Stimulus(
                        stimulus_id=stimulus_id,
                        base_syllable_id=base.id,
                        experiment_condition=ExperimentCondition.TONE_BEARING,
                        target_tone=target_tone,
                        display_text=str(row.get("pinyin") or f"{base_ascii}{target_tone}"),
                        prompt_type="pinyin_tone_marked",
                        is_attested=bool(row.get("is_attested", True)),
                    )
                    session.add(stimulus)

            unspecified_id = f"{base_ascii}_unspecified"

            existing_unspecified = session.exec(
                select(Stimulus).where(Stimulus.stimulus_id == unspecified_id)
            ).first()

            if existing_unspecified is None:
                unspecified = Stimulus(
                    stimulus_id=unspecified_id,
                    base_syllable_id=base.id,
                    experiment_condition=ExperimentCondition.TONE_UNSPECIFIED,
                    target_tone=None,
                    display_text=base_ascii,
                    prompt_type="pinyin_unaccented",
                    is_attested=True,
                )
                session.add(unspecified)

        session.commit()


def main() -> None:
    """Command-line entry point for stimulus import."""
    import_stimuli()
    print(f"Imported stimuli from {STIMULI_CSV}")


if __name__ == "__main__":
    main()

    
