# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 100000)]
    [int]$Serial,

    [string]$Shim,

    [string]$ShimVersion,

    [string]$ServerVersion = 'project-revival-17/0.1.0',

    [string]$ProtocolVersion = '1',

    [string]$ContentVersion = '1',

    [string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$launcherRoot = $PSScriptRoot
$repoRoot = Split-Path -Parent $launcherRoot
$appProject = Join-Path $launcherRoot 'src\Revival.Launcher.App\Revival.Launcher.App.csproj'

if (-not $Shim) { $Shim = Join-Path $repoRoot 'client\build\version.dll' }
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $repoRoot 'dist' }

$releaseDocuments = [ordered]@{
    'START-HERE.txt' = (Join-Path $launcherRoot 'PLAYER-GUIDE.txt')
    'LICENSE' = (Join-Path $repoRoot 'LICENSE')
    'NOTICE' = (Join-Path $repoRoot 'NOTICE')
}
foreach ($document in $releaseDocuments.GetEnumerator()) {
    if (-not (Test-Path -LiteralPath $document.Value -PathType Leaf)) {
        throw "Required release document is missing: $($document.Value)"
    }
}

$staging = Join-Path $OutputDirectory "staging-$Serial"

function Write-Step($message) { Write-Host "==> $message" -ForegroundColor Cyan }

if (-not (Test-Path -LiteralPath $Shim)) {
    throw "No shim at $Shim. Build it with client\build.cmd first."
}

$shimBytes = [System.IO.File]::ReadAllBytes($Shim)
if ($shimBytes.Length -lt 100000) {
    throw "The shim at $Shim is implausibly small ($($shimBytes.Length) bytes). Check the build."
}

Write-Step 'Publishing the launcher'
$publish = Join-Path $staging 'publish'
if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
New-Item -ItemType Directory -Path $publish -Force | Out-Null

& dotnet publish $appProject `
    --nologo -v q `
    --configuration Release `
    --runtime win-x64 `
    --self-contained false `
    -p:DebugType=none `
    --output $publish
if ($LASTEXITCODE -ne 0) {
    throw 'Publish failed.'
}

Write-Step 'Assembling the release folder'
$payload = Join-Path $staging "ProjectRevival17-r$Serial"
New-Item -ItemType Directory -Path $payload -Force | Out-Null

Copy-Item -Path (Join-Path $publish '*') -Destination $payload -Recurse -Force

Get-ChildItem -LiteralPath $payload -Filter '*.pdb' -Recurse | Remove-Item -Force

$packagedShimName = 'FIFA17Revival.Shim.dll'
Copy-Item -LiteralPath $Shim -Destination (Join-Path $payload $packagedShimName) -Force

foreach ($document in $releaseDocuments.GetEnumerator()) {
    Copy-Item -LiteralPath $document.Value -Destination (Join-Path $payload $document.Key) -Force
}

if (Test-Path -LiteralPath (Join-Path $payload 'version.dll')) {
    throw 'The release must not contain version.dll beside the launcher.'
}

if (Get-ChildItem -LiteralPath $payload -Directory) {
    throw 'Published output contains subdirectories, which the path-free release manifest cannot represent.'
}

$launcherExe = Join-Path $payload 'RevivalLauncher.exe'
if (-not (Test-Path -LiteralPath $launcherExe)) {
    throw 'The published output has no RevivalLauncher.exe.'
}

if ([System.IO.Path]::GetFileNameWithoutExtension($launcherExe).StartsWith(
        'FIFA17', [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'The launcher executable name collides with FIFA 17 process detection.'
}

$forbidden = @('FIFA17.exe', 'CardsDLL_Win64_retail.dll', 'dbdataEA.dll', 'EAWebKit.dll')
foreach ($name in $forbidden) {
    $found = Get-ChildItem -LiteralPath $payload -Filter $name -Recurse -ErrorAction SilentlyContinue
    if ($found) {
        throw "Refusing to pack $name. Nothing from a game installation may be redistributed."
    }
}

Write-Step 'Writing the manifest'

$launcherVersion = ([System.Diagnostics.FileVersionInfo]::GetVersionInfo($launcherExe)).ProductVersion
if (-not $launcherVersion) { throw 'The launcher has no product version.' }
$launcherVersion = ($launcherVersion -split '\+')[0]
if (-not $ShimVersion) { $ShimVersion = $launcherVersion }

function New-Artifact($role, $path) {
    $item = Get-Item -LiteralPath $path
    [ordered]@{
        role   = $role
        name   = $item.Name
        size   = $item.Length
        sha256 = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
    }
}

$manifest = [ordered]@{
    schema        = 1
    releaseSerial = $Serial
    releasedAt    = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    keyId         = $null
    versions      = [ordered]@{
        launcher = $launcherVersion
        shim     = $ShimVersion
        server   = $ServerVersion
        protocol = $ProtocolVersion
        content  = $ContentVersion
    }
    artifacts     = @()
}

foreach ($item in (Get-ChildItem -LiteralPath $payload -File | Sort-Object Name)) {
    $role = if ($item.Name -eq 'RevivalLauncher.exe') { 'launcher' }
            elseif ($item.Name -eq $packagedShimName) { 'shim' }
            else { 'support-' + $item.Name.ToLowerInvariant() }
    $manifest.artifacts += New-Artifact $role $item.FullName
}

$manifestPath = Join-Path $payload 'manifest.json'

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText(
    $manifestPath, ($manifest | ConvertTo-Json -Depth 6), $utf8NoBom)

Write-Step 'Validating the assembled release'
$written = [System.IO.File]::ReadAllText($manifestPath) | ConvertFrom-Json
foreach ($artifact in $written.artifacts) {
    $path = Join-Path $payload $artifact.name
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Assembled release validation failed: $($artifact.name) is missing."
    }
    $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
    if ($hash -ne $artifact.sha256 -or (Get-Item -LiteralPath $path).Length -ne $artifact.size) {
        throw "Assembled release validation failed: $($artifact.name) does not match the manifest."
    }
}

Write-Step 'Smoke-testing the packaged launcher process'
$smoke = Start-Process -FilePath $launcherExe `
    -ArgumentList '--smoke-test' `
    -WorkingDirectory $payload `
    -WindowStyle Hidden `
    -PassThru
if (-not $smoke.WaitForExit(15000)) {
    Stop-Process -Id $smoke.Id -Force
    throw 'Packaged launcher smoke test timed out.'
}
if ($smoke.ExitCode -ne 0) {
    throw "Packaged launcher smoke test crashed with exit code $($smoke.ExitCode)."
}
if (Test-Path -LiteralPath (Join-Path $payload 'fifa17-revival-log.txt')) {
    throw 'The packaged launcher loaded the FIFA shim into its own process.'
}

Write-Step 'Compressing'
$zipName = "ProjectRevival17-$launcherVersion-r$Serial.zip"
$zipPath = Join-Path $OutputDirectory $zipName
if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }

Compress-Archive -Path $payload -DestinationPath $zipPath -CompressionLevel Optimal

Remove-Item -LiteralPath $staging -Recurse -Force

$zipHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash

Write-Host ''
Write-Host "  $zipPath"
Write-Host "  SHA-256  $zipHash"
Write-Host ''
Write-Host '  Send this zip to your players privately, together with each player''s own invite code.'
Write-Host '  Players will see a SmartScreen warning on first run: More info, then Run anyway.'
Write-Host ''
