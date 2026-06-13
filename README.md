# Mandarin Tone Recorder

A Django application for Mandarin recording experiments and language practice.

## Development

Install dependencies and apply migrations:

```bash
uv sync
uv run python manage.py migrate
```

Create an administrator:

```bash
uv run python manage.py createsuperuser
```

Run the development server:

```bash
uv run python manage.py runserver
```
