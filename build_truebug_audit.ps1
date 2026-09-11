# Applies YS's sighting-based method: a 117-bug is a TRUE silicon bug if any linked
# sighting has conclusion='hw.bug'. Joins sighting root-cause fields + bugeco buckets.

$dir = 'c:\Users\rbalaji\AppData\Roaming\Code\User\workspaceStorage\d4037233e087c23f8a2885ab4b44d726\GitHub.copilot-chat\chat-session-resources\f045adc6-0b08-45e1-836c-082fba297f5d'
$files = @(
  "$dir\toolu_01CXmbcrBQ82bgzi2Q5zBAfS__vscode-1787294002968\content.json",
  "$dir\toolu_01QsDz1gnkyjiwHQpCkRWnYs__vscode-1787294002969\content.json",
  "$dir\toolu_01YUomyqx3Qydy2cM13kL4kF__vscode-1787294002970\content.json"
)

$sight = @{}
foreach ($f in $files) {
  $j = Get-Content $f -Raw | ConvertFrom-Json
  foreach ($a in $j.data.articles) {
    $sight[[string]$a.id] = [pscustomobject]@{
      status        = $a.status
      component     = $a.component
      conclusion    = $a.conclusion
      defect_history= $a.defect_history
    }
  }
}
Write-Host "sightings resolved:" $sight.Count

# bug -> list of sightings
$map = Import-Csv "$PSScriptRoot\_bug_sighting_map.csv"
$bySighting = $map | Group-Object bug_id

# bugeco buckets
$audit = @{}
Import-Csv "$PSScriptRoot\sandstone_atscale_silicon_bugeco_audit.csv" | ForEach-Object { $audit[$_.id] = $_ }

$rows = foreach ($g in $bySighting) {
  $bug = $g.Name
  $hwbugSid=''; $hwComp=''; $hwHist=''; $anyConcl=@()
  foreach ($row in $g.Group) {
    $sid = $row.sighting_id
    if ($sid -and $sight.ContainsKey($sid)) {
      $c = $sight[$sid].conclusion
      if ($c) { $anyConcl += "$sid=$c" }
      if ($c -eq 'hw.bug' -and -not $hwbugSid) {
        $hwbugSid = $sid; $hwComp = $sight[$sid].component; $hwHist = $sight[$sid].defect_history
      }
    }
  }
  $a = $audit[$bug]
  [pscustomobject]@{
    id                 = $bug
    bucket             = if($a){$a.bucket}else{''}
    bugeco_linked      = if($a){$a.bugeco_linked}else{''}
    bugeco_ids         = if($a){$a.bugeco_ids}else{''}
    sighting_hw_bug    = if($hwbugSid){'yes'}else{'no'}
    hw_bug_sighting_id = $hwbugSid
    sighting_component = $hwComp
    sighting_defect_history = $hwHist
    all_sighting_conclusions = ($anyConcl -join '; ')
    priority           = if($a){$a.priority}else{''}
    status             = if($a){$a.status}else{''}
    status_reason      = if($a){$a.status_reason}else{''}
    codename           = if($a){$a.codename}else{''}
    title              = if($a){$a.title}else{''}
    hsd_link           = if($a){$a.hsd_link}else{''}
  }
}

$rows = $rows | Sort-Object bucket, @{e={$_.sighting_hw_bug};Descending=$true}, id
$rows | Export-Csv "$PSScriptRoot\sandstone_atscale_silicon_TRUEbug_audit.csv" -NoTypeInformation -Encoding UTF8

Write-Host "`n=== TRUE silicon bug (sighting conclusion=hw.bug) x bucket ==="
$rows | Group-Object bucket, sighting_hw_bug | Sort-Object Name | ForEach-Object { "{0}: {1}" -f $_.Name, $_.Count }

Write-Host "`n=== Overall hw.bug count ==="
($rows | Where-Object { $_.sighting_hw_bug -eq 'yes' }).Count

Write-Host "`n=== B & C that ARE true silicon bugs ==="
$rows | Where-Object { $_.bucket -ne 'A_bugeco_linked' -and $_.sighting_hw_bug -eq 'yes' } | Format-Table id,bucket,sighting_component,sighting_defect_history,codename -AutoSize

Write-Host "`n=== distribution of ALL sighting conclusions (nature of bugs) ==="
$concl = @{}
foreach($r in $rows){ foreach($p in ($r.all_sighting_conclusions -split '; ')){ if($p){ $v=($p -split '=')[1]; if($v){ $concl[$v] = 1 + ($concl[$v] | ForEach-Object {$_}) } } } }
$concl.GetEnumerator() | Sort-Object Value -Descending | ForEach-Object { "{0}: {1}" -f $_.Key, $_.Value }
