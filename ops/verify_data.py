"""Check that database audio references resolve to files after a move."""

import os


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mandarin_tone_recorder.settings")

    import django

    django.setup()

    from mandarin_tone_recorder.participants.models import Participant
    from mandarin_tone_recorder.recordings.models import RecordingAttempt

    missing = []
    attempts = RecordingAttempt.objects.all().values_list(
        "recording_id", "raw_audio", "wav_audio"
    )
    for recording_id, raw_name, wav_name in attempts.iterator():
        for field_name, name in (("raw_audio", raw_name), ("wav_audio", wav_name)):
            if name and not RecordingAttempt._meta.get_field(field_name).storage.exists(name):
                missing.append(f"{recording_id}: {name}")

    print(f"Participants: {Participant.objects.count()}")
    print(f"Recording attempts: {RecordingAttempt.objects.count()}")
    print(f"Missing audio files: {len(missing)}")
    for item in missing[:20]:
        print(item)
    if missing:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
