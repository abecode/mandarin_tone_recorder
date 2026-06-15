# Data Dir

This directory contents is not checked into git to keep the data
private, but the directory needs to be here to run the application.

The current database is django.sqlite3.  The old one (for git tag:
fastapi-prototype) is in mandarin_tone_recorder.sqilte3)


the data directory layout is 
media/recordings/<public_participant_id>/<public_session_id>/<session_seq_no>_<attempt_seq_no>_stimulus_<public_response_id>.<media_extention>
e.g.

```
└── media
    └── recordings
        │      
        ├── 3f78693e-7b2d-46d7-a59e-71b01fac14fd
        │   └── f7f2123d-1a6c-4c86-8d11-1d5296d0f1fe
        │       ├── 0001_01_qu_20260615T005542Z_71fe7680-65a7-448d-9af4-6066b80cc91c.webm
        │       ├── 0002_01_qve_20260615T005545Z_e8cc44e4-bbf7-47fe-9f8a-03abae79dde7.webm
        │       ├── 0003_01_gui_20260615T005548Z_10349523-a31f-448f-bf2e-6342e47f31e4.webm
        │       ├── 0004_01_yin_20260615T005552Z_c943ba85-c829-4218-ba85-95b1cbeb53e2.webm
        │       ├── 0005_01_si_20260615T005557Z_94adaed5-8e4e-487c-86c2-654a1ac1fe0e.webm
        │       └── 0006_01_bao_20260615T005601Z_764d2512-f231-4884-a5ce-790874af5fe2.webm
        ├── 70bda6b7-c02d-48e0-8fe8-4183464a0a18
```		

The old data is in audio/ and the format is similar

```.

├── audio
│   │
│   └── p070
│       ├── session_163447d5d72e
│       │   ├── 0001_ang1_ang_0ec868bd.webm
│       │   ├── 0002_men3_men_65b4cddb.webm

```
