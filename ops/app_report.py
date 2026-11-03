"""Read-only production counts for the Fabric application report."""

import os
from datetime import timedelta


def main(hours: int) -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mandarin_tone_recorder.settings")

    import django

    django.setup()

    from django.contrib.auth import get_user_model
    from django.db.models import Count, Q
    from django.utils import timezone

    from mandarin_tone_recorder.participants.models import Participant
    from mandarin_tone_recorder.recordings.models import RecordingAttempt, RecordingSession

    since = timezone.now() - timedelta(hours=hours)
    accepted_audio = Q(status=RecordingAttempt.Status.ACCEPTED) & (
        Q(raw_audio__isnull=False) & ~Q(raw_audio="")
        | Q(wav_audio__isnull=False) & ~Q(wav_audio="")
    )
    totals = RecordingAttempt.objects.aggregate(
        all_attempts=Count("pk"),
        accepted_audio=Count("pk", filter=accepted_audio),
        recent_accepted_audio=Count(
            "pk", filter=accepted_audio & Q(created_at__gte=since)
        ),
    )
    print(f"Registered users: {get_user_model().objects.count()}")
    print(f"Participants: {Participant.objects.count()}")
    print(f"Recording sessions: {RecordingSession.objects.count()}")
    print(f"Sessions started in last {hours}h: {RecordingSession.objects.filter(started_at__gte=since).count()}")
    print(f"Recording attempts: {totals['all_attempts']}")
    print(f"Accepted attempts with audio: {totals['accepted_audio']}")
    print(f"Accepted attempts with audio in last {hours}h: {totals['recent_accepted_audio']}")
    print("Attempts by status:")
    for row in RecordingAttempt.objects.values("status").annotate(total=Count("pk")).order_by("status"):
        print(f"  {row['status']}: {row['total']}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=int, required=True)
    args = parser.parse_args()
    main(args.hours)
