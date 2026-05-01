import numpy as np


def analyze_audio(audio_tuple, min_duration_sec, max_duration_sec,
                  clipping_threshold, silence_rms_threshold):
    """
    Gradio Audio with type='numpy' returns: (sample_rate, numpy_array)
    The array may be int or float, mono or stereo.
    """
    if audio_tuple is None:
        return {
            "quality_pass": False,
            "reason": "No audio received.",
        }

    sample_rate, audio = audio_tuple

    audio = np.asarray(audio)

    if audio.ndim == 2:
        audio = audio.mean(axis=1)

    # Normalize if integer PCM
    if np.issubdtype(audio.dtype, np.integer):
        max_val = np.iinfo(audio.dtype).max
        audio = audio.astype(np.float32) / max_val
    else:
        audio = audio.astype(np.float32)

    duration_sec = len(audio) / sample_rate if sample_rate else 0.0
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    rms = float(np.sqrt(np.mean(audio ** 2))) if len(audio) else 0.0
    clipping_ratio = float(np.mean(np.abs(audio) >= clipping_threshold)) if len(audio) else 0.0

    problems = []

    if duration_sec < min_duration_sec:
        problems.append("too short")
    if duration_sec > max_duration_sec:
        problems.append("too long")
    if rms < silence_rms_threshold:
        problems.append("too quiet / likely silence")
    if clipping_ratio > 0.001:
        problems.append("possible clipping")

    return {
        "quality_pass": len(problems) == 0,
        "reason": "OK" if not problems else "; ".join(problems),
        "sample_rate": sample_rate,
        "duration_sec": round(duration_sec, 3),
        "peak_amplitude": round(peak, 5),
        "rms": round(rms, 5),
        "clipping_ratio": round(clipping_ratio, 5),
    }
