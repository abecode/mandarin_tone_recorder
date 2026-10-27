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
PYTHON_DIR = f"{APP_ROOT}/python"
DATA_DIR = "/var/lib/mandarin-tone-recorder"
DATABASE = f"{DATA_DIR}/django.sqlite3"
MEDIA_DIR = f"{DATA_DIR}/media"
BACKUP_DIR = f"{DATA_DIR}/backups"
ENV_FILE = "/etc/mandarin-tone-recorder/env"
SERVICE = "mandarin-recorder"
UNIT_FILE = f"/etc/systemd/system/{SERVICE}.service"


def status(task_name: str, message: str) -> None:
    print(f"[{task_name}] {message}", flush=True)


def q(value: object) -> str:
    return shlex.quote(str(value))


def active(c) -> bool:
    return c.run(f"systemctl is-active --quiet {SERVICE}", warn=True, hide=True).ok


def uv_executable(c) -> str:
    result = c.run("command -v uv", warn=True, hide=True)
    if result.ok:
        return result.stdout.strip()
    result = c.run('test -x "$HOME/.local/bin/uv"', warn=True, hide=True)
    if result.ok:
        return c.run('printf "%s" "$HOME/.local/bin/uv"', hide=True).stdout.strip()
    raise RuntimeError(
        "uv is not installed for the deployment user. Install it on the server "
        "before running deploy (see ops.md)."
    )


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
            "rsync", "-a", "--omit-dir-times", "--no-perms", "--stats",
            "--no-owner", "--no-group",
            "-e", ssh, f"{source}/", f"{remote}:{destination}/",
        ]
    else:
        command = [
            "rsync", "-a", "--stats", "--no-owner", "--no-group",
            "--chmod=Du+rwx,Dgo=,Fu+rw,Fgo=", "-e", ssh,
            f"{remote}:{source}/", f"{destination}/",
        ]
    subprocess.run(command, check=True)


@task
def bootstrap(c, repo_url, env_file):
    """Create the service account, persistent directories, checkout and unit."""
    status("bootstrap", "Checking the local environment file and remote account")
    local_env = Path(env_file).expanduser().resolve()
    if not local_env.is_file():
        raise FileNotFoundError(local_env)
    deploy_user = c.run("id -un", hide=True).stdout.strip()
    deploy_group = c.run("id -gn", hide=True).stdout.strip()

    status("bootstrap", "Preparing the service account and persistent directories")
    if not c.run(f"id -u {q(SERVICE)}", warn=True, hide=True).ok:
        c.sudo(
            f"useradd --system --user-group --no-create-home "
            f"--home-dir {q(DATA_DIR)} --shell /usr/sbin/nologin {q(SERVICE)}"
        )
    c.sudo(f"install -d -o {q(deploy_user)} -g {q(deploy_group)} -m 0755 {q(APP_ROOT)}")
    c.sudo(f"install -d -o {SERVICE} -g {SERVICE} -m 2770 {q(DATA_DIR)} {q(MEDIA_DIR)} {q(BACKUP_DIR)}")
    c.sudo(f"install -d -o root -g {SERVICE} -m 0750 {q('/etc/mandarin-tone-recorder')}")
    c.sudo(f"usermod -aG {SERVICE} {q(deploy_user)}")

    status("bootstrap", "Installing the production environment and systemd unit")
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
        status("bootstrap", "Cloning the repository on the server")
        c.run(f"git clone -- {q(repo_url)} {q(APP_DIR)}")
    else:
        status("bootstrap", "Repository checkout already exists")
    status("bootstrap", "Reloading systemd")
    c.sudo("systemctl daemon-reload")
    status("bootstrap", "Complete. Reconnect SSH so the new service-group membership applies")


