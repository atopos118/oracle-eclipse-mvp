param(
    [int]$Port = 8000,
    [string]$HostAddress = "127.0.0.1"
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($null -ne $pythonCommand) {
    $python = $pythonCommand.Source
}
else {
    $python = "C:\Users\dhtbo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    if (-not (Test-Path -LiteralPath $python)) {
        throw "Python was not found. Install Python or add it to PATH."
    }
}

$apiKey = [Environment]::GetEnvironmentVariable("DASHSCOPE_API_KEY", "Process")
if ([string]::IsNullOrWhiteSpace($apiKey)) {
    $apiKey = [Environment]::GetEnvironmentVariable("DASHSCOPE_API_KEY", "User")
}
if ([string]::IsNullOrWhiteSpace($apiKey)) {
    throw "DASHSCOPE_API_KEY is not configured for the current process or Windows user."
}

$model = [Environment]::GetEnvironmentVariable("QWEN_MODEL", "Process")
if ([string]::IsNullOrWhiteSpace($model)) {
    $model = [Environment]::GetEnvironmentVariable("QWEN_MODEL", "User")
}
if ([string]::IsNullOrWhiteSpace($model)) {
    $model = "qwen-plus"
}

$ocrModel = [Environment]::GetEnvironmentVariable("QWEN_OCR_MODEL", "Process")
if ([string]::IsNullOrWhiteSpace($ocrModel)) {
    $ocrModel = [Environment]::GetEnvironmentVariable("QWEN_OCR_MODEL", "User")
}
if ([string]::IsNullOrWhiteSpace($ocrModel)) {
    $ocrModel = "qwen-vl-ocr-latest"
}

$ttsModel = [Environment]::GetEnvironmentVariable("QWEN_TTS_MODEL", "Process")
if ([string]::IsNullOrWhiteSpace($ttsModel)) {
    $ttsModel = [Environment]::GetEnvironmentVariable("QWEN_TTS_MODEL", "User")
}
if ([string]::IsNullOrWhiteSpace($ttsModel)) {
    $ttsModel = "qwen3-tts-flash"
}

$ttsVoice = [Environment]::GetEnvironmentVariable("QWEN_TTS_VOICE", "Process")
if ([string]::IsNullOrWhiteSpace($ttsVoice)) {
    $ttsVoice = [Environment]::GetEnvironmentVariable("QWEN_TTS_VOICE", "User")
}
if ([string]::IsNullOrWhiteSpace($ttsVoice)) {
    $ttsVoice = "Cherry"
}

$videoModel = [Environment]::GetEnvironmentVariable("QWEN_VIDEO_MODEL", "Process")
if ([string]::IsNullOrWhiteSpace($videoModel)) {
    $videoModel = [Environment]::GetEnvironmentVariable("QWEN_VIDEO_MODEL", "User")
}
if ([string]::IsNullOrWhiteSpace($videoModel)) {
    $videoModel = "happyhorse-1.1-t2v"
}

$videoTimeout = [Environment]::GetEnvironmentVariable("QWEN_VIDEO_TIMEOUT", "Process")
if ([string]::IsNullOrWhiteSpace($videoTimeout)) {
    $videoTimeout = [Environment]::GetEnvironmentVariable("QWEN_VIDEO_TIMEOUT", "User")
}
if ([string]::IsNullOrWhiteSpace($videoTimeout)) {
    $videoTimeout = "900"
}

$env:DASHSCOPE_API_KEY = $apiKey
$env:QWEN_MODEL = $model
$env:QWEN_OCR_MODEL = $ocrModel
$env:QWEN_TTS_MODEL = $ttsModel
$env:QWEN_TTS_VOICE = $ttsVoice
$env:QWEN_VIDEO_MODEL = $videoModel
$env:QWEN_VIDEO_TIMEOUT = $videoTimeout

$researchUsername = [Environment]::GetEnvironmentVariable("ORACLE_RESEARCH_USERNAME", "Process")
if ([string]::IsNullOrWhiteSpace($researchUsername)) {
    $researchUsername = [Environment]::GetEnvironmentVariable("ORACLE_RESEARCH_USERNAME", "User")
}
$researchPassword = [Environment]::GetEnvironmentVariable("ORACLE_RESEARCH_PASSWORD", "Process")
if ([string]::IsNullOrWhiteSpace($researchPassword)) {
    $researchPassword = [Environment]::GetEnvironmentVariable("ORACLE_RESEARCH_PASSWORD", "User")
}
if ([string]::IsNullOrWhiteSpace($researchUsername) -or [string]::IsNullOrWhiteSpace($researchPassword)) {
    throw "Research login is not configured. Run tools/configure_research_login.ps1 first."
}
$env:ORACLE_RESEARCH_USERNAME = $researchUsername
$env:ORACLE_RESEARCH_PASSWORD = $researchPassword

$baseUrl = [Environment]::GetEnvironmentVariable("DASHSCOPE_BASE_URL", "Process")
if ([string]::IsNullOrWhiteSpace($baseUrl)) {
    $baseUrl = [Environment]::GetEnvironmentVariable("DASHSCOPE_BASE_URL", "User")
}
if ([string]::IsNullOrWhiteSpace($baseUrl)) {
    $baseUrl = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
}
$endpoint = ([Uri]$baseUrl).DnsSafeHost
$tcpClient = [Net.Sockets.TcpClient]::new()
try {
    $connectTask = $tcpClient.ConnectAsync($endpoint, 443)
    if (-not $connectTask.Wait(5000)) {
        throw "connection timed out"
    }
    Write-Host "Bailian network: ${endpoint}:443 reachable" -ForegroundColor Green
}
catch {
    Write-Warning "Cannot reach ${endpoint}:443. Bailian chat and cloud OCR will be unavailable until outbound HTTPS is allowed."
    Write-Warning "Run this script in a normal PowerShell window. Allow '$python' outbound TCP 443 in Windows Security or antivirus, and check VPN or organization network policy."
    Write-Warning ("Network detail: " + $_.Exception.GetBaseException().Message)
}
finally {
    $tcpClient.Dispose()
}

Write-Host "Starting research service at http://${HostAddress}:$Port"
Write-Host "Model: $model"
Write-Host "OCR model: $ocrModel"
Write-Host "Speech model: $ttsModel"
Write-Host "Speech voice: $ttsVoice"
Write-Host "Video model: $videoModel"
Write-Host "Video timeout: $videoTimeout seconds"
Write-Host "Research account: $researchUsername"
& $python (Join-Path $projectRoot "server.py") --host $HostAddress --port $Port
