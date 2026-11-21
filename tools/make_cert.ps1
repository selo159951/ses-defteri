# Run once: makes the free code-signing certificate "Selim Oğuz" (10 years) in the current user's certificate store.
#   .\tools\make_cert.ps1
# - The private key stays in Windows (Cert:\CurrentUser\My). Back it up with tools\backup_cert.ps1 (password protected .pfx):
#   installed apps only accept updates signed by this exact certificate.
# - The public part goes to installer\SesDefteri-imza.cer (safe to share).
# - Prints the thumbprint: put it into backend\version.py SIGNER_THUMBPRINT so the updater only installs our setups.
# Windows does not trust a self-made certificate, so SmartScreen still warns; the file properties show "Selim Oğuz".
$ErrorActionPreference = "Stop"
$subject = "CN=Selim Oğuz, O=Selim Oğuz"
$cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert | Where-Object { $_.Subject -eq $subject -and $_.NotAfter -gt (Get-Date) } |
    Sort-Object NotAfter -Descending | Select-Object -First 1
if ($cert) {
    Write-Host "Certificate already exists."
} else {
    $cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject $subject -FriendlyName "Ses Defteri imza" `
        -KeyAlgorithm RSA -KeyLength 3072 -HashAlgorithm SHA256 -KeyExportPolicy Exportable `
        -NotAfter (Get-Date).AddYears(10) -CertStoreLocation Cert:\CurrentUser\My
    Write-Warning "Back it up now with .\tools\backup_cert.ps1 (asks for a password). Without the certificate, installed apps refuse later updates."
}
Export-Certificate -Cert $cert -FilePath (Join-Path $PSScriptRoot "..\installer\SesDefteri-imza.cer") | Out-Null
Write-Host "Thumbprint: $($cert.Thumbprint)"
