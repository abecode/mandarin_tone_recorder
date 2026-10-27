# Operations

The deployment target is one Linux host with systemd. Fabric runs from the
source checkout over SSH; it does not run on the production server. Production
data is never part of a routine code deployment.

## Server layout

```text
/srv/mandarin-tone-recorder/app/         Git checkout and .venv (deployment user)
/var/lib/mandarin-tone-recorder/         Persistent SQLite database and media
/etc/mandarin-tone-recorder/env          Production environment (root:service)
/etc/systemd/system/mandarin-recorder.service
```

The SSH/deployment user owns the checkout and belongs to the
`mandarin-recorder` group. Gunicorn runs as the non-login
`mandarin-recorder` service user. The service owns the database and media.
The proxy may read `staticfiles/`; do not give it direct access to `media/`.

The server needs Python 3.14, `uv`, `git`, `rsync`, `curl`, `sudo`, and systemd.
The source machine also needs `rsync`. The public repository can be cloned on
the server over HTTPS without a GitHub SSH key. Use SSH config for the
deployment host and key. On the source checkout, install
Fabric with `uv sync --group deploy --locked`, then run `.venv/bin/fab --list`.

`bootstrap` runs `git clone` on the server, using the SSH account that Fabric
logged into. A private repository would require server-side GitHub credentials,
such as a read-only deploy key. Rerunning `bootstrap` after a failed clone is
supported.

## Production environment

Create a private, shell-compatible environment file outside the repository:

```text
DJANGO_SECRET_KEY='replace_this_with_a_long_random_secret'
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=study.example.org
DJANGO_DATA_DIR=/var/lib/mandarin-tone-recorder
```

The bootstrap task installs this file at `/etc/mandarin-tone-recorder/env`.
Keep the source copy private. The data directory must match the path in
`fabfile.py`. Use a long, random production secret. `deploy` refuses `DEBUG=1`,
an unknown domain, or database/media paths outside the persistent directory.
Review the output of `manage.py check --deploy`; it may recommend enabling
HSTS after HTTPS is working reliably. Only trust `X-Forwarded-Proto` when the
proxy overwrites any value supplied by the browser. Gunicorn binds to loopback.

## First deployment with existing data

1. Commit and push the code, including `fabfile.py`, `ops/`, and this document.
   Configure DNS and HTTPS for the chosen domain. Configure Caddy or Nginx to
   proxy to `127.0.0.1:8001` and serve only `/static/` from the checkout's
   `staticfiles/` directory. The proxy must set `X-Forwarded-Proto` from the
   actual connection and must not publish `/media/`.
2. Prepare the server account, directories, checkout, environment file, and
   systemd unit. Run this from the source checkout:

   ```bash
   .venv/bin/fab -H prod-host bootstrap --repo-url https://github.com/abecode/mandarin_tone_recorder.git --env-file /private/path/study.env
   ```

   `bootstrap` does not install Python, uv, rsync, or a web server. Reconnect
   SSH afterward so the deployment user's new group membership applies.
3. Back up the source database and recordings. Stop the development app and
   any other writers to its database and media.
   Production must still be empty and the Gunicorn service stopped. From the
   machine containing `data/django.sqlite3` and `data/media/`, run:

   ```bash
   .venv/bin/fab -H prod-host migrate-data --source-data data --confirm-writes-stopped
   ```

   This creates a consistent SQLite snapshot, transfers media with `rsync`,
   and installs the database last. The task refuses to replace an existing
   production database. It does not delete media already on the server.
4. Deploy the same code version as the source, migrate its schema, collect
   static files, start Gunicorn, and verify the data:

   ```bash
   .venv/bin/fab -H prod-host deploy --ref origin/main --domain study.example.org
   .venv/bin/fab -H prod-host verify-data
   ```

   `verify-data` reports participant and attempt counts and fails if a
   referenced recording file is missing. Compare the counts with the source,
   test the site through HTTPS, and test a staff-authorized audio download
   before opening the site to participants. The copied database already
   contains stimuli and practice decks; do not import those again solely
   because this is a new host.

After cutover, production is the source of truth. Do not rerun `migrate-data`
against a server that has begun accepting users.

For a fresh empty installation, skip `migrate-data`, run `deploy`, then run
`import_stimuli` and `import_practice_decks` on the server as needed.

## Routine deployments

```bash
.venv/bin/fab -H prod-host deploy --ref <commit-or-tag> --domain study.example.org
```

`deploy` fetches Git, refuses a dirty tracked checkout, stops Gunicorn,
creates a server-side SQLite snapshot, checks out the requested commit, runs
`uv sync --locked --no-group deploy`, `manage.py check --deploy`, migrations,
and `collectstatic`, then starts Gunicorn and probes its local HTTP endpoint.
There is a short outage while the service is stopped. The proxy configuration
does not need to reload for a code-only deployment. If a step fails, the
service remains stopped for inspection; a database migration may need a
specific recovery plan before switching back to older code.

## Backups

```bash
.venv/bin/fab -H prod-host backup --destination /private/backups/study-2026-10-27
```

The destination must not exist. `backup` stops Gunicorn, snapshots SQLite,
downloads the snapshot and media tree, then restarts Gunicorn. It also leaves
a timestamped database snapshot in the server's `backups/` directory. Treat
both copies as sensitive; keep an additional off-server backup. A database
without its corresponding media directory is not a complete recording backup.
The resulting folder has the same layout as `migrate-data --source-data` expects,
so it can be restored to an empty server through the same cutover procedure.

## Proxy configuration

Both Caddy and Nginx can use the same Gunicorn service. Configure only one
proxy on ports 80/443. For Nginx, use a separate `server` block for this domain;
an existing unrelated site can keep its own block. Serve `/static/` from
`/srv/mandarin-tone-recorder/app/staticfiles/`, proxy other requests to
`127.0.0.1:8001`, pass the original `Host`, and set `X-Forwarded-Proto` to
the scheme Nginx actually received. Caddy's `reverse_proxy` and `file_server`
can do the equivalent. Never expose the media directory with a public alias.

A Caddy site can route static assets and application requests like this:

```caddyfile
study.example.org {
    handle_path /static/* {
        root * /srv/mandarin-tone-recorder/app/staticfiles
        file_server
    }
    handle {
        reverse_proxy 127.0.0.1:8001
    }
}
```

For Nginx, add the following locations to a TLS-enabled `server` block for the
study domain. Keep the existing site's server block separate:

```nginx
location /static/ {
    alias /srv/mandarin-tone-recorder/app/staticfiles/;
}
location / {
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_pass http://127.0.0.1:8001;
}
```
