from django.db import migrations


EXPERIMENTS = (
    {
        "name": "Mandarin tone reading experiment",
        "slug": "mandarin-tone-reading",
        "track": "tone",
        "target_duration_minutes": 20,
        "is_active": True,
    },
    {
        "name": "Mandarin non-tone reading experiment",
        "slug": "mandarin-non-tone-reading",
        "track": "non-tone",
        "target_duration_minutes": 20,
        "is_active": True,
    },
)


def seed_experiments(apps, schema_editor):
    Experiment = apps.get_model("experiments", "Experiment")
    for experiment in EXPERIMENTS:
        Experiment.objects.update_or_create(
            slug=experiment["slug"],
            defaults=experiment,
        )


def remove_seeded_experiments(apps, schema_editor):
    Experiment = apps.get_model("experiments", "Experiment")
    Experiment.objects.filter(
        slug__in=[experiment["slug"] for experiment in EXPERIMENTS]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("experiments", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_experiments, remove_seeded_experiments),
    ]
