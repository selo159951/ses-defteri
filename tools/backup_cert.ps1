# Back up the "Selim Oğuz" signing certificate to Documents\SesDefteri-imza.pfx, protected by a password you type.
#   .\tools\backup_cert.ps1
# Keep the .pfx and the password somewhere safe (USB stick, password manager). On a new PC:
#   Import-PfxCertificate -FilePath SesDefteri-imza.pfx -CertStoreLocation Cert:\CurrentUser\My -Password (Read-Host -AsSecureString)
# Installed apps only accept updates signed by this exact certificate, so losing it means users must reinstall by hand.
$ErrorActionPreference = "Stop"
$subject = "CN=Selim Oğuz, O=Selim Oğuz"
$cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert | Where-Object { $_.Subject -eq $subject } |
    Sort-Object NotAfter -Descending | Select-Object -First 1
if (-not $cert) { throw "No certificate: run tools\make_cert.ps1 first" }
$pw = Read-Host -AsSecureString "Yedek için parola"
$pw2 = Read-Host -AsSecureString "Parola (tekrar)"
$a = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($pw))
$b = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($pw2))
if ($a -ne $b -or $a.Length -lt 8) { throw "Parolalar aynı değil ya da 8 karakterden kısa" }
$pfx = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "SesDefteri-imza.pfx"
Export-PfxCertificate -Cert $cert -FilePath $pfx -Password $pw | Out-Null
Write-Host "Yedek: $pfx  (parmak izi $($cert.Thumbprint))"
