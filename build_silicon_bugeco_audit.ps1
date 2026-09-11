# Enriches the 117 confirmed-Si issues with formal bugeco/errata linkage audited via HSDES.
# Buckets: A = formal bugeco link; B = product-change (stepping) fix, no linked bugeco; C = needs review.

$src = Join-Path $PSScriptRoot 'sandstone_atscale_silicon_issues.csv'
$out = Join-Path $PSScriptRoot 'sandstone_atscale_silicon_bugeco_audit.csv'

# IDs with a formal subject='bugeco' link (verified via HSDES links, 2026-09-01).
$bugeco = @{
    '14026464067' = '13014355605'
    '14015032086' = '1308560873;1309522432;1309345419'
    '22010039282' = '1306993191'
}

Import-Csv $src | ForEach-Object {
    $hasBugeco = $bugeco.ContainsKey($_.id)
    $bucket = if ($hasBugeco) { 'A_bugeco_linked' }
              elseif ($_.status_reason -eq 'complete.product_changed') { 'B_product_change_no_bugeco' }
              else { 'C_needs_review' }
    [pscustomobject]@{
        id            = $_.id
        bucket        = $bucket
        bugeco_linked = if ($hasBugeco) { 'yes' } else { 'no' }
        bugeco_ids    = if ($hasBugeco) { $bugeco[$_.id] } else { '' }
        priority      = $_.priority
        status        = $_.status
        status_reason = $_.status_reason
        codename      = $_.codename
        title         = $_.title
        hsd_link      = $_.hsd_link
    }
} | Sort-Object bucket, id | Export-Csv $out -NoTypeInformation -Encoding UTF8

Write-Host "Wrote $out"
Import-Csv $out | Group-Object bucket | ForEach-Object { "{0}: {1}" -f $_.Name, $_.Count }
