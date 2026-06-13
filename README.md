# Mandarin Tone Recorder

A Django application for Mandarin recording experiments and language practice.

## Development

Install dependencies and apply migrations:

```bash
uv sync
uv run python manage.py migrate
uv run python manage.py import_stimuli
```

The stimulus import is safe to rerun. It imports tones 1-4, creates separate
tone-unspecified prompts, skips tone 5, and excludes syllabic `m` and `n`.

Create an administrator:

```bash
uv run python manage.py createsuperuser
```

Run the development server:

```bash
uv run python manage.py runserver
```
