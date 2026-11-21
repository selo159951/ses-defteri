# Sign files with the "Selim Oğuz" certificate from tools\make_cert.ps1:  .\tools\sign.ps1 dist\SesDefteri\SesDefteri.exe ...
# Without the certificate it only warns (the build still works, unsigned). A timestamp keeps the signature valid after
# the certificate expires; when the timestamp server cannot be reached the file is signed without one.
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Files)
$ErrorActionPreference = "Stop"
$subject = "CN=Selim Oğuz, O=Selim Oğuz"
$cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert | Where-Object { $_.Subject -eq $subject -and $_.NotAfter -gt (Get-Date) } |
    Sort-Object NotAfter -Descending | Select-Object -First 1
if (-not $cert) { Write-Warning "No signing certificate (run tools\make_cert.ps1 once): files stay unsigned"; return }
foreach ($f in $Files) {
    $sig = $null
    try { $sig = Set-AuthenticodeSignature -FilePath $f -Certificate $cert -HashAlgorithm SHA256 -TimestampServer "http://timestamp.digicert.com" }
    catch { Write-Warning "timestamp server not reached, signing without it: $_" }
    if (-not $sig -or -not $sig.SignerCertificate) { $sig = Set-AuthenticodeSignature -FilePath $f -Certificate $cert -HashAlgorithm SHA256 }
    if (-not $sig.SignerCertificate) { throw "could not sign $f : $($sig.StatusMessage)" }
    Write-Host "signed $f"
}
