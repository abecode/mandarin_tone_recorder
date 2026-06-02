"""Framework-independent storage for recorded stimulus chunks.

This module handles filenames, audio file writing, optional conversion to WAV,
and metadata CSV appending.

It intentionally avoids FastAPI-specific types such as ``UploadFile``. The web
layer should parse the request, read the uploaded bytes, and then call
``save_recording_chunk`` with a plain dataclass. This keeps the storage logic
portable if the project later moves to Django or another framework.
"""

import csv
import re
import shutil
import subprocess
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_metadata_lock = threading.Lock()


def safe_name(value: str) -> str:
    """Convert a value into a conservative filename/path component.

    This is used for participant IDs, session IDs, stimulus labels, and related
    filename pieces. It preserves ASCII letters, digits, underscores, hyphens,
    and periods. Characters such as tone marks or Chinese characters are kept
    in metadata, but removed from filenames for cross-platform safety.

    Parameters
    ----------
    value:
        Input value to sanitize.

    Returns
    -------
    str
        A filename-safe string. If sanitization removes everything, returns
        ``"unknown"``.
    """
    value = str(value).strip()
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"[^A-Za-z0-9_\-\.]+", "", value)
    return value or "unknown"


def extension_from_mime(mime_type: str) -> str:
    """Infer a file extension from a browser audio MIME type.

    Browser ``MediaRecorder`` implementations differ. Chrome often produces
    WebM/Opus, Firefox may produce Ogg/Opus, and Safari may produce MP4-style
    audio. This helper chooses a practical file extension for the raw upload.

    Parameters
    ----------
    mime_type:
        MIME type reported by the browser or upload.

    Returns
    -------
    str
        One of ``"webm"``, ``"ogg"``, ``"m4a"``, or ``"wav"``.
    """
    mime_type = mime_type or ""

    if "mp4" in mime_type:
        return "m4a"
    if "ogg" in mime_type:
        return "ogg"
    if "wav" in mime_type:
        return "wav"
    return "webm"


def convert_to_wav_if_possible(
    input_path: Path,
    *,
    target_sample_rate: int = 16000,
) -> Path | None:
    """Convert an uploaded audio file to mono WAV using ffmpeg if available.

    The browser usually uploads compressed audio such as WebM/Opus. Keeping the
    raw file is useful, but many speech-analysis tools prefer WAV. If ffmpeg is
    installed, this function writes a WAV next to the raw upload.

    Parameters
    ----------
    input_path:
        Path to the raw uploaded audio file.
    target_sample_rate:
        Sample rate for the converted WAV file.

    Returns
    -------
    Path | None
        Path to the WAV file if conversion succeeded. Returns ``None`` if
        ffmpeg is missing or conversion fails. If the input is already WAV,
        returns ``input_path``.
    """
    if input_path.suffix.lower() == ".wav":
        return input_path

    if shutil.which("ffmpeg") is None:
        return None

    wav_path = input_path.with_suffix(".wav")

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-ac",
        "1",
        "-ar",
        str(target_sample_rate),
        str(wav_path),
    ]

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.returncode != 0:
        return None

    return wav_path


@dataclass(frozen=True)
class RecordingChunk:
    """A single recorded audio chunk for one stimulus.

    This dataclass represents the cleaned, framework-independent payload that
    the storage layer needs. A FastAPI route, Django view, CLI script, or test
    can all construct this object without changing the storage implementation.

    Attributes
    ----------
    participant_id:
        Participant identifier entered on the recording page.
    session_id:
        Session identifier entered on the recording page.
    speaker_type:
        Broad speaker category, such as native, heritage, learner, or other.
    mandarin_background:
        Free-text description of Mandarin background.
    stimulus_index:
        One-based position of the stimulus within the current session.
    stimulus_id:
        Stable ID from the stimulus CSV.
    stimulus:
        Full stimulus row dictionary from ``StimulusManager``.
    started_at_ms:
        Browser timestamp in milliseconds when this stimulus segment began.
    ended_at_ms:
        Browser timestamp in milliseconds when this stimulus segment ended.
    mime_type:
        MIME type reported by the browser/upload.
    audio_bytes:
        Raw bytes uploaded from the browser.
    """
    participant_id: str
    session_id: str
    speaker_type: str
    mandarin_background: str

    stimulus_index: int
    stimulus_id: str
    stimulus: dict[str, Any]

    started_at_ms: int
    ended_at_ms: int
    mime_type: str
    audio_bytes: bytes


def save_recording_chunk(
    chunk: RecordingChunk,
    *,
    audio_dir: Path,
    target_sample_rate: int = 16000,
    recording_id: str | None = None,
) -> dict[str, Any]:
    """Save one recording chunk and append its metadata.

    This function writes the raw browser-uploaded audio file, optionally
    converts it to WAV, and appends one row to the project-level metadata CSV.

    Files are stored under:

    ``audio_dir / participant_id / session_id / filename``

    Parameters
    ----------
    chunk:
        The recording chunk to save.
    audio_dir:
        Base directory for audio files.
    metadata_csv:
        Path to the CSV file where metadata rows should be appended.
    target_sample_rate:
        Sample rate for optional WAV conversion.

    Returns
    -------
    dict[str, Any]
        A result dictionary containing the recording ID, file paths, metadata
        path, and the row that was written.
    """
    participant_id = safe_name(chunk.participant_id or "anonymous")
    session_id = safe_name(chunk.session_id or "default_session")

    session_audio_dir = Path(audio_dir) / participant_id / session_id
    session_audio_dir.mkdir(parents=True, exist_ok=True)

    recording_id = recording_id or str(uuid.uuid4())
    ext = extension_from_mime(chunk.mime_type)

    stimulus_label = (
        chunk.stimulus.get("ascii")
        or chunk.stimulus.get("pinyin")
        or chunk.stimulus_id
    )

    filename_base = (
        f"{chunk.stimulus_index:04d}_"
        f"{safe_name(chunk.stimulus_id)}_"
        f"{safe_name(stimulus_label)}_"
        f"{recording_id[:8]}"
    )

    raw_path = session_audio_dir / f"{filename_base}.{ext}"
    raw_path.write_bytes(chunk.audio_bytes)

    wav_path = convert_to_wav_if_possible(
        raw_path,
        target_sample_rate=target_sample_rate,
    )

    duration_sec = (chunk.ended_at_ms - chunk.started_at_ms) / 1000.0

    return {
        "recording_id": recording_id,
        "raw_audio_path": str(raw_path),
        "wav_audio_path": str(wav_path) if wav_path else None,
    }

