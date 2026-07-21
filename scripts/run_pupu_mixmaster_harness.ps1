param(
    [string]$UnidbgRoot = ".local/private/unidbg-work/unidbg",
    [string]$LibMixmaster = "../artifacts/apk/pupu-6.4.9-downkuai-apktool/lib/arm64-v8a/libmixmaster.so",
    [string]$Path = "/client/product/storeproduct/detail",
    [string]$DeviceFeed = "{}"
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$unidbg = Resolve-Path (Join-Path $repo $UnidbgRoot)
$lib = Resolve-Path (Join-Path $repo $LibMixmaster)
$harnessSrc = Resolve-Path (Join-Path $repo "scripts/unidbg/PupuMixmasterHarness.java")
$harnessDir = Join-Path $unidbg "unidbg-android/src/test/java/com/pupu/harness"
New-Item -ItemType Directory -Force $harnessDir | Out-Null
Copy-Item -LiteralPath $harnessSrc -Destination (Join-Path $harnessDir "PupuMixmasterHarness.java") -Force

Push-Location (Join-Path $unidbg "unidbg-android")
try {
    $env:MAVEN_OPTS = (($env:MAVEN_OPTS, "--add-opens java.base/java.util=ALL-UNNAMED") -join " ").Trim()
    & "..\mvnw.cmd" -s "..\.mvn\local-settings.xml" `
        "-Dmaven.test.skip=false" "-Dmaven.javadoc.skip=true" "-Dgpg.skip=true" `
        test-compile exec:java `
        "-Dexec.classpathScope=test" `
        "-Dexec.mainClass=com.pupu.harness.PupuMixmasterHarness" `
        "-Dexec.args=$lib $Path $DeviceFeed"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Pop-Location
}
