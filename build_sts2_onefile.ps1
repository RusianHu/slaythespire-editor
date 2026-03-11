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

if (-not (Test-Path '.\dist\slaythespire-editor-sts2.exe')) {
    throw '未找到预期产物：dist\slaythespire-editor-sts2.exe'
}

$exe = Get-Item '.\dist\slaythespire-editor-sts2.exe'
$sizeMB = [math]::Round($exe.Length / 1MB, 2)

Write-Host ''
Write-Host '==> 构建完成' -ForegroundColor Green
Write-Host ("产物：{0}" -f $exe.FullName)
Write-Host ("大小：{0} MB" -f $sizeMB)

