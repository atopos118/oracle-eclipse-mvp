param(
    [string]$Model = "qwen-plus",
    [string]$OcrModel = "qwen-vl-ocr-latest",
    [string]$TtsModel = "qwen3-tts-flash",
    [string]$TtsVoice = "Cherry",
    [string]$VideoModel = "happyhorse-1.1-t2v",
    [int]$VideoTimeout = 900
)

$secureKey = Read-Host "Enter DashScope API Key (input is hidden)" -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
try {
    $apiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    if ([string]::IsNullOrWhiteSpace($apiKey)) {
        throw "API Key cannot be empty"
    }
    [Environment]::SetEnvironmentVariable("DASHSCOPE_API_KEY", $apiKey.Trim(), "User")
    [Environment]::SetEnvironmentVariable("QWEN_MODEL", $Model, "User")
    [Environment]::SetEnvironmentVariable("QWEN_OCR_MODEL", $OcrModel, "User")
    [Environment]::SetEnvironmentVariable("QWEN_TTS_MODEL", $TtsModel, "User")
    [Environment]::SetEnvironmentVariable("QWEN_TTS_VOICE", $TtsVoice, "User")
    [Environment]::SetEnvironmentVariable("QWEN_VIDEO_MODEL", $VideoModel, "User")
    [Environment]::SetEnvironmentVariable("QWEN_VIDEO_TIMEOUT", [Math]::Max(60, [Math]::Min($VideoTimeout, 900)), "User")
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
}

Write-Host "Bailian configuration was saved to Windows user environment variables."
Write-Host "Chat model: $Model"
Write-Host "OCR model: $OcrModel"
Write-Host "Speech model: $TtsModel"
Write-Host "Speech voice: $TtsVoice"
Write-Host "Video model: $VideoModel"
Write-Host "Video timeout: $([Math]::Max(60, [Math]::Min($VideoTimeout, 900))) seconds"
Write-Host "Stop the old service and run tools/start_research.ps1."
