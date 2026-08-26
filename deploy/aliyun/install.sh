#!/usr/bin/env bash
set -euo pipefail

domain="${1:-}"
app_user="oracle-eclipse"
app_root="/opt/oracle-eclipse"
app_dir="${app_root}/app"
env_dir="/etc/oracle-eclipse"
source_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if [[ "${EUID}" -ne 0 ]]; then
    echo "Run this installer as root." >&2
    exit 1
fi
if [[ ! "${domain}" =~ ^([A-Za-z0-9-]+\.)+[A-Za-z]{2,63}$ ]]; then
    echo "Usage: sudo bash deploy/aliyun/install.sh your.domain.example" >&2
    exit 1
fi
if [[ ! -f "${source_dir}/server.py" ]]; then
    echo "Project root was not found next to deploy/aliyun/install.sh." >&2
    exit 1
fi
if [[ -e "${app_dir}/server.py" ]]; then
    echo "${app_dir} already contains an installation. Use the documented upgrade procedure." >&2
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
    ca-certificates curl nginx certbot python3-certbot-nginx \
    python3 python3-pip python3-venv fonts-noto-cjk ffmpeg

if ! id -u "${app_user}" >/dev/null 2>&1; then
    useradd --system --create-home --home-dir "/var/lib/${app_user}" \
        --shell /usr/sbin/nologin "${app_user}"
fi

install -d -m 755 "${app_root}" "${app_dir}" /var/www/oracle-eclipse-acme
cp -a "${source_dir}/." "${app_dir}/"
rm -rf "${app_dir}/.git" "${app_dir}/.pytest_cache" "${app_dir}/tmp"
find "${app_dir}" -type d -name __pycache__ -prune -exec rm -rf {} +
find "${app_dir}" -type f \( -name '*.pyc' -o -name 'server*.log' -o -name 'server*.err' \) -delete

python3 -m venv "${app_dir}/.venv"
"${app_dir}/.venv/bin/python" -m pip install --upgrade pip
"${app_dir}/.venv/bin/python" -m pip install -r "${app_dir}/deploy/ubuntu/requirements-server.txt"

chown -R root:root "${app_dir}"
chown -R "${app_user}:${app_user}" "${app_dir}/source-materials" "${app_dir}/data"
chmod -R u=rwX,go= "${app_dir}/source-materials" "${app_dir}/data"

install -d -m 700 "${env_dir}"
if [[ ! -f "${env_dir}/oracle-eclipse.env" ]]; then
    install -m 600 "${app_dir}/deploy/aliyun/oracle-eclipse.env.example" \
        "${env_dir}/oracle-eclipse.env"
fi
install -m 644 "${app_dir}/deploy/aliyun/oracle-eclipse.service" \
    /etc/systemd/system/oracle-eclipse.service

sed "s/__DOMAIN__/${domain}/g" \
    "${app_dir}/deploy/aliyun/nginx-site.conf.template" \
    > "/etc/nginx/sites-available/${domain}.conf"
ln -sfn "/etc/nginx/sites-available/${domain}.conf" \
    "/etc/nginx/sites-enabled/${domain}.conf"
rm -f /etc/nginx/sites-enabled/default

systemctl daemon-reload
nginx -t
systemctl enable --now nginx
systemctl reload nginx

echo
echo "Application files installed in ${app_dir}."
echo "Next: sudo bash ${app_dir}/deploy/aliyun/configure-secrets.sh ${domain}"
echo "Then point DNS to this ECS and request HTTPS with Certbot."
