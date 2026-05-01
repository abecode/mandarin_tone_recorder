#!/usr/bin/env python3
"""
Convert a base Mandarin syllable CSV into an expanded stimulus CSV.

Input columns expected:
    onset, medial, nucleus, coda, ipa, pinyin, ascii

Special input-line conventions:
    - Lines whose first non-whitespace character is '#' are skipped entirely.
      These are treated as non-existent syllables.
    - Lines whose final marker is '#', '#!', etc. are kept, but marked rare.
      Example: ",,a,,a,a,a #!" -> kept as ascii "a" with is_rare=True.

Output columns:
    stimulus_id, base_id, onset, medial, nucleus, coda, ipa,
    pinyin, pinyin_number, ascii, tone, is_attested,
    is_rare, rarity, source_row, original_line_number

Example:
    uv run python scripts/make_stimuli.py syllables.csv stimuli/syllables.csv
"""

from __future__ import annotations

import argparse
import re
import unicodedata
from io import StringIO
from pathlib import Path

import pandas as pd


TONE_MARKS = {
    "a": ["ā", "á", "ǎ", "à"],
    "e": ["ē", "é", "ě", "è"],
    "i": ["ī", "í", "ǐ", "ì"],
    "o": ["ō", "ó", "ǒ", "ò"],
    "u": ["ū", "ú", "ǔ", "ù"],
    "ü": ["ǖ", "ǘ", "ǚ", "ǜ"],
}

VOWELS = set("aeiouü")
REQUIRED_COLUMNS = ["onset", "medial", "nucleus", "coda", "ipa", "pinyin", "ascii"]


def strip_newline(line: str) -> tuple[str, str]:
    """Return line content without newline plus the original newline suffix."""
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n"):
        return line[:-1], "\n"
    if line.endswith("\r"):
        return line[:-1], "\r"
    return line, ""


def remove_trailing_rare_marker(line: str) -> tuple[str, bool]:
    """
    Remove a final rare-syllable marker and report whether it was present.

    This intentionally only handles markers at the END of a row, e.g.:
        ri #!
        en #
        ang#

    Lines that START with '#' are handled elsewhere and skipped entirely.
    """
    content, newline = strip_newline(line)

    # A final marker may be '#', '#!', '#rare', etc. The current source file
    # mostly uses '#!'. We remove it only when it is the final thing on the line.
    cleaned = re.sub(r"\s*#[^,\s]*\s*$", "", content)
    is_rare = cleaned != content
    return cleaned + newline, is_rare


def read_syllable_csv(path: str | Path) -> pd.DataFrame:
    """
    Read a syllable CSV while applying the project's comment conventions.

    Important:
    - Lines starting with '#' are excluded.
    - Lines ending with '#', '#!', etc. are preserved and marked rare.

    Returns a DataFrame with two extra internal columns:
    - __is_rare_source
    - __original_line_number
    """
    path = Path(path)

    kept_lines: list[str] = []
    rare_flags: list[bool] = []
    original_line_numbers: list[int] = []
    skipped_comment_lines = 0
    saw_header = False

    with path.open("r", encoding="utf-8-sig") as f:
        for line_number, line in enumerate(f, start=1):
            if not line.strip():
                if not saw_header:
                    kept_lines.append(line)
                continue

            if line.lstrip().startswith("#"):
                skipped_comment_lines += 1
                continue

            if not saw_header:
                kept_lines.append(line)
                saw_header = True
                continue

            cleaned_line, is_rare = remove_trailing_rare_marker(line)
            kept_lines.append(cleaned_line)
            rare_flags.append(is_rare)
            original_line_numbers.append(line_number)

    if not kept_lines:
        raise ValueError(f"No usable CSV rows found in {path}")

    df = pd.read_csv(StringIO("".join(kept_lines))).fillna("")

    if len(df) != len(rare_flags):
        raise ValueError(
            "Internal parsing mismatch: number of parsed rows does not match "
            "number of tracked source rows. Check for malformed CSV rows."
        )

    df["__is_rare_source"] = rare_flags
    df["__original_line_number"] = original_line_numbers
    df.attrs["skipped_comment_lines"] = skipped_comment_lines
    return df


def clean_text(value: object) -> str:
    """Normalize cells; turn NaN into '', strip extra whitespace."""
    if pd.isna(value):
        return ""
    return unicodedata.normalize("NFC", str(value).strip())


def clean_pinyin_base(value: object) -> str:
    """Clean base pinyin while preserving ü."""
    text = clean_text(value)
    text = text.split()[0] if text else ""
    return unicodedata.normalize("NFC", text)


def clean_ascii_base(value: object) -> str:
    """
    Clean ASCII pinyin form.

    Convention: ü -> v, so lü becomes lv in ASCII.
    """
    text = clean_text(value)
    text = text.split()[0] if text else ""
    text = text.replace("ü", "v")
    text = re.sub(r"[^A-Za-zvV]", "", text).lower()
    return text


