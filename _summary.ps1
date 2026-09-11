$r = Import-Csv "$PSScriptRoot\sandstone_atscale_silicon_TRUEbug_audit.csv"
Write-Host "=== Combined TRUE silicon bug (bugeco OR hw.bug sighting) ==="
$true1 = $r | Where-Object { $_.bugeco_linked -eq 'yes' -or $_.sighting_hw_bug -eq 'yes' }
Write-Host "total:" $true1.Count
$true1 | Group-Object bucket | ForEach-Object { "  {0}: {1}" -f $_.Name,$_.Count }
Write-Host "`n=== STRICT YS (conclusion=hw.bug AND defect_history=new) ==="
$strict = $r | Where-Object { $_.sighting_hw_bug -eq 'yes' -and $_.sighting_defect_history -eq 'new' }
Write-Host "total:" $strict.Count
$strict | Group-Object bucket | ForEach-Object { "  {0}: {1}" -f $_.Name,$_.Count }
Write-Host "`n=== TRUE silicon bugs by component (nature) ==="
$true1 | Where-Object { $_.sighting_component } | Group-Object sighting_component | Sort-Object Count -Descending | ForEach-Object { "  {0}: {1}" -f $_.Name,$_.Count }
Write-Host "`n=== TRUE silicon bugs by codename ==="
$true1 | Group-Object codename | Sort-Object Count -Descending | ForEach-Object { "  {0}: {1}" -f $_.Name,$_.Count }
