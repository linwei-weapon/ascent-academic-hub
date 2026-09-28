param(
  [Parameter(Mandatory=$true)][string]$SourceDirectory,
  [Parameter(Mandatory=$true)][string]$OutputFile
)
$ErrorActionPreference = 'Stop'
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
# Disable document macros before opening any supplied document.
$word.AutomationSecurity = 3
$items = @()
try {
  foreach ($file in (Get-ChildItem -LiteralPath $SourceDirectory -File | Where-Object { $_.Extension -in '.doc','.docx' } | Sort-Object Name)) {
    $document = $null
    try {
      $document = $word.Documents.Open($file.FullName, $false, $true, $false)
      $items += [pscustomobject]@{
        file_name = $file.Name
        file_hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLower()
        text = $document.Content.Text
        table_count = $document.Tables.Count
      }
      Write-Output ('Read ' + $file.Name)
    } finally { if ($null -ne $document) { $document.Close($false) } }
  }
} finally { $word.Quit(); [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null }
$parent = Split-Path -Parent $OutputFile
if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
$items | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $OutputFile -Encoding utf8
Write-Output ('Read-only extraction completed: ' + $items.Count)
