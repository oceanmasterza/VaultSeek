# Create and configure the VaultSeek GitHub Project board.
#
# Prerequisites:
#   gh auth refresh -h github.com -s project,read:project
#   (complete browser device login when prompted)
#
# Usage (from repo root):
#   .\scripts\setup-github-project.ps1

$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path "$PSScriptRoot\..")

$Owner = "oceanmasterza"
$Title = "VaultSeek"
$Repo = "VaultSeek"
$StageOptions = @(
    "Ideas",
    "Architecture Ready",
    "Ready for Development",
    "In Progress",
    "Testing",
    "Completed"
)

Write-Host "==> Checking gh project scope"
$status = gh auth status 2>&1 | Out-String
if ($status -notmatch "project") {
    Write-Error @"
Missing 'project' scope on gh token.

Run in an interactive terminal:
  gh auth refresh -h github.com -s project,read:project

Complete the browser device login, then re-run this script.
"@
}

Write-Host "==> Looking for existing project '$Title'"
$existing = gh project list --owner $Owner --format json 2>$null | ConvertFrom-Json
$project = $existing.projects | Where-Object { $_.title -eq $Title } | Select-Object -First 1

if ($null -eq $project) {
    Write-Host "==> Creating project"
    $created = gh project create --owner $Owner --title $Title --format json | ConvertFrom-Json
    $projectNumber = $created.number
    $projectUrl = $created.url
} else {
    $projectNumber = $project.number
    $projectUrl = $project.url
    Write-Host "Found existing project #$projectNumber"
}

Write-Host "==> Linking repository $Owner/$Repo"
gh project link $projectNumber --owner $Owner --repo "$Owner/$Repo" 2>$null

Write-Host "==> Listing project fields"
$fieldsJson = gh project field-list $projectNumber --owner $Owner --format json | ConvertFrom-Json
$stageField = $fieldsJson.fields | Where-Object { $_.name -eq "Stage" } | Select-Object -First 1

if ($null -eq $stageField) {
    Write-Host "==> Creating Stage field (board columns)"
    $options = ($StageOptions -join ",")
    gh project field-create $projectNumber --owner $Owner `
        --name "Stage" `
        --data-type "SINGLE_SELECT" `
        --single-select-options $options | Out-Null
} else {
    Write-Host "Stage field already exists (id: $($stageField.id))"
}

Write-Host ""
Write-Host "Project URL: $projectUrl"
Write-Host ""
Write-Host "Optional UI step: open the project board view and set 'Group by' to Stage"
Write-Host "if columns do not show the six stages automatically."
