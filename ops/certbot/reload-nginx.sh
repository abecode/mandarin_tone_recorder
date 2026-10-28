#!/bin/sh
set -eu

/sbin/nginx -t
exec /usr/bin/systemctl reload nginx
