"""Nginx traffic reporting should be scoped and avoid leaking URLs."""

from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from ops.traffic_report import print_report, summarize_access


class TrafficReportTests(TestCase):
    def setUp(self) -> None:
        self.since = datetime(2026, 11, 3, tzinfo=timezone.utc)

    def line(self, host: str, ip: str, path: str, status: int = 200, method: str = "GET") -> str:
        return (
            f'{host} {ip} - - [03/Nov/2026:12:00:00 +0000] '
            f'"{method} {path} HTTP/1.1" {status} 10 "-" "test" "-"\n'
        )

    def test_only_new_format_for_our_host_is_counted(self) -> None:
        lines = [
            self.line("mantonesarehard.com", "1.2.3.4", "/"),
            self.line("www.mantonesarehard.com", "1.2.3.4", "/", 301),
            self.line("emo20q.org", "1.2.3.4", "/", 404),
            '1.2.3.4 - - [03/Nov/2026:12:00:00 +0000] "GET / HTTP/1.1" 200 10 "-" "test" "-"\n',
        ]
        totals, findings = summarize_access(lines, since=self.since, host="mantonesarehard.com")
        self.assertEqual(totals["requests"], 2)
        self.assertEqual(totals["3xx"], 1)
        self.assertEqual(findings, [])

    def test_burst_and_probe_detection_ignores_query_content(self) -> None:
        lines = [self.line("mantonesarehard.com", "1.2.3.4", "/.env?code=SECRET", 404)] * 60
        totals, findings = summarize_access(lines, since=self.since, host="mantonesarehard.com")
        self.assertEqual(totals["4xx"], 60)
        self.assertEqual(len(findings), 1)
        self.assertIn("60 requests in one minute", findings[0][2])
        self.assertIn("60 probe-path requests", findings[0][2])
        self.assertNotIn("SECRET", repr(findings))

    def test_default_output_hides_addresses_and_queries(self) -> None:
        with TemporaryDirectory() as directory:
            access = Path(directory) / "access.log"
            timestamp = datetime.now(timezone.utc).strftime("%d/%b/%Y:%H:%M:%S %z")
            line = (
                f'mantonesarehard.com 1.2.3.4 - - [{timestamp}] '
                '"GET /wp-admin?code=SECRET HTTP/1.1" 404 10 "-" "test" "-"\n'
            )
            access.write_text(line * 3)
            error = Path(directory) / "error.log"
            error.write_text("")
            output = StringIO()
            with patch("sys.stdout", output):
                print_report(
                    hours=24, max_lines=5, show_ips=False, access_log=access,
                    error_log=error, host="mantonesarehard.com",
                )
            self.assertNotIn("1.2.3.4", output.getvalue())
            self.assertNotIn("SECRET", output.getvalue())
