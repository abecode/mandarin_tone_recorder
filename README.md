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

## Planning/Todos

### Annotatation

Annotation could take different forms.  The two main ways that I can think of are

- verification: is what was recorded correct or not in the annotator's
  judgement (grading)
- recognition: given what is recorded, what does the annotator
  perceive the syllable to be
  - aka blind labeling

These are kind of traditional.  Newer general purpose audio models may
have another way, like

- feedback: given the recording and a prompt, give output describing the recording


### Analytics

- total recordings
- how many recordings per syllable
- recordings per experimental setting
- participant view: how many recordings, what is the target and what is the total
  - progress bar
  - wording:
	- session progress, MM:SS / 20:00 (you may stop at any time)
	- syllable coverage, 42/ 1680 syllables and tones
  - issue: what if we want to have multiple assessments
	- different assessment cycles between enrollment and recording session
	- participant < enrollment < assesssment cycle < recording session
	  - aka, assessment, studyround, collectionperiod, experimentrun,
		experiment cycle
- D3

### Documentation

### recording to s3

### practice decks

Practice decks are a work in progress to help me practice Chinese.
Currently they are just forms that take a list of newline separated
sentences.  You read them and you can show the pinyin if you don't
know it.  Showing the pinyin will be recorded so that eventually it
can be used to recommend characters/sentences to practice.

Practice decks can also be stored in the git repo as YAML files under
`content/practice_decks/`.  This lets curated decks be reviewed in pull requests,
versioned with the code, and imported into Django on a new machine.

The import/export management commands are:

```bash
uv run python manage.py import_practice_decks
uv run python manage.py export_practice_deck <deck_id_or_slug> --deck-version 1
```

The current YAML format uses snake_case keys:

```yaml
slug: django_basics
version: 1
title: Django Basics
activity_type: reading_speaking
response:
  type: audio
items:
  - prompts:
      hanzi: "模型"
    hints:
      pinyin: "mo2 xing2"
      english: "model"
  - prompts:
      hanzi: "视图"
    hints:
      pinyin: "shi4 tu2"
      english: "view"
```

The imported Django deck stores the prompt text and pinyin hint. Other YAML hints,
such as `hints.english`, are preserved in the repo file format for future use but
are not currently stored in the database.

Imported decks use `user=None`, `is_shared=True`, and `is_builtin=True`.  If an
imported deck already has practice sessions, changing its items requires bumping
the YAML `version`; this avoids silently rewriting historical practice data.

For future listening/writing modes, the `activity_type` and `response.type` fields
matter.

Possible activity-types later:

reading_speaking
listening_writing
listening_recognition
translation
character_reading
sentence_shadowing
