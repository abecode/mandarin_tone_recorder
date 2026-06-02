"""Project configuration.

This module centralizes filesystem and experiment constants. Keeping these
values here avoids scattering paths and timing settings throughout the app.
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

STIMULI_CSV = BASE_DIR / "stimuli" / "syllables.csv"

DATA_DIR = BASE_DIR / "data"
AUDIO_DIR = DATA_DIR / "audio"
DATABASE_PATH = DATA_DIR / "mandarin_tone_recorder.sqlite3"
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

TARGET_SAMPLE_RATE = 16000

# Per-stimulus recording timeout. This is intentionally not a whole-session
# timeout. A session may last much longer if the participant keeps recording.
MAX_DURATION_SEC = 7.0

# Soft target duration for a session. The app should notify the participant
# when this target is reached, but it should not abruptly stop recording.
DEFAULT_SESSION_TARGET_DURATION_SEC = 10 * 60

MIN_DURATION_SEC = 0.25
CLIPPING_THRESHOLD = 0.99
SILENCE_RMS_THRESHOLD = 0.005

