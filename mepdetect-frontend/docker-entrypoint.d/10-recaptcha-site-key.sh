#!/bin/sh
# Inject the reCAPTCHA site key into the served pages at container start.
#
# The key is public — it ships to every browser — but it is per-deployment,
# and hardcoding it in login.html is what forced a private copy of this
# source to exist. Substituting it here keeps one set of files that anyone
# can deploy with their own key.
#
# nginx's own entrypoint runs every executable *.sh in this directory before
# starting the server, so this happens once, before the first request.
set -eu

ROOT="${NGINX_HTML_ROOT:-/usr/share/nginx/html}"
TOKEN='__RECAPTCHA_SITE_KEY__'

targets=$(grep -rl "$TOKEN" "$ROOT" 2>/dev/null || true)

if [ -z "$targets" ]; then
    exit 0
fi

if [ -z "${RECAPTCHA_SITE_KEY:-}" ]; then
    echo "$0: RECAPTCHA_SITE_KEY is not set; reCAPTCHA will not work on:" >&2
    echo "$targets" | sed 's#^#    #' >&2
    echo "$0: set it in the environment file the stack is deployed with." >&2
    exit 0
fi

echo "$targets" | while IFS= read -r file; do
    [ -n "$file" ] || continue
    sed -i "s|$TOKEN|$RECAPTCHA_SITE_KEY|g" "$file"
    echo "$0: site key applied to $file"
done
