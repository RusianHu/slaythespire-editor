$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

Write-Host '==> 清理旧的 build / dist 产物...' -ForegroundColor Cyan
if (Test-Path '.\build') {
    Remove-Item '.\build' -Recurse -Force
}
if (Test-Path '.\dist') {
    Remove-Item '.\dist' -Recurse -Force
}

Write-Host '==> 开始构建《杀戮尖塔 2》单文件 exe...' -ForegroundColor Cyan
python .\setup.py build_exe

$metadataPath = Join-Path $ProjectRoot '.build\sts2_build_metadata.json'
if (-not (Test-Path $metadataPath)) {
    throw '未找到构建元数据文件：.build\sts2_build_metadata.json'
}

$metadata = Get-Content $metadataPath -Raw -Encoding UTF8 | ConvertFrom-Json
$expectedOutput = [string]$metadata.expected_output
if ([string]::IsNullOrWhiteSpace($expectedOutput)) {
    throw '构建元数据缺少 expected_output 字段'
}

if (-not (Test-Path $expectedOutput)) {
    throw ("未找到预期产物：{0}" -f $expectedOutput)
}

$exe = Get-Item $expectedOutput
$sizeMB = [math]::Round($exe.Length / 1MB, 2)
$versionInfo = $exe.VersionInfo

Write-Host ''
Write-Host '==> 构建完成' -ForegroundColor Green
Write-Host ("产物：{0}" -f $exe.FullName)
Write-Host ("大小：{0} MB" -f $sizeMB)
Write-Host ("显示版本：{0}" -f [string]$metadata.display_version)
Write-Host ("文件版本：{0}" -f $versionInfo.FileVersion)
Write-Host ("产品版本：{0}" -f $versionInfo.ProductVersion)

