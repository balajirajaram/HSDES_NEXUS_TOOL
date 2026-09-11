$r = Import-Csv "$PSScriptRoot\sandstone_atscale_silicon_TRUEbug_audit.csv"
$true1 = $r | Where-Object { $_.bugeco_linked -eq 'yes' -or $_.sighting_hw_bug -eq 'yes' }

$true1 | ForEach-Object {
  [pscustomobject]@{
    atscale_hsd_id      = $_.id
    atscale_hsd_link    = $_.hsd_link
    confirmed_via       = if ($_.bugeco_linked -eq 'yes' -and $_.sighting_hw_bug -eq 'yes') {'bugeco+sighting'}
                          elseif ($_.bugeco_linked -eq 'yes') {'bugeco'} else {'sighting_hw.bug'}
    bugeco_hsd_ids      = $_.bugeco_ids
    rootcause_sighting  = $_.hw_bug_sighting_id
    component_nature    = $_.sighting_component
    defect_history      = $_.sighting_defect_history
    codename            = $_.codename
    priority            = $_.priority
    status              = $_.status
    resolution          = $_.status_reason
    title               = $_.title
  }
} | Sort-Object component_nature, atscale_hsd_id |
Export-Csv "$PSScriptRoot\sandstone_TRUE_silicon_bugs_for_excel.csv" -NoTypeInformation -Encoding UTF8

Write-Host "wrote sandstone_TRUE_silicon_bugs_for_excel.csv (rows:" ($true1.Count) ")"
