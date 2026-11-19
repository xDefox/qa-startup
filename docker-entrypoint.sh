#!/bin/sh
# Fly монтирует volume в /data от root, а приложение работает от webscope.
# Чиним владельца и сбрасываем привилегии — иначе SQLite не сможет создать базу.
set -e

if [ "$(id -u)" = "0" ]; then
  mkdir -p /data
  chown -R webscope:webscope /data
  if command -v setpriv >/dev/null 2>&1; then
    exec setpriv --reuid=webscope --regid=webscope --init-groups "$@"
  fi
  # util-linux без setpriv: su от root пароля не спрашивает.
  exec su -s /bin/sh webscope -c 'exec "$@"' sh "$@"
fi

exec "$@"
