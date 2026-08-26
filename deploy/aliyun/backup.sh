#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    echo "Run this script as root." >&2
    exit 1
fi

app_dir="/opt/oracle-eclipse/app"
backup_dir="/var/backups/oracle-eclipse"
stamp="$(date +%Y%m%d-%H%M%S)"
archive="${backup_dir}/oracle-eclipse-data-${stamp}.tar.gz"
was_active=0

install -d -m 700 "${backup_dir}"
if systemctl is-active --quiet oracle-eclipse; then
    was_active=1
    systemctl stop oracle-eclipse
fi
restore_service() {
    if [[ "${was_active}" -eq 1 ]]; then
        systemctl start oracle-eclipse
    fi
}
trap restore_service EXIT

tar -czf "${archive}" \
    -C "${app_dir}" source-materials data \
    -C /etc oracle-eclipse/oracle-eclipse.env
chmod 600 "${archive}"
sha256sum "${archive}" > "${archive}.sha256"
chmod 600 "${archive}.sha256"

restore_service
trap - EXIT
echo "Backup created: ${archive}"
