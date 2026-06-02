This a research-oriented application for recording Mandarin tones.

first bootstrap the db:

```
uv run python -m mandarin_tone_recorder.db_bootstrap
```


then start the app:
```
uv run uvicorn app:app --reload --port 7860
```
