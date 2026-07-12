param(
  [Parameter(Mandatory = $true)][string]$SourceDirectory,
  [Parameter(Mandatory = $true)][string]$OutputFile
)

$ErrorActionPreference = 'Stop'
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
$items = @()
try {
  $files = Get-ChildItem -LiteralPath $SourceDirectory -File |
    Where-Object { $_.Extension -in '.doc', '.docx' } |
    Sort-Object Name
  foreach ($file in $files) {
    $document = $null
    try {
      $document = $word.Documents.Open($file.FullName, $false, $true)
      $tables = @()
      # 修读要求位于文档前部；只取前3个表格，跳过后面体量很大的课程计划表。
      $tableCount = $document.Tables.Count
      foreach ($tableIndex in 1, 2, 3) {
        if ($tableIndex -gt $document.Tables.Count) { break }
        $table = $document.Tables.Item($tableIndex)
        $tableTextBase64 = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($table.Range.Text))
        $cells = @()
        foreach ($cell in $table.Range.Cells) {
          if ($cell.RowIndex -gt 20) { break }
          $cellText = $cell.Range.Text -replace '[\x07\r]', ''
          $cells += [pscustomobject]@{
            row = $cell.RowIndex
            column = $cell.ColumnIndex
            text_utf16le_base64 = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($cellText))
          }
        }
        $tables += [pscustomobject]@{
          index = $tableIndex
          row_count = $table.Rows.Count
          column_count = $table.Columns.Count
          text_utf16le_base64 = $tableTextBase64
          preview_cells = $cells
        }
      }
      $items += [pscustomobject]@{
        file_name = $file.Name
        source_path = $file.FullName
        text_utf16le_base64 = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($document.Content.Text))
        table_count = [int]$document.Tables.Count
        tables = $tables
      }
    }
    finally {
      if ($null -ne $document) { $document.Close($false) }
    }
  }
}
finally {
  $word.Quit()
  [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
}

$parent = Split-Path -Parent $OutputFile
if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
$items | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $OutputFile -Encoding utf8
Write-Output ("Extracted {0} curriculum plans to {1}" -f $items.Count, $OutputFile)
