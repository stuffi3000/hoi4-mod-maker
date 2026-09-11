# HOI4 Map Maker Workshop deploy (safe)
#
# Run build_exe.bat first to create dist/HOI4MapMaker/.
#
# Safety rules:
# - Delete only HOI4MapMaker.exe and _internal/ from the MOD directory.
# - Preserve thumbnail.png, common/, localisation/, and all other files.
# - Edit the outer .mod and descriptor.mod in place, changing only version fields.
# - Never touch Steam Workshop fields such as picture, remote_file_id, or path.
#
# Read the version automatically from the VERSION field in ../version.py.
$ErrorActionPreference = "Stop"

# The upload source is mod\1, the numbered directory created by the launcher
# Upload Mod tool (remote_file_id=3707251866).
# mod\hoi4_map_maker was a planned rename that was never deployed; keep this path.
$MOD_DIR = "D:\Documents\Paradox Interactive\Hearts of Iron IV\mod\1"
$OUTER_MOD = "D:\Documents\Paradox Interactive\Hearts of Iron IV\mod\1.mod"
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$REPO_ROOT = Split-Path -Parent $SCRIPT_DIR
$DIST_DIR = Join-Path $REPO_ROOT "dist\HOI4MapMaker"
$VERSION_PY = Join-Path $REPO_ROOT "version.py"
$SUP_VER = "1.19.*"

# Read VERSION from version.py.
$verLine = Get-Content $VERSION_PY | Where-Object { $_ -match '^VERSION\s*=' } | Select-Object -First 1
if (-not $verLine -or $verLine -notmatch '"([^"]+)"') {
    Write-Error "Cannot parse VERSION from $VERSION_PY"
    exit 1
}
$VER = $Matches[1]

Write-Output "Deploying v$VER to $MOD_DIR"

# Sanity checks
if (-not (Test-Path $MOD_DIR)) {
    Write-Error "MOD_DIR missing: $MOD_DIR`nFirst-time deploy must be manual (create dir + thumbnail.png + outer .mod with remote_file_id from Steam)."
    exit 1
}
# The outer .mod is absent in the mod\1 layout because the launcher reads the
# descriptor.mod inside the directory; patch it only when it exists.
$HAS_OUTER = Test-Path $OUTER_MOD
if (-not (Test-Path (Join-Path $DIST_DIR "HOI4MapMaker.exe"))) {
    Write-Error "Build missing: $DIST_DIR\HOI4MapMaker.exe`nRun build_exe.bat first."
    exit 1
}

Write-Output "[1/4] Delete old exe + _internal (keep thumbnail/common/localisation)..."
$exeTarget = Join-Path $MOD_DIR "HOI4MapMaker.exe"
$internalTarget = Join-Path $MOD_DIR "_internal"
if (Test-Path $exeTarget) { Remove-Item -Force $exeTarget }
if (Test-Path $internalTarget) { Remove-Item -Recurse -Force $internalTarget }

Write-Output "[2/4] Copy new build..."
Copy-Item -Path (Join-Path $DIST_DIR "HOI4MapMaker.exe") -Destination $MOD_DIR
Copy-Item -Path (Join-Path $DIST_DIR "_internal") -Destination $MOD_DIR -Recurse

Write-Output "[3/4] In-place patch descriptor.mod version fields..."
$descPath = Join-Path $MOD_DIR "descriptor.mod"
(Get-Content $descPath) | ForEach-Object {
    if ($_ -match '^version=') { "version=`"$VER`"" }
    elseif ($_ -match '^supported_version=') { "supported_version=`"$SUP_VER`"" }
    else { $_ }
} | Set-Content $descPath -Encoding utf8

if ($HAS_OUTER) {
    Write-Output "[3/4] In-place patch outer .mod (preserve picture / remote_file_id / path)..."
    (Get-Content $OUTER_MOD) | ForEach-Object {
        if ($_ -match '^version=') { "version=`"$VER`"" }
        elseif ($_ -match '^supported_version=') { "supported_version=`"$SUP_VER`"" }
        else { $_ }
    } | Set-Content $OUTER_MOD -Encoding utf8
} else {
    Write-Output "[3/4] No outer .mod (mod\1 layout) - skip."
}

Write-Output "[4/4] Verify Workshop key fields preserved..."
$descContent = Get-Content $descPath -Raw
if ($descContent -notmatch 'remote_file_id="\d+"') {
    Write-Warning "remote_file_id missing from descriptor.mod after deploy! Steam Workshop upload will create a new entry."
}
Write-Output "--- descriptor.mod after deploy ---"
Get-Content $descPath

Write-Output "`n=== Deploy OK ==="
Write-Output "Next: HOI4 launcher -> Mod Tools -> Upload Mod -> hoi4_map_maker"
