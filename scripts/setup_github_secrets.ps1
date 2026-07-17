<#
Securely configure the repository secrets required by the Telegram workflow.

The token is entered as a masked prompt and piped to `gh secret set`; it is
never written to a file, command-line argument, or repository.
#>
[CmdletBinding()]
param(
    [string]$Repo = "maikhanhthieu-droid/laixuat_tienVN"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "GitHub CLI (gh) is required. Install it from https://cli.github.com/"
}

function Set-SecretFromPrompt {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Prompt,
        [switch]$Optional
    )

    $secureValue = Read-Host $Prompt -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureValue)
    try {
        $value = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
        if ([string]::IsNullOrWhiteSpace($value)) {
            if ($Optional) {
                Write-Host "Skipped $Name"
                return
            }
            throw "$Name cannot be empty."
        }
        $value | gh secret set $Name --repo $Repo
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to set $Name."
        }
        Write-Host "Set $Name"
    }
    finally {
        if ($pointer -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
        }
        $value = $null
    }
}

Write-Host "Repository: $Repo"
Write-Host "Do not reuse a bot token that has been posted in chat; revoke it in @BotFather first."

Set-SecretFromPrompt `
    -Name "TELEGRAM_BOT_TOKEN" `
    -Prompt "Telegram bot token (masked)"

Set-SecretFromPrompt `
    -Name "TELEGRAM_CHAT_ID" `
    -Prompt "Telegram chat ID (masked)"

Set-SecretFromPrompt `
    -Name "FRED_API_KEY" `
    -Prompt "FRED API key (optional; press Enter to skip)" `
    -Optional

Set-SecretFromPrompt `
    -Name "REPORT_URL" `
    -Prompt "Public report URL (optional; press Enter to skip)" `
    -Optional

Write-Host ""
Write-Host "Secrets configured. Values are not printed or stored in the repository."
Write-Host "Run: gh workflow run weekly-telegram.yml --repo $Repo"
