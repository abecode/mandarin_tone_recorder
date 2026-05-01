import csv
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import soundfile as sf


def save_recording(
    audio_tuple,
    stimulus,
    participant,
    quality,
    audio_dir,
    metadata_csv,
):
    if audio_tuple is None:
        raise ValueError("No audio to save.")

    participant_id = participant.get("participant_id", "").strip() or "anonymous"
    session_id = participant.get("session_id", "").strip() or "default_session"

    sample_rate, audio = audio_tuple
    audio = np.asarray(audio)

    if audio.ndim == 2:
        audio = audio.mean(axis=1)

    recording_id = str(uuid.uuid4())
    participant_audio_dir = Path(audio_dir) / participant_id
    participant_audio_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{recording_id}_{stimulus['stimulus_id']}.wav"
    audio_path = participant_audio_dir / filename

    sf.write(audio_path, audio, sample_rate)

    row = {
        "recording_id": recording_id,
        "participant_id": participant_id,
        "session_id": session_id,
        "stimulus_id": stimulus.get("stimulus_id", ""),
        "onset": stimulus.get("onset", ""),
        "medial": stimulus.get("medial", ""),
        "nucleus": stimulus.get("nucleus", ""),
        "coda": stimulus.get("coda", ""),
        "ipa": stimulus.get("ipa", ""),
        "pinyin": stimulus.get("pinyin", ""),
        "ascii": stimulus.get("ascii", ""),
        "tone": stimulus.get("tone", ""),
        "is_attested": stimulus.get("is_attested", ""),
        "audio_path": str(audio_path),
        "sample_rate": quality.get("sample_rate", sample_rate),
        "duration_sec": quality.get("duration_sec", ""),
        "peak_amplitude": quality.get("peak_amplitude", ""),
        "rms": quality.get("rms", ""),
        "clipping_ratio": quality.get("clipping_ratio", ""),
        "quality_pass": quality.get("quality_pass", ""),
        "quality_reason": quality.get("reason", ""),
        "speaker_type": participant.get("speaker_type", ""),
        "mandarin_background": participant.get("mandarin_background", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    metadata_csv = Path(metadata_csv)
    metadata_csv.parent.mkdir(parents=True, exist_ok=True)

    file_exists = metadata_csv.exists()

    with metadata_csv.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

    return recording_id, str(audio_path)