@task
def deploy(c, ref="origin/main", domain=""):
    """Deploy one Git commit without copying development data."""
    if not domain:
        raise ValueError("Pass --domain with the hostname in DJANGO_ALLOWED_HOSTS.")
    status("deploy", "Checking the server environment and checkout")
    if not c.run(f"test -r {q(ENV_FILE)}", warn=True, hide=True).ok:
        raise RuntimeError("Production environment file is not readable; run bootstrap and reconnect SSH.")
    if c.run(f"git -C {q(APP_DIR)} status --porcelain --untracked-files=no", hide=True).stdout.strip():
        raise RuntimeError("The server checkout has tracked changes; resolve them before deploying.")

    status("deploy", "Checking uv and preparing Python 3.14")
    uv = uv_executable(c)
    c.run(f"{q(uv)} --version")
    c.run(f"install -d -m 0755 {q(PYTHON_DIR)}")
    c.run(f"UV_PYTHON_INSTALL_DIR={q(PYTHON_DIR)} {q(uv)} python install 3.14")

    status("deploy", f"Fetching Git ref {ref}")
    c.run(f"git -C {q(APP_DIR)} fetch --tags origin")
    commit = c.run(
        f"git -C {q(APP_DIR)} rev-parse --verify {q(ref + '^{commit}')}", hide=True
    ).stdout.strip()
    was_active = active(c)
    if was_active:
        status("deploy", "Stopping Gunicorn")
        c.sudo(f"systemctl stop {SERVICE}")
    try:
        if c.run(f"test -f {q(DATABASE)}", warn=True, hide=True).ok:
            status("deploy", "Taking a SQLite snapshot before migrations")
            status("deploy", f"Database snapshot saved at {remote_snapshot(c)}")
        status("deploy", f"Checking out {commit}")
        c.run(f"git -C {q(APP_DIR)} switch --detach {q(commit)}")
        status("deploy", "Installing locked production dependencies")
        c.run(
            f"cd {q(APP_DIR)} && UV_PYTHON_INSTALL_DIR={q(PYTHON_DIR)} "
            f"{q(uv)} sync --locked --no-group deploy"
        )
        status("deploy", "Checking production settings and Django configuration")
        check_deploy_settings(c, domain)
        run_manage(c, "check --deploy", service_user=True)
        status("deploy", "Applying database migrations")
        run_manage(c, "migrate --noinput", service_user=True)
        status("deploy", "Collecting static files")
        run_manage(c, "collectstatic --noinput", service_user=False)
        status("deploy", "Starting Gunicorn")
        c.sudo(f"systemctl enable --now {SERVICE}")
        status("deploy", "Probing the local HTTP endpoint")
        c.run(
            f"curl --fail --silent --show-error --max-time 10 "
            f"-H {q('Host: ' + domain)} -H {q('X-Forwarded-Proto: https')} "
            f"http://127.0.0.1:8001/ -o /dev/null"
        )
    except Exception:
        status("deploy", "Failed. The service remains stopped; inspect the error before restarting it")
        c.sudo(f"systemctl stop {SERVICE}")
        raise
    status("deploy", f"Complete at {commit}")


@task
def migrate_data(c, source_data="data", confirm_writes_stopped=False):
    """Copy one local development database and media tree to an empty server."""
    status("migrate-data", "Checking source files and production state")
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
        status("migrate-data", "Creating a consistent local SQLite snapshot")
        snapshot(source / "django.sqlite3", Path(temporary) / "django.sqlite3")
        status("migrate-data", "Copying recordings to the server with rsync")
        rsync_media(c, str(source / "media"), MEDIA_DIR, to_server=True)
        status("migrate-data", "Setting private media permissions on the server")
        c.sudo(f"chgrp -R {SERVICE} {q(MEDIA_DIR)}")
        c.sudo(f"find {q(MEDIA_DIR)} -type d -exec chmod 2770 {{}} +")
        c.sudo(f"find {q(MEDIA_DIR)} -type f -exec chmod 0660 {{}} +")
        incoming = f"{DATA_DIR}/.django.sqlite3.incoming-{uuid4().hex}"
        try:
            status("migrate-data", "Installing the database snapshot on the server")
            c.put(str(Path(temporary) / "django.sqlite3"), incoming)
            c.sudo(f"install -o {SERVICE} -g {SERVICE} -m 0660 {q(incoming)} {q(DATABASE)}")
        finally:
            c.run(f"rm -f -- {q(incoming)}")
    status("migrate-data", "Complete. Run deploy and verify-data before opening the site")


@task
def backup(c, destination):
    """Download a matching SQLite snapshot and recordings to a new local folder."""
    status("backup", "Checking the destination and production database")
    local = Path(destination).expanduser().resolve()
    if local.exists():
        raise FileExistsError(local)
    if not c.run(f"test -f {q(DATABASE)}", warn=True, hide=True).ok:
        raise FileNotFoundError(DATABASE)
    local.mkdir(parents=True, mode=0o700)
    (local / "media").mkdir(mode=0o700)
    was_active = active(c)
    if was_active:
        status("backup", "Stopping Gunicorn for a consistent backup")
        c.sudo(f"systemctl stop {SERVICE}")
    try:
        status("backup", "Creating a server-side SQLite snapshot")
        remote_file = remote_snapshot(c)
        status("backup", "Downloading the SQLite snapshot")
        c.get(remote_file, str(local / "django.sqlite3"))
        status("backup", "Downloading recordings with rsync")
        rsync_media(c, MEDIA_DIR, str(local / "media"), to_server=False)
    finally:
        if was_active:
            status("backup", "Restarting Gunicorn")
            c.sudo(f"systemctl start {SERVICE}")
    status("backup", f"Complete at {local}")


@task
def verify_data(c):
    """Count imported records and report missing recording files."""
    status("verify-data", "Counting records and checking referenced audio files")
    script = (
        f"set -a; . {q(ENV_FILE)}; set +a; "
        f"cd {q(APP_DIR)}; exec .venv/bin/python -m ops.verify_data"
    )
    c.sudo(f"sh -c {q(script)}", user=SERVICE)
    status("verify-data", "Complete")
