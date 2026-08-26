param(
    [string]$Username
)

if ([string]::IsNullOrWhiteSpace($Username)) {
    $existing = [Environment]::GetEnvironmentVariable("ORACLE_RESEARCH_USERNAME", "User")
    $prompt = if ([string]::IsNullOrWhiteSpace($existing)) { "Research username" } else { "Research username [$existing]" }
    $entered = Read-Host $prompt
    $Username = if ([string]::IsNullOrWhiteSpace($entered)) { $existing } else { $entered.Trim() }
}
if ([string]::IsNullOrWhiteSpace($Username)) {
    throw "Research username cannot be empty."
}

$securePassword = Read-Host "Research password (at least 10 characters)" -AsSecureString
$secureConfirmation = Read-Host "Confirm research password" -AsSecureString
$passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
$confirmationPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureConfirmation)
try {
    $password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
    $confirmation = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($confirmationPointer)
    if ($password.Length -lt 10) {
        throw "Research password must contain at least 10 characters."
    }
    if ($password -cne $confirmation) {
        throw "The two passwords do not match."
    }
    [Environment]::SetEnvironmentVariable("ORACLE_RESEARCH_USERNAME", $Username, "User")
    [Environment]::SetEnvironmentVariable("ORACLE_RESEARCH_PASSWORD", $password, "User")
    Write-Host "Research login configured for '$Username'. Restart the service to apply it." -ForegroundColor Green
}
finally {
    if ($passwordPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
    }
    if ($confirmationPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($confirmationPointer)
    }
    $password = $null
    $confirmation = $null
}
