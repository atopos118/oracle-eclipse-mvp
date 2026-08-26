#!/usr/bin/env bash
set -euo pipefail

domain="${1:-sci.ljcode.cn}"
env_dir="/etc/oracle-eclipse"
env_file="${env_dir}/oracle-eclipse.env"

read -r -p "Research username: " research_user
read -r -s -p "Research password (12+ safe characters): " research_password
printf '\n'
read -r -s -p "Repeat research password: " research_password_repeat
printf '\n'
read -r -s -p "DashScope API key: " dashscope_key
printf '\n'

if [[ ! "${research_user}" =~ ^[A-Za-z0-9._-]{3,64}$ ]]; then
    echo "Username must use 3-64 letters, digits, dots, underscores, or hyphens." >&2
    exit 1
fi
if [[ "${research_password}" != "${research_password_repeat}" ]]; then
    echo "Passwords do not match." >&2
    exit 1
fi
if [[ ! "${research_password}" =~ ^[A-Za-z0-9._~!@%+=:-]{12,128}$ ]]; then
    echo "Password contains unsupported characters or is shorter than 12 characters." >&2
    exit 1
fi
if [[ ! "${dashscope_key}" =~ ^[A-Za-z0-9._-]{16,256}$ ]]; then
    echo "DashScope API key format is invalid." >&2
    exit 1
fi

install -d -m 700 "${env_dir}"
umask 077
temporary_file="$(mktemp "${env_dir}/oracle-eclipse.env.XXXXXX")"
trap 'rm -f "${temporary_file}"' EXIT
{
    printf 'DASHSCOPE_API_KEY=%s\n' "${dashscope_key}"
    printf 'ORACLE_RESEARCH_USERNAME=%s\n' "${research_user}"
    printf 'ORACLE_RESEARCH_PASSWORD=%s\n' "${research_password}"
    printf 'ORACLE_PUBLIC_CORS_ORIGIN=https://%s\n' "${domain}"
    printf 'QWEN_MODEL=qwen-plus\n'
    printf 'QWEN_OCR_MODEL=qwen-vl-ocr-latest\n'
    printf 'QWEN_TTS_MODEL=qwen3-tts-flash\n'
    printf 'QWEN_TTS_VOICE=Cherry\n'
    printf 'QWEN_REQUEST_TIMEOUT=180\n'
    printf 'ORACLE_SECURE_COOKIES=1\n'
    printf 'ORACLE_TRUST_PROXY=1\n'
    printf 'ORACLE_RESEARCH_SESSION_HOURS=4\n'
    printf 'ORACLE_LOGIN_RATE_LIMIT=10\n'
    printf 'ORACLE_PUBLIC_CHAT_RATE_LIMIT=30\n'
} > "${temporary_file}"
install -m 600 "${temporary_file}" "${env_file}"
rm -f "${temporary_file}" /root/oracle-eclipse-initial-login.txt
trap - EXIT

systemctl restart oracle-eclipse
systemctl --no-pager --full status oracle-eclipse
echo "Credentials updated."
