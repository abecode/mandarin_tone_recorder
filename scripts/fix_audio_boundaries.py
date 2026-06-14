#!/usr/bin/env python3
"""Repair delayed recording boundaries and convert recordings to 16
kHz PCM WAV.

This was made for data recorded using the fastapi-prototype tag
(before switching to django, so it might not be needed after that.

"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import tempfile
import wave
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


INDEX_RE = re.compile(r"^(\d+)_")
SUPPORTED_SUFFIXES = {".webm", ".wav", ".ogg", ".mp4", ".m4a"}
SAMPLE_RATE = 16_000
CHANNELS = 1
SAMPLE_WIDTH = 2


@dataclass(frozen=True)
class Recording:
    source: Path
    relative: Path
    index: int | None


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def capture(command: list[str]) -> str:
    return subprocess.run(
        command,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout


def decode_to_pcm(source: Path, destination: Path, ffmpeg: str) -> None:
    run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-vn",
            "-ac",
            str(CHANNELS),
            "-ar",
            str(SAMPLE_RATE),
            "-f",
            "s16le",
            str(destination),
        ]
    )


def write_wav(destination: Path, pcm: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(destination), "wb") as output:
        output.setnchannels(CHANNELS)
        output.setsampwidth(SAMPLE_WIDTH)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(pcm)


def output_path(output_root: Path, recording: Recording) -> Path:
    return output_root / recording.relative.with_suffix(".wav")


def numbered_recordings(directory: Path, input_root: Path) -> list[Recording]:
    recordings = []
    for source in sorted(directory.iterdir()):
        if not source.is_file() or source.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        match = INDEX_RE.match(source.name)
        recordings.append(
            Recording(
                source=source,
                relative=source.relative_to(input_root),
                index=int(match.group(1)) if match else None,
            )
        )
    return recordings


def chronological_runs(recordings: list[Recording]) -> list[list[Recording]]:
    ordered = sorted(
        recordings,
        key=lambda recording: (
            recording.source.stat().st_mtime_ns,
            recording.source.name,
        ),
    )
    runs: list[list[Recording]] = []
    for recording in ordered:
        if (
            not runs
            or recording.index is None
            or runs[-1][-1].index is None
            or recording.index <= runs[-1][-1].index
        ):
            runs.append([recording])
        else:
            runs[-1].append(recording)
    return runs


def is_unambiguous_sequence(recordings: list[Recording]) -> bool:
    indices = [recording.index for recording in recordings]
    if not indices or any(index is None for index in indices):
        return False
    counts = Counter(indices)
    return all(count == 1 for count in counts.values())


def has_webm_header(source: Path) -> bool:
    with source.open("rb") as input_file:
        return input_file.read(4) == b"\x1a\x45\xdf\xa3"


def is_continuous_webm(recordings: list[Recording]) -> bool:
    return (
        len(recordings) > 1
        and all(recording.source.suffix.lower() == ".webm" for recording in recordings)
        and has_webm_header(recordings[0].source)
        and all(not has_webm_header(recording.source) for recording in recordings[1:])
    )


def repair_continuous_webm(
    recordings: list[Recording],
    output_root: Path,
    shift_frames: int,
    ffmpeg: str,
    ffprobe: str,
    temp_root: Path,
) -> list[dict[str, str]]:
    combined = temp_root / "combined.webm"
    boundaries = []
    byte_count = 0
    with combined.open("wb") as output:
        for recording in recordings:
            if byte_count:
                boundaries.append(byte_count)
            with recording.source.open("rb") as input_file:
                shutil.copyfileobj(input_file, output)
            byte_count += recording.source.stat().st_size

    packet_data = json.loads(
        capture(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "packet=pts_time,pos",
                "-of",
                "json",
                str(combined),
            ]
        )
    )
    packets = [
        (int(packet["pos"]), float(packet["pts_time"]))
        for packet in packet_data["packets"]
        if "pos" in packet and "pts_time" in packet
    ]
    boundary_frames = []
    for boundary in boundaries:
        try:
            timestamp = next(pts for pos, pts in packets if pos >= boundary)
        except StopIteration as error:
            raise RuntimeError(
                f"Could not map chunk boundary {boundary} in {recordings[0].source.parent}"
            ) from error
        boundary_frames.append(round(timestamp * SAMPLE_RATE))

    pcm_path = temp_root / "combined.pcm"
    decode_to_pcm(combined, pcm_path, ffmpeg)
    pcm = pcm_path.read_bytes()
    total_frames = len(pcm) // (CHANNELS * SAMPLE_WIDTH)
    starts = [0, *boundary_frames]
    ends = [*boundary_frames, total_frames]

    rows = []
    frame_size = CHANNELS * SAMPLE_WIDTH
    for position, recording in enumerate(recordings):
        start = starts[position]
        end = ends[position]
        moved = 0
        if position + 1 < len(recordings):
            moved = min(shift_frames, total_frames - end)
            end += moved
        if position:
            start = min(start + shift_frames, end)
        destination = output_path(output_root, recording)
        write_wav(destination, pcm[start * frame_size : end * frame_size])
        rows.append(
            {
                "source": str(recording.source),
                "output": str(destination),
                "action": "continuous_webm_boundary_shift",
                "moved_from_next_ms": f"{moved * 1000 / SAMPLE_RATE:.3f}",
            }
        )
    return rows


def repair_sequence(
    recordings: list[Recording],
    output_root: Path,
    shift_frames: int,
    ffmpeg: str,
    temp_root: Path,
) -> list[dict[str, str]]:
    pcm_parts: list[bytes] = []
    for position, recording in enumerate(recordings):
        pcm_path = temp_root / f"{position:06d}.pcm"
        decode_to_pcm(recording.source, pcm_path, ffmpeg)
        pcm_parts.append(pcm_path.read_bytes())

    frame_size = CHANNELS * SAMPLE_WIDTH
    rows = []
    for position, (recording, pcm) in enumerate(zip(recordings, pcm_parts)):
        moved = 0
        if position + 1 < len(pcm_parts):
            following = pcm_parts[position + 1]
            moved = min(shift_frames, len(following) // frame_size)
            pcm += following[: moved * frame_size]
            pcm_parts[position + 1] = following[moved * frame_size :]

        destination = output_path(output_root, recording)
        write_wav(destination, pcm)
        rows.append(
            {
                "source": str(recording.source),
                "output": str(destination),
                "action": "boundary_shift",
                "moved_from_next_ms": f"{moved * 1000 / SAMPLE_RATE:.3f}",
            }
        )
    return rows


def convert_individually(
    recordings: list[Recording],
    output_root: Path,
    ffmpeg: str,
    temp_root: Path,
    reason: str,
) -> list[dict[str, str]]:
    rows = []
    for position, recording in enumerate(recordings):
        pcm_path = temp_root / f"single-{position:06d}.pcm"
        decode_to_pcm(recording.source, pcm_path, ffmpeg)
        destination = output_path(output_root, recording)
        write_wav(destination, pcm_path.read_bytes())
        rows.append(
            {
                "source": str(recording.source),
                "output": str(destination),
                "action": reason,
                "moved_from_next_ms": "0.000",
            }
        )
    return rows


def skipped_rows(
    recordings: list[Recording],
    output_root: Path,
    reason: str,
) -> list[dict[str, str]]:
    return [
        {
            "source": str(recording.source),
            "output": str(output_path(output_root, recording)),
            "action": reason,
            "moved_from_next_ms": "0.000",
        }
        for recording in recordings
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/audio"))
    parser.add_argument("--output", type=Path, default=Path("data/audio_fixed"))
    parser.add_argument(
        "--shift-ms",
        type=float,
        default=500.0,
        help="Audio moved from the start of each recording to the prior one.",
    )
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg"))
    parser.add_argument("--ffprobe", default=shutil.which("ffprobe"))
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_root = args.input.resolve()
    output_root = args.output.resolve()
    if not args.ffmpeg or not args.ffprobe:
        raise SystemExit(
            "ffmpeg and ffprobe are required; install them or pass their paths"
        )
    if args.shift_ms < 0:
        raise SystemExit("--shift-ms must be nonnegative")
    if output_root.exists():
        if not args.overwrite:
            raise SystemExit(f"{output_root} exists; pass --overwrite to replace it")
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True)

    directories = sorted(
        {path.parent for path in input_root.rglob("*") if path.is_file()}
    )
    rows: list[dict[str, str]] = []
    shift_frames = round(args.shift_ms * SAMPLE_RATE / 1000)

    with tempfile.TemporaryDirectory(prefix="fix-audio-") as temp:
        temp_root = Path(temp)
        for directory_number, directory in enumerate(directories):
            recordings = numbered_recordings(directory, input_root)
            if not recordings:
                continue
            directory_temp = temp_root / str(directory_number)
            directory_temp.mkdir()
            if is_continuous_webm(recordings):
                rows.extend(
                    repair_continuous_webm(
                        recordings,
                        output_root,
                        shift_frames,
                        args.ffmpeg,
                        args.ffprobe,
                        directory_temp,
                    )
                )
                continue

            headerless = [
                recording
                for recording in recordings
                if recording.source.suffix.lower() == ".webm"
                and not has_webm_header(recording.source)
            ]
            if headerless:
                rows.extend(
                    skipped_rows(
                        headerless,
                        output_root,
                        "skipped_unmappable_headerless_tail",
                    )
                )
                recordings = [
                    recording for recording in recordings if recording not in headerless
                ]

            if len(recordings) > 1 and is_unambiguous_sequence(recordings):
                rows.extend(
                    repair_sequence(
                        recordings,
                        output_root,
                        shift_frames,
                        args.ffmpeg,
                        directory_temp,
                    )
                )
            elif len(recordings) > 1 and all(
                recording.index is not None for recording in recordings
            ):
                for run_number, run_recordings in enumerate(
                    chronological_runs(recordings)
                ):
                    run_temp = directory_temp / str(run_number)
                    run_temp.mkdir()
                    if len(run_recordings) > 1:
                        rows.extend(
                            repair_sequence(
                                run_recordings,
                                output_root,
                                shift_frames,
                                args.ffmpeg,
                                run_temp,
                            )
                        )
                    else:
                        rows.extend(
                            convert_individually(
                                run_recordings,
                                output_root,
                                args.ffmpeg,
                                run_temp,
                                "converted_only_single_file",
                            )
                        )
            else:
                reason = (
                    "converted_only_ambiguous_order"
                    if len(recordings) > 1
                    else "converted_only_single_file"
                )
                rows.extend(
                    convert_individually(
                        recordings,
                        output_root,
                        args.ffmpeg,
                        directory_temp,
                        reason,
                    )
                )

    manifest = output_root / "manifest.csv"
    with manifest.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=("source", "output", "action", "moved_from_next_ms"),
        )
        writer.writeheader()
        writer.writerows(rows)
    written = sum(not row["action"].startswith("skipped_") for row in rows)
    skipped = len(rows) - written
    print(f"Wrote {written} WAV files, skipped {skipped}, and created {manifest}")


if __name__ == "__main__":
    main()
