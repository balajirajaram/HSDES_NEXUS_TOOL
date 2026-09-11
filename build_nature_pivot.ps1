# Builds a component x codename pivot of the 32 confirmed silicon logic bugs.

$r = Import-Csv "$PSScriptRoot\sandstone_atscale_silicon_TRUEbug_audit.csv"
$true1 = $r | Where-Object { $_.bugeco_linked -eq 'yes' -or $_.sighting_hw_bug -eq 'yes' }

# component label: fall back to 'hw.(bugeco-only)' when no hw.bug sighting component
$codes = @($true1 | Select-Object -ExpandProperty codename -Unique | Sort-Object)

$rows = $true1 | ForEach-Object {
    $comp = if ($_.sighting_component) { $_.sighting_component } else { 'hw.(bugeco-only)' }
    [pscustomobject]@{ component = $comp; codename = $_.codename }
} | Group-Object component | Sort-Object Name

$pivot = foreach ($g in $rows) {
    $o = [ordered]@{ component_nature = $g.Name }
    foreach ($c in $codes) { $o[$c] = @($g.Group | Where-Object { $_.codename -eq $c }).Count }
    $o['Total'] = $g.Count
    [pscustomobject]$o
}

# Grand-total row
$tot = [ordered]@{ component_nature = 'TOTAL' }
foreach ($c in $codes) { $tot[$c] = @($true1 | Where-Object { $_.codename -eq $c }).Count }
$tot['Total'] = $true1.Count
$pivot += [pscustomobject]$tot

$pivot | Export-Csv "$PSScriptRoot\sandstone_TRUE_silicon_bugs_nature_pivot.csv" -NoTypeInformation -Encoding UTF8
Write-Host "wrote sandstone_TRUE_silicon_bugs_nature_pivot.csv"
$pivot | Format-Table -AutoSize
