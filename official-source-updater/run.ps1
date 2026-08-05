param(
    [ValidateSet("list", "validate", "run")]
    [string]$Command = "validate",
    [string[]]$Source = @(),
    [switch]$PromptCourtToken,
    [int]$CourtMaxPages = 0,
    [int]$FlkMaxPages = 0,
    [int]$MaxPages = 0,
    [string]$ProxyUrl = ""
)

$ErrorActionPreference = "Stop"
$PythonExecutable = (Get-Command python -ErrorAction Stop).Source
if ($ProxyUrl) {
    $ParsedProxy = [Uri]$ProxyUrl
    if (-not $ParsedProxy.IsAbsoluteUri -or $ParsedProxy.Scheme -notin @("http", "https")) {
        throw "ProxyUrl must be an absolute HTTP(S) URL"
    }
    $env:HTTP_PROXY = $ProxyUrl
    $env:HTTPS_PROXY = $ProxyUrl
    $env:ALL_PROXY = $ProxyUrl
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
