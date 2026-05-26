<#
.SYNOPSIS
  legal-cn-core-codices 安装脚本
.DESCRIPTION
  将 162 部法律全文 JSON 部署到指定目录。
  本仓库通常作为其他仓库的依赖被自动安装，也可独立使用。
#>
$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host "=== core-codices v0.2-beta === 162 部中国法律全文 JSON" -ForegroundColor Green
Write-Host "  路径: $RepoRoot" -ForegroundColor Cyan
Write-Host "  已就绪，无需额外操作。" -ForegroundColor Green
