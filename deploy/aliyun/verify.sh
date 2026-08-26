#!/usr/bin/env bash
set -euo pipefail

domain="${1:-}"
if [[ ! "${domain}" =~ ^([A-Za-z0-9-]+\.)+[A-Za-z]{2,63}$ ]]; then
    echo "Usage: bash verify.sh your.domain.example" >&2
    exit 1
fi

base_url="https://${domain}"

expect_code() {
    local path="$1"
    local expected="$2"
    local actual
    actual="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' "${base_url}${path}")"
    if [[ "${actual}" != "${expected}" ]]; then
        echo "FAIL ${path}: expected ${expected}, got ${actual}" >&2
        return 1
    fi
    echo "PASS ${path}: ${actual}"
}

systemctl is-active --quiet oracle-eclipse
nginx -t
echo "Local health:"
curl --fail --silent --show-error http://127.0.0.1:8018/api/health
printf '\n'

curl --fail --silent --show-error "${base_url}/" >/dev/null
curl --fail --silent --show-error "${base_url}/showcase/" >/dev/null
curl --fail --silent --show-error "${base_url}/api/health"
printf '\n'

expect_code "/source-materials/research.db" "404"
expect_code "/source-materials/pdfs/test.pdf" "404"
expect_code "/data/release-history/test.json" "404"

echo "Deployment verification passed. Complete the browser workflow checks in the guide."
