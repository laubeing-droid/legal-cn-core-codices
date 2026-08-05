[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('Details', 'Docx')]
    [string]$Mode,

    [Parameter(Mandatory)]
    [string]$OutputRoot,

    [string]$CandidateCsv,
    [string]$FetchResultsCsv,
    [string]$Proxy = '',
    [int]$DelayMilliseconds = 100
)

$ErrorActionPreference = 'Stop'
$rawDirectory = Join-Path $OutputRoot 'raw'
$failedResponseDirectory = Join-Path $OutputRoot 'failed_responses'
New-Item -ItemType Directory -Force -Path $rawDirectory | Out-Null
New-Item -ItemType Directory -Force -Path $failedResponseDirectory | Out-Null

function Invoke-VerifiedCurlDownload {
    param(
        [Parameter(Mandatory)][string]$Url,
        [Parameter(Mandatory)][string]$Destination
    )

    $partial = "$Destination.part"
    Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue
    $arguments = @(
        '--fail-with-body',
        '--location',
        '--silent',
        '--show-error',
        '--max-time', '12',
        '--user-agent', 'legal-cn-core-codices-targeted-evidence/1.0',
        '--referer', 'https://flk.npc.gov.cn/'
    )
    if ($Proxy) {
        $arguments += @('--proxy', $Proxy)
    }
    $arguments += @('--output', $partial, $Url)
    & curl.exe @arguments
    if ($LASTEXITCODE -ne 0) {
        Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue
        throw "curl exit=$LASTEXITCODE"
    }
    Move-Item -LiteralPath $partial -Destination $Destination -Force
}

function Test-SuccessJson {
    param([Parameter(Mandatory)][string]$Path)
    try {
        $value = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
        return $value.code -eq 200 -and $null -ne $value.data
    }
    catch {
        return $false
    }
}

function Test-DocxMagic {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return $false
    }
    $stream = [System.IO.File]::OpenRead($Path)
    try {
        if ($stream.Length -lt 4) {
            return $false
        }
        $bytes = New-Object byte[] 4
        [void]$stream.Read($bytes, 0, 4)
        return $bytes[0] -eq 0x50 -and $bytes[1] -eq 0x4B -and $bytes[2] -eq 0x03 -and $bytes[3] -eq 0x04
    }
    finally {
        $stream.Dispose()
    }
}

$records = [System.Collections.Generic.List[object]]::new()
$succeeded = 0
$reused = 0
$failed = 0
$circuitOpenCount = 0
$consecutiveChallenges = 0
$circuitOpen = $false

