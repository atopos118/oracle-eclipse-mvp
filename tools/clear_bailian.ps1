[Environment]::SetEnvironmentVariable("DASHSCOPE_API_KEY", $null, "User")
[Environment]::SetEnvironmentVariable("QWEN_MODEL", $null, "User")
[Environment]::SetEnvironmentVariable("QWEN_OCR_MODEL", $null, "User")
[Environment]::SetEnvironmentVariable("QWEN_TTS_MODEL", $null, "User")
[Environment]::SetEnvironmentVariable("QWEN_TTS_VOICE", $null, "User")
Write-Host "Bailian configuration was cleared. Restart the service."
