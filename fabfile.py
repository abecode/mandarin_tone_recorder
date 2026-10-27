"""SSH operations for one Linux host running the Django application."""

import shlex
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fabric import task

from ops.sqlite_backup import snapshot


APP_ROOT = "/srv/mandarin-tone-recorder"
APP_DIR = f"{APP_ROOT}/app"
DATA_DIR = "/var/lib/mandarin-tone-recorder"
DATABASE = f"{DATA_DIR}/django.sqlite3"
MEDIA_DIR = f"{DATA_DIR}/media"
BACKUP_DIR = f"{DATA_DIR}/backups"
ENV_FILE = "/etc/mandarin-tone-recorder/env"
SERVICE = "mandarin-recorder"
UNIT_FILE = f"/etc/systemd/system/{SERVICE}.service"


def q(value: object) -> str:
    return shlex.quote(str(value))


def active(c) -> bool:
    return c.run(f"systemctl is-active --quiet {SERVICE}", warn=True, hide=True).ok


def run_manage(c, arguments: str, *, service_user: bool) -> None:
    script = (
        f"set -a; . {q(ENV_FILE)}; set +a; "
        f"cd {q(APP_DIR)}; exec .venv/bin/python manage.py {arguments}"
    )
    command = f"sh -c {q(script)}"
    if service_user:
        c.sudo(command, user=SERVICE)
    else:
        c.run(command)


def check_deploy_settings(c, domain: str) -> None:
    script = (
        f"set -a; . {q(ENV_FILE)}; set +a; cd {q(APP_DIR)}; "
        f"exec .venv/bin/python -m ops.check_deploy {q(domain)} {q(DATA_DIR)}"
    )
    c.sudo(f"sh -c {q(script)}", user=SERVICE)


def remote_snapshot(c) -> str:
    """Save a database snapshot on the server before changing or copying data."""
    name = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}_{uuid4().hex}.sqlite3"
    path = f"{BACKUP_DIR}/{name}"
    c.sudo(
        f"sh -c {q(f'cd {q(APP_DIR)}; exec python3 -m ops.sqlite_backup {q(DATABASE)} {q(path)}')}",
        user=SERVICE,
    )
    return path


def rsync_media(c, source: str, destination: str, *, to_server: bool) -> None:
    ssh = f"ssh -p {c.port or 22}"
    deploy_user = c.run("id -un", hide=True).stdout.strip()
    remote = f"{deploy_user}@{c.host}"
    if to_server:
        command = [
            "rsync", "-a", "--no-owner", "--no-group",
            "--chmod=Dg+rwx,Do=,Dg+s,Fg+rw,Fo=",
            "-e", ssh, f"{source}/", f"{remote}:{destination}/",
        ]
    else:
        command = [
            "rsync", "-a", "--no-owner", "--no-group",
            "--chmod=Du+rwx,Dgo=,Fu+rw,Fgo=", "-e", ssh,
            f"{remote}:{source}/", f"{destination}/",
        ]
    subprocess.run(command, check=True)


@task
def bootstrap(c, repo_url, env_file):
    """Create the service account, persistent directories, checkout and unit."""
    local_env = Path(env_file).expanduser().resolve()
    if not local_env.is_file():
        raise FileNotFoundError(local_env)
    deploy_user = c.run("id -un", hide=True).stdout.strip()
    deploy_group = c.run("id -gn", hide=True).stdout.strip()

    if not c.run(f"id -u {q(SERVICE)}", warn=True, hide=True).ok:
        c.sudo(
            f"useradd --system --user-group --no-create-home "
            f"--home-dir {q(DATA_DIR)} --shell /usr/sbin/nologin {q(SERVICE)}"
        )
    c.sudo(f"install -d -o {q(deploy_user)} -g {q(deploy_group)} -m 0755 {q(APP_ROOT)}")
    c.sudo(f"install -d -o {SERVICE} -g {SERVICE} -m 2770 {q(DATA_DIR)} {q(MEDIA_DIR)} {q(BACKUP_DIR)}")
    c.sudo(f"install -d -o root -g {SERVICE} -m 0750 {q('/etc/mandarin-tone-recorder')}")
    c.sudo(f"usermod -aG {SERVICE} {q(deploy_user)}")

    temporary = c.run("mktemp", hide=True).stdout.strip()
    try:
        c.put(str(local_env), temporary)
        c.sudo(f"install -o root -g {SERVICE} -m 0640 {q(temporary)} {q(ENV_FILE)}")
        unit = Path(__file__).resolve().parent / "ops/mandarin-recorder.service"
        c.put(str(unit), temporary)
        c.sudo(f"install -o root -g root -m 0644 {q(temporary)} {q(UNIT_FILE)}")
    finally:
        c.run(f"rm -f -- {q(temporary)}")

    if not c.run(f"test -d {q(APP_DIR + '/.git')}", warn=True, hide=True).ok:
        c.run(f"git clone -- {q(repo_url)} {q(APP_DIR)}")
    c.sudo("systemctl daemon-reload")
    print("Bootstrap complete. Reconnect SSH so the new service-group membership applies.")