if ($Mode -eq 'Details') {
    if (-not $CandidateCsv) {
        throw 'Details mode requires -CandidateCsv.'
    }
    $items = @(Import-Csv -LiteralPath $CandidateCsv -Encoding UTF8)
    for ($index = 0; $index -lt $items.Count; $index++) {
        $item = $items[$index]
        $destination = Join-Path $rawDirectory "$($item.bbbs).detail.json"
        $status = ''
        $errorMessage = ''
        try {
            if ($circuitOpen) {
                $status = 'CIRCUIT_OPEN'
                $circuitOpenCount++
            }
            elseif (Test-SuccessJson -Path $destination) {
                $status = 'REUSED'
                $reused++
            }
            else {
                $url = 'https://flk.npc.gov.cn/law-search/search/flfgDetails?bbbs=' + [uri]::EscapeDataString($item.bbbs)
                Invoke-VerifiedCurlDownload -Url $url -Destination $destination
                if (-not (Test-SuccessJson -Path $destination)) {
                    $challenge = Select-String -LiteralPath $destination -Pattern 'WZWS|Please enable JavaScript' -Quiet -Encoding UTF8
                    $failedDestination = Join-Path $failedResponseDirectory "$($item.bbbs).detail.response"
                    Move-Item -LiteralPath $destination -Destination $failedDestination -Force
                    if ($challenge) {
                        $consecutiveChallenges++
                        throw "WZWS challenge page; consecutive=$consecutiveChallenges"
                    }
                    $consecutiveChallenges = 0
                    throw 'response is not code=200 JSON data'
                }
                $status = 'SUCCEEDED'
                $succeeded++
                $consecutiveChallenges = 0
            }
        }
        catch {
            $status = 'FAILED'
            $errorMessage = $_.Exception.Message
            $failed++
            if ($consecutiveChallenges -ge 10) {
                $circuitOpen = $true
            }
        }
        $records.Add([pscustomobject]@{
            bbbs = $item.bbbs
            mode = $Mode
            status = $status
            output_path = "raw/$([System.IO.Path]::GetFileName($destination))"
            sha256 = if (Test-Path -LiteralPath $destination) { (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant() } else { '' }
            error = $errorMessage
        })
        if ($DelayMilliseconds -gt 0 -and $status -eq 'SUCCEEDED') {
            Start-Sleep -Milliseconds $DelayMilliseconds
        }
        if (($index + 1) % 50 -eq 0) {
            Write-Output "processed=$($index + 1)/$($items.Count) succeeded=$succeeded reused=$reused failed=$failed"
        }
    }
}
else {
    if (-not $FetchResultsCsv) {
        throw 'Docx mode requires -FetchResultsCsv.'
    }
    $items = @(Import-Csv -LiteralPath $FetchResultsCsv -Encoding UTF8 | Where-Object status -eq 'DOCX_REQUIRED')
    for ($index = 0; $index -lt $items.Count; $index++) {
        $item = $items[$index]
        $docxDestination = Join-Path $rawDirectory "$($item.bbbs).docx"
        $downloadJsonDestination = Join-Path $rawDirectory "$($item.bbbs).download.json"
        $status = ''
        $errorMessage = ''
        try {
            if (Test-DocxMagic -Path $docxDestination) {
                $status = 'REUSED'
                $reused++
            }
            else {
                $query = 'format=docx&bbbs=' + [uri]::EscapeDataString($item.bbbs) + '&fileId='
                Invoke-VerifiedCurlDownload -Url "https://flk.npc.gov.cn/law-search/download/pc?$query" -Destination $downloadJsonDestination
                $download = Get-Content -LiteralPath $downloadJsonDestination -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($download.code -ne 200 -or -not $download.data.url -or -not $download.data.url.StartsWith('https://')) {
                    throw 'download endpoint did not return an HTTPS signed URL'
                }
                Invoke-VerifiedCurlDownload -Url $download.data.url -Destination $docxDestination
                if (-not (Test-DocxMagic -Path $docxDestination)) {
                    throw 'downloaded bytes are not DOCX/ZIP'
                }
                $status = 'SUCCEEDED'
                $succeeded++
            }
        }
        catch {
            $status = 'FAILED'
            $errorMessage = $_.Exception.Message
            $failed++
        }
        $records.Add([pscustomobject]@{
            bbbs = $item.bbbs
            mode = $Mode
            status = $status
            output_path = "raw/$([System.IO.Path]::GetFileName($docxDestination))"
            sha256 = if (Test-Path -LiteralPath $docxDestination) { (Get-FileHash -LiteralPath $docxDestination -Algorithm SHA256).Hash.ToLowerInvariant() } else { '' }
            error = $errorMessage
        })
        if ($DelayMilliseconds -gt 0 -and $status -eq 'SUCCEEDED') {
            Start-Sleep -Milliseconds $DelayMilliseconds
        }
        Write-Output "processed=$($index + 1)/$($items.Count) succeeded=$succeeded reused=$reused failed=$failed"
    }
}

$logPath = Join-Path $OutputRoot "network_fetch_log_$($Mode.ToLowerInvariant()).csv"
$records | Export-Csv -LiteralPath $logPath -NoTypeInformation -Encoding UTF8
Write-Output "mode=$Mode total=$($records.Count) succeeded=$succeeded reused=$reused failed=$failed circuit_open=$circuitOpenCount log=$logPath"
if ($failed -gt 0) {
    exit 2
}
