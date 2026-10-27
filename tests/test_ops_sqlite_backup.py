"""The transfer uses a consistent SQLite snapshot, including WAL changes."""

import sqlite3
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from ops.sqlite_backup import snapshot


class SqliteSnapshotTests(SimpleTestCase):
    def test_snapshot_copies_committed_rows_from_wal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.sqlite3"
            target = Path(directory) / "snapshot.sqlite3"
            with sqlite3.connect(source) as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("CREATE TABLE sample (value TEXT)")
                connection.execute("INSERT INTO sample VALUES ('recorded')")
                connection.commit()
                snapshot(source, target)

            with sqlite3.connect(target) as copy:
                self.assertEqual(
                    copy.execute("SELECT value FROM sample").fetchall(),
                    [("recorded",)],
                )

    def test_snapshot_refuses_to_replace_an_existing_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.sqlite3"
            target = Path(directory) / "snapshot.sqlite3"
            with sqlite3.connect(source):
                pass
            target.write_bytes(b"do not replace")

            with self.assertRaises(FileExistsError):
                snapshot(source, target)

            self.assertEqual(target.read_bytes(), b"do not replace")