@task
def deploy(c, ref="origin/main", domain=""):
    """Deploy one Git commit without copying development data."""
    if not domain:
        raise ValueError("Pass --domain with the hostname in DJANGO_ALLOWED_HOSTS.")
    if not c.run(f"test -r {q(ENV_FILE)}", warn=True, hide=True).ok:
        raise RuntimeError("Production environment file is not readable; run bootstrap and reconnect SSH.")
    if c.run(f"git -C {q(APP_DIR)} status --porcelain --untracked-files=no", hide=True).stdout.strip():
        raise RuntimeError("The server checkout has tracked changes; resolve them before deploying.")

    c.run(f"git -C {q(APP_DIR)} fetch --tags origin")
    commit = c.run(
        f"git -C {q(APP_DIR)} rev-parse --verify {q(ref + '^{commit}')}", hide=True
    ).stdout.strip()
    was_active = active(c)
    if was_active:
        c.sudo(f"systemctl stop {SERVICE}")
    try:
        if c.run(f"test -f {q(DATABASE)}", warn=True, hide=True).ok:
            print(f"Database snapshot: {remote_snapshot(c)}")
        c.run(f"git -C {q(APP_DIR)} switch --detach {q(commit)}")
        c.run(f"cd {q(APP_DIR)} && uv sync --locked --no-group deploy")
        check_deploy_settings(c, domain)
        run_manage(c, "check --deploy", service_user=True)
        run_manage(c, "migrate --noinput", service_user=True)
        run_manage(c, "collectstatic --noinput", service_user=False)
        c.sudo(f"systemctl enable --now {SERVICE}")
        c.run(
            f"curl --fail --silent --show-error --max-time 10 "
            f"-H {q('Host: ' + domain)} -H {q('X-Forwarded-Proto: https')} "
            f"http://127.0.0.1:8001/ -o /dev/null"
        )
    except Exception:
        print("Deployment failed. The application service remains stopped; inspect the error before restarting it.")
        c.sudo(f"systemctl stop {SERVICE}")
        raise
    print(f"Deployed {commit}")


@task
def migrate_data(c, source_data="data", confirm_writes_stopped=False):
    """Copy one local development database and media tree to an empty server."""
    if not confirm_writes_stopped:
        raise ValueError("Stop writes on the source, then pass --confirm-writes-stopped.")
    source = Path(source_data).expanduser().resolve()
    if not (source / "django.sqlite3").is_file():
        raise FileNotFoundError(source / "django.sqlite3")
    if not (source / "media").is_dir():
        raise FileNotFoundError(source / "media")
    if active(c):
        raise RuntimeError("Stop the production service before transferring data.")
    if c.run(f"test -e {q(DATABASE)}", warn=True, hide=True).ok:
        raise RuntimeError("Production database already exists; refusing to overwrite it.")

    with tempfile.TemporaryDirectory() as temporary:
        snapshot(source / "django.sqlite3", Path(temporary) / "django.sqlite3")
        rsync_media(c, str(source / "media"), MEDIA_DIR, to_server=True)
        incoming = f"{DATA_DIR}/.django.sqlite3.incoming-{uuid4().hex}"
        try:
            c.put(str(Path(temporary) / "django.sqlite3"), incoming)
            c.sudo(f"install -o {SERVICE} -g {SERVICE} -m 0660 {q(incoming)} {q(DATABASE)}")
        finally:
            c.run(f"rm -f -- {q(incoming)}")
    print("Data copied. Run deploy, then verify-data, before opening the site.")


@task
def backup(c, destination):
    """Download a matching SQLite snapshot and recordings to a new local folder."""
    local = Path(destination).expanduser().resolve()
    if local.exists():
        raise FileExistsError(local)
    if not c.run(f"test -f {q(DATABASE)}", warn=True, hide=True).ok:
        raise FileNotFoundError(DATABASE)
    local.mkdir(parents=True, mode=0o700)
    (local / "media").mkdir(mode=0o700)
    was_active = active(c)
    if was_active:
        c.sudo(f"systemctl stop {SERVICE}")
    try:
        remote_file = remote_snapshot(c)
        c.get(remote_file, str(local / "django.sqlite3"))
        rsync_media(c, MEDIA_DIR, str(local / "media"), to_server=False)
    finally:
        if was_active:
            c.sudo(f"systemctl start {SERVICE}")
    print(f"Backup saved in {local}")


@task
def verify_data(c):
    """Count imported records and report missing recording files."""
    script = (
        f"set -a; . {q(ENV_FILE)}; set +a; "
        f"cd {q(APP_DIR)}; exec .venv/bin/python -m ops.verify_data"
    )
    c.sudo(f"sh -c {q(script)}", user=SERVICE)
