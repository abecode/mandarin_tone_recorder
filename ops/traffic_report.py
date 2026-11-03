"""Summarize this site's Nginx logs without exposing raw request URLs."""

import argparse
import re
from collections import Counter, defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit


ACCESS_RE = re.compile(
    r'^(?P<host>\S+) (?P<ip>\S+) \S+ \S+ \[(?P<time>[^]]+)\] '
    r'"(?P<request>[^"]*)" (?P<status>\d{3}) '
)
ERROR_RE = re.compile(r"^(?P<time>\d{4}/\d\d/\d\d \d\d:\d\d:\d\d) \[(?P<level>\w+)\] ")
PROBE_PREFIXES = ("/wp-admin", "/wp-login", "/.env", "/.git", "/xmlrpc.php", "/phpmyadmin")
MAX_SCAN_LINES = 100_000


def recent_lines(path: Path):
    """Bound memory and work for a potentially large shared log."""
    if not path.exists():
        return [], False
    with path.open(encoding="utf-8", errors="replace") as source:
        lines = deque(source, maxlen=MAX_SCAN_LINES)
    return lines, len(lines) == MAX_SCAN_LINES


def summarize_access(lines, *, since: datetime, host: str):
    totals = Counter()
    by_ip = defaultdict(Counter)
    minute_counts = defaultdict(Counter)
    for line in lines:
        match = ACCESS_RE.match(line)
        if not match or match["host"] not in (host, f"www.{host}"):
            continue  # Old-format lines cannot be assigned to a site.
        try:
            at = datetime.strptime(match["time"], "%d/%b/%Y:%H:%M:%S %z")
        except ValueError:
            continue
        if at < since:
            continue
        ip, status = match["ip"], int(match["status"])
        totals["requests"] += 1
        totals[f"{status // 100}xx"] += 1
        by_ip[ip]["requests"] += 1
        minute_counts[ip][at.replace(second=0, microsecond=0)] += 1
        if status >= 400:
            by_ip[ip]["errors"] += 1
        parts = match["request"].split(" ", 2)
        if len(parts) < 2:
            continue
        method, target = parts[:2]
        path = urlsplit(target).path.lower()
        if any(path.startswith(prefix) for prefix in PROBE_PREFIXES):
            by_ip[ip]["probes"] += 1
        if method == "POST" and path == "/participate/consent/":
            by_ip[ip]["consent_posts"] += 1
        if method == "POST" and path.startswith("/recordings/sessions/") and "/attempts/" in path:
            by_ip[ip]["attempt_posts"] += 1

    findings = []
    for ip, counts in by_ip.items():
        burst = max(minute_counts[ip].values(), default=0)
        reasons = []
        if burst >= 60:
            reasons.append(f"{burst} requests in one minute")
        if counts["errors"] >= 20:
            reasons.append(f"{counts['errors']} HTTP errors")
        if counts["probes"] >= 3:
            reasons.append(f"{counts['probes']} probe-path requests")
        if counts["consent_posts"] >= 10:
            reasons.append(f"{counts['consent_posts']} consent POSTs")
        if counts["attempt_posts"] >= 120:
            reasons.append(f"{counts['attempt_posts']} attempt POSTs")
        if reasons:
            findings.append((ip, counts["requests"], ", ".join(reasons)))
    findings.sort(key=lambda item: item[1], reverse=True)
    return totals, findings


def print_report(*, hours: int, max_lines: int, show_ips: bool, access_log: Path, error_log: Path, host: str) -> None:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    access, access_limited = recent_lines(access_log)
    totals, findings = summarize_access(access, since=since, host=host)
    print(f"Nginx traffic for {host}, last {hours}h (current log only):")
    print(f"  Requests: {totals['requests']} (2xx {totals['2xx']}, 3xx {totals['3xx']}, 4xx {totals['4xx']}, 5xx {totals['5xx']})")
    print(f"  Sources worth reviewing: {len(findings)}")
    for index, (ip, requests, reasons) in enumerate(findings[:max_lines], 1):
        label = ip if show_ips else f"source {index}"
        print(f"    {label}: {requests} requests; {reasons}")
    if len(findings) > max_lines:
        print(f"  ... {len(findings) - max_lines} more sources")
    if access_limited:
        print(f"  Note: only the last {MAX_SCAN_LINES} access-log lines were scanned.")

    errors, error_limited = recent_lines(error_log)
    recent_errors = []
    local_since = since.astimezone().replace(tzinfo=None)
    for line in errors:
        match = ERROR_RE.match(line)
        if not match:
            continue
        at = datetime.strptime(match["time"], "%Y/%m/%d %H:%M:%S")
        if at >= local_since:
            message = line.split(", client:", 1)[0].rstrip()
            message = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[address]", message)
            message = re.sub(r"\?[^\s\"']+", "?[redacted]", message)
            recent_errors.append(message)
    print(f"Nginx errors (shared log; last {hours}h): {len(recent_errors)}")
    for line in recent_errors[-max_lines:]:
        print(f"  {line}")
    if error_limited:
        print(f"  Note: only the last {MAX_SCAN_LINES} error-log lines were scanned.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=int, required=True)
    parser.add_argument("--max-lines", type=int, required=True)
    parser.add_argument("--show-ips", action="store_true")
    parser.add_argument("--host", default="mantonesarehard.com")
    parser.add_argument("--access-log", type=Path, default=Path("/var/log/nginx/access.log"))
    parser.add_argument("--error-log", type=Path, default=Path("/var/log/nginx/error.log"))
    args = parser.parse_args()
    print_report(**vars(args))
