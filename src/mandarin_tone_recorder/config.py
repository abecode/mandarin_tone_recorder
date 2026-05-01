from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
STIMULI_CSV = BASE_DIR / "stimuli" / "syllables.csv"
DATA_DIR = BASE_DIR / "data"
AUDIO_DIR = DATA_DIR / "audio"
METADATA_CSV = DATA_DIR / "metadata.csv"

TARGET_SAMPLE_RATE = 16000
MIN_DURATION_SEC = 0.25
MAX_DURATION_SEC = 3.00
CLIPPING_THRESHOLD = 0.99
SILENCE_RMS_THRESHOLD = 0.005
