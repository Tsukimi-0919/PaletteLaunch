<#
.SYNOPSIS
    PaletteLaunch のテスト・ビルド・配布用 zip の作成を一括で行う。

.DESCRIPTION
    1. src\version.py からバージョンを読み取る
    2. pytest を実行する（-SkipTests で省略可）
    3. PyInstaller（PaletteLaunch.spec, onedir）でビルドする
    4. dist\PaletteLaunch-v<version>-win64.zip を作成する
       - settings.json（利用者の設定）とそのバックアップ類は含めない
         （dist 内のファイルは消さず、除外したコピーを build\package に作ってから固める）
    5. zip の中身を検査し、SHA-256 を表示する

    詳しくは docs\build.md を参照。

.EXAMPLE
    .\build.ps1
.EXAMPLE
    .\build.ps1 -SkipTests
.EXAMPLE
    .\build.ps1 -SkipBuild   # 既存の dist\PaletteLaunch から zip だけ作り直す
#>
[CmdletBinding()]
param(
    # テストを省略する（通常は付けない）
    [switch]$SkipTests,
    # ビルドを省略し、既存の dist\PaletteLaunch から zip だけを作る
    [switch]$SkipBuild
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Root = $PSScriptRoot
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$Spec = Join-Path $Root 'PaletteLaunch.spec'
$VersionFile = Join-Path $Root 'src\version.py'
$DistDir = Join-Path $Root 'dist'
$AppDir = Join-Path $DistDir 'PaletteLaunch'
$StageRoot = Join-Path $Root 'build\package'
$StageDir = Join-Path $StageRoot 'PaletteLaunch'

# zip に含めないファイル（利用者の設定とそのバックアップ・退避ファイル）
#   settings.YYYYMMDD.bak.json は日ごとのバックアップ、settings.json.*.tmp は保存途中の一時ファイル
$ExcludePatterns = @('settings.json', 'settings.json.bak', 'settings.*.bak.json',
                     'settings.corrupt-*.json', 'settings.json.*.tmp')

function Write-Step([string]$Message) {
    Write-Host ''
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-Checked([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "コマンドが失敗しました (exit $LASTEXITCODE): $Exe $($Arguments -join ' ')"
    }
}

Push-Location $Root
try {
    # --- 0. 前提の確認 ---------------------------------------------------------
    if (-not (Test-Path $Python)) {
        throw ".venv が見つかりません。docs\build.md の「開発環境の準備」を先に実行してください: $Python"
    }

    # 引数に " を含めない（Windows PowerShell 5.1 は外部コマンドへの引数から " を落とすため）
    $bits = (& $Python -c 'import sys; print(64 if sys.maxsize > 2**32 else 32)').Trim()
    if ($bits -ne '64') {
        throw "64bit 版の Python が必要です（現在: ${bits}bit）。"
    }

    # --- 1. バージョン -----------------------------------------------------------
    Write-Step 'バージョンの読み取り'
    $versionText = Get-Content -Raw -Encoding UTF8 $VersionFile
    $match = [regex]::Match($versionText, '(?m)^__version__\s*=\s*"(\d+\.\d+\.\d+)"\s*$')
    if (-not $match.Success) {
        throw "src\version.py から __version__ (x.y.z 形式) を読み取れません。"
    }
    $Version = $match.Groups[1].Value
    $ZipName = "PaletteLaunch-v$Version-win64.zip"
    $ZipPath = Join-Path $DistDir $ZipName
    Write-Host "version: $Version"

    # git の状態は警告のみ（ビルドは止めない）
    if (Get-Command git -ErrorAction SilentlyContinue) {
        $dirty = git status --porcelain
        if ($dirty) {
            Write-Warning 'コミットされていない変更があります。配布物は作業中の状態からビルドされます。'
        }
        $tagCommit = git rev-parse -q --verify "refs/tags/v$Version^{commit}" 2>$null
        $headCommit = git rev-parse HEAD
        if ($tagCommit -and ($tagCommit -ne $headCommit)) {
            Write-Warning "タグ v$Version は HEAD 以外のコミットを指しています。src\version.py の更新を忘れていないか確認してください。"
        }
    }

    # --- 2. テスト ---------------------------------------------------------------
    if ($SkipTests -or $SkipBuild) {
        Write-Warning 'テストを省略しました。'
    } else {
        Write-Step 'テスト (pytest)'
        Invoke-Checked $Python @('-m', 'pytest', '-q')
    }

    # --- 3. ビルド ---------------------------------------------------------------
    if ($SkipBuild) {
        Write-Warning "ビルドを省略しました (-SkipBuild)。既存の $AppDir を使います。"
    } else {
        Write-Step 'ビルド (PyInstaller)'
        # 注意: PyInstaller は dist\PaletteLaunch を作り直す（中に置いた settings.json も消える）
        Invoke-Checked $Python @('-m', 'PyInstaller', $Spec, '--clean', '--noconfirm')
    }

    $exe = Join-Path $AppDir 'PaletteLaunch.exe'
    if (-not (Test-Path $exe)) {
        throw "ビルド結果が見つかりません: $exe"
    }

    # --- 4. zip の作成 -----------------------------------------------------------
    Write-Step "zip の作成 ($ZipName)"

    # dist 内のファイルは消さずに、除外ファイルを除いたコピーを作ってから固める
    if (Test-Path $StageRoot) {
        Remove-Item -LiteralPath $StageRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Path $StageDir -Force | Out-Null
    $appDirFull = (Resolve-Path -LiteralPath $AppDir).Path.TrimEnd('\')
    Get-ChildItem -LiteralPath $appDirFull -Recurse -File | ForEach-Object {
        $file = $_
        $excluded = $false
        foreach ($pattern in $ExcludePatterns) {
            if ($file.Name -like $pattern) { $excluded = $true }
        }
        if ($excluded) {
            Write-Warning "zip に含めません: $($file.FullName)"
            return
        }
        $relative = $file.FullName.Substring($appDirFull.Length + 1)
        $dest = Join-Path $StageDir $relative
        $destDir = Split-Path -Parent $dest
        if (-not (Test-Path -LiteralPath $destDir)) {
            New-Item -ItemType Directory -Path $destDir -Force | Out-Null
        }
        Copy-Item -LiteralPath $file.FullName -Destination $dest
    }

    if (Test-Path $ZipPath) {
        Remove-Item -LiteralPath $ZipPath -Force
    }
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    # zip 内は PaletteLaunch\ フォルダ以下に収める（展開するとフォルダごと出てくる）
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $StageDir, $ZipPath, [System.IO.Compression.CompressionLevel]::Optimal, $true)
    Remove-Item -LiteralPath $StageRoot -Recurse -Force

    # --- 5. 検査 -----------------------------------------------------------------
    Write-Step 'zip の検査'
    $zip = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        $entries = @($zip.Entries | ForEach-Object { $_.FullName.Replace('\', '/') })
    } finally {
        $zip.Dispose()
    }

    $required = @(
        'PaletteLaunch/PaletteLaunch.exe',
        'PaletteLaunch/_internal/settings.json.example',
        'PaletteLaunch/_internal/src/ui/index.html',
        'PaletteLaunch/_internal/src/ui/vendor/Sortable.min.js',
        'PaletteLaunch/_internal/src/ui/fonts/fonts.css'
    )
    foreach ($r in $required) {
        if ($entries -notcontains $r) {
            throw "zip に必要なファイルがありません: $r"
        }
    }
    foreach ($e in $entries) {
        $name = ($e -split '/')[-1]
        foreach ($pattern in $ExcludePatterns) {
            if ($name -like $pattern) {
                throw "zip に含めてはいけないファイルがあります: $e"
            }
        }
    }

    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $ZipPath).Hash.ToLowerInvariant()
    $sizeMB = [math]::Round((Get-Item -LiteralPath $ZipPath).Length / 1MB, 1)

    Write-Host ''
    Write-Host '完了しました。' -ForegroundColor Green
    Write-Host "  zip    : $ZipPath"
    Write-Host "  size   : $sizeMB MB ($($entries.Count) entries)"
    Write-Host "  sha256 : $hash"
    Write-Host ''
    Write-Host '配布前に docs\build.md の「起動確認」を実施してください。'
}
finally {
    Pop-Location
}
