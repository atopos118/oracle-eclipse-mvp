param(
    [int]$Port = 8000,
    [string]$PublicOrigin = ""
)

$projectRoot = Split-Path -Parent $PSScriptRoot

function Read-Setting([string]$Name, [string]$Default = "") {
    $value = [Environment]::GetEnvironmentVariable($Name, "Process")
    if ([string]::IsNullOrWhiteSpace($value)) {
        $value = [Environment]::GetEnvironmentVariable($Name, "User")
    }
    if ([string]::IsNullOrWhiteSpace($value)) { return $Default }
    return $value
}

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
$python = if ($null -ne $pythonCommand) {
    $pythonCommand.Source
}
else {
    "C:\Users\dhtbo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
}
if (-not (Test-Path -LiteralPath $python)) {
    throw "Python was not found. Install Python or add it to PATH."
}

$apiKey = Read-Setting "DASHSCOPE_API_KEY"
$username = Read-Setting "ORACLE_RESEARCH_USERNAME"
$password = Read-Setting "ORACLE_RESEARCH_PASSWORD"
if ([string]::IsNullOrWhiteSpace($apiKey)) {
    throw "DASHSCOPE_API_KEY is required for the competition demo."
}
if ([string]::IsNullOrWhiteSpace($username) -or [string]::IsNullOrWhiteSpace($password)) {
    throw "Research login is not configured. Run tools/configure_research_login.ps1 first."
}

$env:DASHSCOPE_API_KEY = $apiKey
$env:ORACLE_RESEARCH_USERNAME = $username
$env:ORACLE_RESEARCH_PASSWORD = $password
$env:QWEN_MODEL = Read-Setting "QWEN_MODEL" "qwen-plus"
$env:QWEN_OCR_MODEL = Read-Setting "QWEN_OCR_MODEL" "qwen-vl-ocr-latest"
$env:QWEN_TTS_MODEL = Read-Setting "QWEN_TTS_MODEL" "qwen3-tts-flash"
$env:QWEN_TTS_VOICE = Read-Setting "QWEN_TTS_VOICE" "Cherry"
$env:ORACLE_SECURE_COOKIES = "1"
$env:ORACLE_TRUST_PROXY = "1"
$env:ORACLE_RESEARCH_SESSION_HOURS = Read-Setting "ORACLE_RESEARCH_SESSION_HOURS" "4"
$env:ORACLE_LOGIN_RATE_LIMIT = Read-Setting "ORACLE_LOGIN_RATE_LIMIT" "10"
$env:ORACLE_PUBLIC_CHAT_RATE_LIMIT = Read-Setting "ORACLE_PUBLIC_CHAT_RATE_LIMIT" "30"
$env:ORACLE_QUICK_LOGIN_ENABLED = Read-Setting "ORACLE_QUICK_LOGIN_ENABLED" "0"
if (-not [string]::IsNullOrWhiteSpace($PublicOrigin)) {
    $env:ORACLE_PUBLIC_CORS_ORIGIN = $PublicOrigin.TrimEnd("/")
}

Write-Host "Starting competition demo backend at http://127.0.0.1:$Port" -ForegroundColor Green
Write-Host "Expose it only through an HTTPS reverse proxy or secure tunnel." -ForegroundColor Yellow
Write-Host "Public site: / | Competition entry: /showcase/ | Research workbench: /research/"
& $python (Join-Path $projectRoot "server.py") --host 127.0.0.1 --port $Port --public-demo
