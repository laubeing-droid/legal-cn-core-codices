param(
    [ValidateSet("list", "validate", "run")]
    [string]$Command = "validate",
    [string[]]$Source = @(),
    [switch]$PromptCourtToken,
    [int]$CourtMaxPages = 0,
    [int]$FlkMaxPages = 0,
    [int]$MaxPages = 0
)

$ErrorActionPreference = "Stop"
$PythonExecutable = (Get-Command python -ErrorAction Stop).Source
foreach ($ProxyEnvironmentVariable in @(
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "all_proxy"
)) {
    Remove-Item -Path "Env:$ProxyEnvironmentVariable" -ErrorAction SilentlyContinue
}
$UpdaterArguments = @(
    (Join-Path $PSScriptRoot "updater.py"),
    $Command,
    "--database-root",
    (Join-Path (Split-Path $PSScriptRoot -Parent) "corpus")
)

foreach ($SourceId in $Source) {
    $UpdaterArguments += @("--source", $SourceId)
}
if ($PromptCourtToken) {
    $UpdaterArguments += "--prompt-court-token"
}
if ($CourtMaxPages -gt 0) {
    $UpdaterArguments += @("--court-max-pages", $CourtMaxPages)
}
if ($FlkMaxPages -gt 0) {
    $UpdaterArguments += @("--flk-max-pages", $FlkMaxPages)
}
if ($MaxPages -gt 0) {
    $UpdaterArguments += @("--max-pages", $MaxPages)
}

& $PythonExecutable @UpdaterArguments
exit $LASTEXITCODE
