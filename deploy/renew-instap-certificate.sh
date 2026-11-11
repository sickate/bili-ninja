#!/bin/sh
# Certbot deploy-directory hook: install root-owned, mode 0755 at
# /etc/letsencrypt/renewal-hooks/deploy/50-instap-nginx-reload
# Certbot 1.21 invokes directory hooks for renew and skips them during dry-run.
# See v1.21.0 certbot/docs/using.rst and certbot/docs/cli-help.txt:
# https://github.com/certbot/certbot/tree/v1.21.0/certbot/docs
set -eu

# Other certificates share this Certbot installation. Only www triggers reload.
case "${RENEWED_LINEAGE:-}" in
    /etc/letsencrypt/live/www.instap.net|/etc/letsencrypt/live/www.instap.net/) ;;
    *) exit 0 ;;
esac

# A failed configuration check exits before reload; errors reach Certbot's log.
/usr/sbin/nginx -t
/usr/bin/systemctl reload nginx
printf '%s\n' 'Instap: Nginx reloaded after www.instap.net certificate renewal.'
