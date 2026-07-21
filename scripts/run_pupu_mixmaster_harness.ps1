param(
    [string]$UnidbgRoot = ".local/private/unidbg-work/unidbg",
    [string]$LibMixmaster = "../artifacts/apk/pupu-6.4.9-downkuai-apktool/lib/arm64-v8a/libmixmaster.so",
    [string]$Path = "/client/product/storeproduct/detail",
    [string]$DeviceFeed = "{}",
    [switch]$SignerMode
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$unidbg = Resolve-Path (Join-Path $repo $UnidbgRoot)
$lib = Resolve-Path (Join-Path $repo $LibMixmaster)
$harnessSrc = Resolve-Path (Join-Path $repo "scripts/unidbg/PupuMixmasterHarness.java")
$harnessDir = Join-Path $unidbg "unidbg-android/src/test/java/com/pupu/harness"
New-Item -ItemType Directory -Force $harnessDir | Out-Null
Copy-Item -LiteralPath $harnessSrc -Destination (Join-Path $harnessDir "PupuMixmasterHarness.java") -Force

$inputFile = $null
if ($SignerMode) {
    $inputFile = [System.IO.Path]::GetTempFileName()
    [System.IO.File]::WriteAllText($inputFile, [Console]::In.ReadToEnd(), [System.Text.UTF8Encoding]::new($false))
}

Push-Location (Join-Path $unidbg "unidbg-android")
try {
    $env:MAVEN_OPTS = (($env:MAVEN_OPTS, "--add-opens java.base/java.util=ALL-UNNAMED") -join " ").Trim()
    if ($SignerMode) {
        $execArgs = "--signer $lib $inputFile"
        $previousErrorActionPreference = $ErrorActionPreference
        $previousNativePreference = $null
        if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -Scope Global -ErrorAction SilentlyContinue) {
            $previousNativePreference = $Global:PSNativeCommandUseErrorActionPreference
            $Global:PSNativeCommandUseErrorActionPreference = $false
        }
        try {
            $ErrorActionPreference = "Continue"
            $output = & "..\mvnw.cmd" -s "..\.mvn\local-settings.xml" `
                "-Dmaven.test.skip=false" "-Dmaven.javadoc.skip=true" "-Dgpg.skip=true" `
                test-compile exec:java `
                "-Dexec.classpathScope=test" `
                "-Dexec.mainClass=com.pupu.harness.PupuMixmasterHarness" `
                "-Dexec.args=$execArgs" 2>&1
            $exitCode = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $previousErrorActionPreference
            if ($null -ne $previousNativePreference) {
                $Global:PSNativeCommandUseErrorActionPreference = $previousNativePreference
            }
        }
        $jsonLine = $null
        foreach ($line in $output) {
            $text = [string]$line
            if ($text.TrimStart().StartsWith("{")) {
                try {
                    $null = $text | ConvertFrom-Json -ErrorAction Stop
                    $jsonLine = $text
                    continue
                } catch {
                    # Not the final JSON payload; keep it as diagnostic output.
                }
            }
            [Console]::Error.WriteLine($text)
        }
        if ($exitCode -ne 0) { exit $exitCode }
        if (-not $jsonLine) { throw "mixmaster signer did not emit JSON" }
        [Console]::Out.WriteLine($jsonLine)
    } else {
        & "..\mvnw.cmd" -s "..\.mvn\local-settings.xml" `
            "-Dmaven.test.skip=false" "-Dmaven.javadoc.skip=true" "-Dgpg.skip=true" `
            test-compile exec:java `
            "-Dexec.classpathScope=test" `
            "-Dexec.mainClass=com.pupu.harness.PupuMixmasterHarness" `
            "-Dexec.args=$lib $Path $DeviceFeed"
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
} finally {
    Pop-Location
    if ($inputFile -and (Test-Path $inputFile)) {
        Remove-Item -LiteralPath $inputFile -Force
    }
}