def choose_tone_mark_index(pinyin: str) -> int | None:
    """
    Return the index of the vowel that should carry the tone mark.

    Standard pinyin orthographic rule:
    1. Mark a or e if present.
    2. In ou, mark o.
    3. Otherwise mark the final vowel: iu -> mark u, ui -> mark i.
    """
    pinyin = unicodedata.normalize("NFC", pinyin)

    for preferred in ("a", "e"):
        idx = pinyin.find(preferred)
        if idx >= 0:
            return idx

    idx = pinyin.find("ou")
    if idx >= 0:
        return idx

    vowel_positions = [i for i, ch in enumerate(pinyin) if ch in VOWELS]
    if not vowel_positions:
        return None

    return vowel_positions[-1]


def add_tone_mark(pinyin_base: str, tone: int) -> str:
    """
    Convert base pinyin + tone number into pinyin with tone mark.

    Tone 5 / neutral tone is returned unmarked.
    """
    pinyin_base = unicodedata.normalize("NFC", pinyin_base)

    if tone == 5:
        return pinyin_base

    idx = choose_tone_mark_index(pinyin_base)
    if idx is None:
        return pinyin_base

    vowel = pinyin_base[idx]
    if vowel not in TONE_MARKS:
        return pinyin_base

    marked_vowel = TONE_MARKS[vowel][tone - 1]
    return pinyin_base[:idx] + marked_vowel + pinyin_base[idx + 1:]


def make_base_id(ascii_base: str, source_row: int) -> str:
    """Create a stable base id for the segmental syllable."""
    if ascii_base:
        return ascii_base
    return f"row{source_row:04d}"


def convert_syllables(
    input_csv: Path,
    output_csv: Path,
    tones: list[int],
    assume_attested: str = "unknown",
    include_rare: bool = True,
) -> pd.DataFrame:
    source = read_syllable_csv(input_csv)

    missing = [col for col in REQUIRED_COLUMNS if col not in source.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    rows = []
    seen_stimulus_ids: set[str] = set()

    for source_row, row in source.reset_index(drop=True).iterrows():
        is_rare = bool(row.get("__is_rare_source", False))
        if is_rare and not include_rare:
            continue

        pinyin_base = clean_pinyin_base(row["pinyin"])
        ascii_base = clean_ascii_base(row["ascii"])
        base_id = make_base_id(ascii_base, source_row)

        for tone in tones:
            pinyin_marked = add_tone_mark(pinyin_base, tone)
            pinyin_number = f"{pinyin_base}{tone}"
            stimulus_id = f"{ascii_base}{tone}" if ascii_base else f"row{source_row:04d}_{tone}"

            # If duplicate base syllables exist, avoid duplicate stimulus IDs.
            if stimulus_id in seen_stimulus_ids:
                stimulus_id = f"{stimulus_id}_row{source_row:04d}"
            seen_stimulus_ids.add(stimulus_id)

            rows.append(
                {
                    "stimulus_id": stimulus_id,
                    "base_id": base_id,
                    "onset": clean_text(row["onset"]),
                    "medial": clean_text(row["medial"]),
                    "nucleus": clean_text(row["nucleus"]),
                    "coda": clean_text(row["coda"]),
                    "ipa": clean_text(row["ipa"]),
                    "pinyin": pinyin_marked,
                    "pinyin_number": pinyin_number,
                    "ascii": ascii_base,
                    "tone": tone,
                    "is_attested": assume_attested,
                    "is_rare": is_rare,
                    "rarity": "rare" if is_rare else "common",
                    "source_row": source_row,
                    "original_line_number": int(row["__original_line_number"]),
                }
            )

    output = pd.DataFrame(rows)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(output_csv, index=False, encoding="utf-8")
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Expand a Mandarin syllable CSV into tone-specific recording stimuli."
    )
    parser.add_argument("input_csv", type=Path)
    parser.add_argument("output_csv", type=Path)
    parser.add_argument(
        "--tones",
        default="1,2,3,4,5",
        help="Comma-separated tones to generate, e.g. '1,2,3,4' or '1,2,3,4,5'.",
    )
    parser.add_argument(
        "--assume-attested",
        default="unknown",
        choices=["unknown", "true", "false"],
        help=(
            "Value to put in is_attested. Without a lexicon this script cannot know "
            "which syllable-tone combinations are real Mandarin lexical combinations."
        ),
    )
    parser.add_argument(
        "--exclude-rare",
        action="store_true",
        help="Exclude rows marked rare by a trailing # / #! marker. Default is to keep them.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tones = [int(t.strip()) for t in args.tones.split(",") if t.strip()]
    invalid = [t for t in tones if t not in {1, 2, 3, 4, 5}]
    if invalid:
        raise ValueError(f"Invalid tones: {invalid}")

    output = convert_syllables(
        input_csv=args.input_csv,
        output_csv=args.output_csv,
        tones=tones,
        assume_attested=args.assume_attested,
        include_rare=not args.exclude_rare,
    )

    n_rare = int(output["is_rare"].sum()) if not output.empty else 0
    n_common = len(output) - n_rare
    print(f"Wrote {len(output)} stimulus rows to {args.output_csv}")
    print(f"Common stimulus rows: {n_common}")
    print(f"Rare stimulus rows: {n_rare}")


if __name__ == "__main__":
    main()
