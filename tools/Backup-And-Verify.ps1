param(
    [Parameter(Mandatory = $true)]
    [string]$CandidateRoot,
    [Parameter(Mandatory = $true)]
    [string]$BackupRoot
)

$ErrorActionPreference = "Stop"

function Get-RelativePath([string]$Root, [string]$Child) {
    $rootPrefix = $Root.TrimEnd("\") + "\"
    if (-not $Child.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path is outside root: $Child"
    }
    return $Child.Substring($rootPrefix.Length)
}

$candidate = (Resolve-Path -LiteralPath $CandidateRoot).Path
$allowedRoot = Split-Path -Parent $candidate
$relativeCandidate = Get-RelativePath $allowedRoot $candidate
if ([IO.Path]::IsPathRooted($relativeCandidate)) {
    throw "Candidate is outside the allowed exchange-candidate root: $candidate"
}

$backup = [IO.Path]::GetFullPath($BackupRoot)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
$candidateName = Split-Path -Leaf $candidate
$archive = Join-Path $backup "$candidateName.zip"
$manifest = Join-Path $backup "$candidateName.sha256.csv"
$report = Join-Path $backup "$candidateName.rollback-verification.json"
if (Test-Path -LiteralPath $archive) {
    throw "Backup already exists; refusing overwrite: $archive"
}

$sourceRows = Get-ChildItem -LiteralPath $candidate -File -Recurse |
    Sort-Object FullName |
    ForEach-Object {
        [pscustomobject]@{
            relative_path = (Get-RelativePath $candidate $_.FullName).Replace("\", "/")
            byte_size = $_.Length
            sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
$sourceRows | Export-Csv -LiteralPath $manifest -Encoding utf8 -NoTypeInformation

tar.exe -a -cf $archive -C (Split-Path -Parent $candidate) $candidateName
if ($LASTEXITCODE -ne 0) {
    throw "Archive failed; tar exit code: $LASTEXITCODE"
}

$drillRoot = Join-Path $backup ("rollback-drill-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $drillRoot | Out-Null
try {
    tar.exe -xf $archive -C $drillRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Rollback extraction failed; tar exit code: $LASTEXITCODE"
    }
    $restored = Join-Path $drillRoot $candidateName
    $restoredRows = Get-ChildItem -LiteralPath $restored -File -Recurse |
        Sort-Object FullName |
        ForEach-Object {
            [pscustomobject]@{
                relative_path = (Get-RelativePath $restored $_.FullName).Replace("\", "/")
                byte_size = $_.Length
                sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            }
        }
    $sourceJson = $sourceRows | ConvertTo-Json -Compress
    $restoredJson = $restoredRows | ConvertTo-Json -Compress
    if ($sourceJson -ne $restoredJson) {
        throw "Rollback drill hash manifest mismatch"
    }
    $result = [ordered]@{
        status = "PASS"
        candidate_root = $candidate
        archive = $archive
        archive_sha256 = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
        file_count = $sourceRows.Count
        byte_size = ($sourceRows | Measure-Object -Property byte_size -Sum).Sum
        restored_file_count = $restoredRows.Count
        hash_equivalent = $true
    }
    $result | ConvertTo-Json | Set-Content -LiteralPath $report -Encoding utf8
    $result | ConvertTo-Json
}
finally {
    $resolvedDrillRoot = [IO.Path]::GetFullPath($drillRoot)
    $relativeDrill = Get-RelativePath $backup $resolvedDrillRoot
    if (
        (Test-Path -LiteralPath $resolvedDrillRoot) -and
        -not [IO.Path]::IsPathRooted($relativeDrill) -and
        (Split-Path -Leaf $resolvedDrillRoot).StartsWith("rollback-drill-")
    ) {
        Remove-Item -LiteralPath $resolvedDrillRoot -Recurse -Force
    }
}
