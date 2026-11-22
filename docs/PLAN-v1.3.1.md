# Ses Defteri 1.3.1 planı

Kaynak: kullanıcının 22.11.2026 akşamki istekleri. Sırayla yapılır, her adımdan sonra `[x]` + commit hash.
Önceki plan: `docs/PLAN-v1.3.0.md` (bitti). Yanıtlar Türkçe; az token; alt ajanlar `sonnet`.

## Yapıldı (cfc413f, henüz derlenmedi / yayınlanmadı)
- [x] Asistan:
  - Selam/teşekkür/nasılsın sorularına model çalıştırılmadan cevap veriliyor.
  - Belirsiz sorularda kullanıcıya geri soruluyor.
  - O gün kayıt yoksa en yakın kayıt tarihi söyleniyor.
  - Önceki sorunun tarihi yalnızca gerçek bir devam sorusuna aktarılıyor.
  - Ay ve gün adları artık arama kelimesi sayılmıyor.
  - Sohbet en alta kayıyor. Yeni testler `tests/test_chat.py`, toplam 494 test geçiyor.
- [x] Kişiler: Sözlük açılır pencerede açılıyor (`#glossDlg`, `people.js` `openGlossary`).
- [x] Tek düğme boyutu: `button.small` normal boyutta. Textarea'lar genel stilde (yazı tipi, çerçeve).
- [x] Sol menü:
  - Dosyalar: `nav.js`, `#sidenav`. Hamburger düğmesi menüyü simgelere katlıyor, katlı/açık durumu localStorage'da tutuluyor.
  - 900 pikselden dar pencerede menü sayfanın üstüne açılıyor (`navpeek`).
  - Eski `<header>` kaldırıldı.
- [x] Ayarlar sayfası:
  - Sekmeler: Görünüm, Kayıt, Tutanak, Güncelleme.
  - Onay kutuları anahtar biçiminde.
  - "Arayüz boyutu" seçimi: WebView2 `ZoomFactor`, `bridge.apply_zoom`/`watch_zoom`, ayar `ui_zoom`. Ctrl + tekerlek ile değişen boyut da kaydediliyor.
- [x] Toplantı kaydı karıştırması (`meeting_recorder.mix`):
  - Kanallar konuşma seviyesine göre ayarlanıyor, en fazla 4 kat.
  - Mikrofon gürültüsü konuşma yokken kısılıyor.
  - Bilgisayardan ses gelirken mikrofon kısılıyor (hoparlör yankısı).
  - Teşhis: yalnızca bilgisayar sesiyle yapılan gerçek kayıtta iki konuşmacı doğru ayrılıyor. Mikrofon açıkken her şey tek konuşmacıya düşüyordu.

## Yapılacaklar (sırayla)
1. [ ] **Karıştırma düzeltmesini doğrula**
   - Daha güçlü yapay yankıyla (`scratchpad/mix_exp.py`: yankı 0.5 ve uzun oda yankısı) eski yöntemin bozulduğunu, yenisinin ayırdığını göster.
   - `mix()` için birim test: hoparlör sesi varken mikrofon kısılıyor, kullanıcının kendi sesi korunuyor.
   - Kullanıcı mikrofonu açınca gerçek kayıtla tekrar dene: `play_dialog.py` + `start_meeting`.
   - Test ses dosyaları: `scratchpad/teams/l1..l8.mp3`, `diyalog.wav` (EVREN tts, emre/ece).
2. [ ] **Hitaptan konuşmacı adı**
   - "Günaydın Ece", "Ece, …", "…, Ece?" gibi hitaplarda adı söyleyen kişiye değil, ondan sonra konuşan farklı kişiye ver.
   - Ad bulma kuralları "ben Selim", "Umut sen…" ile aynı yerde: `backend/` içinde ad bulan modül (grep `benim adım`).
   - Test: sanal diyalogda Konuşmacı 2 → Ece.
3. [ ] **Konuşmacı seçicisi**: satırlardaki açılır kutu adı kesiyor ("Konuşmacı 1" sığmıyor). Kutuyu genişlet veya içeriğe göre boyutlandır, bütün yakınlaştırma oranlarında kontrol et.
4. [ ] **Ayarlar sekmeleri sabit kalsın** (iPhone Ayarlar gibi): sol sekme listesi yerinde dursun, yalnızca sağ taraf kaysın ve değişsin. Yöntem: `.slayout` için yükseklik `calc(100vh - üst)` ve `.sbody` için `overflow:auto`, ya da `.stabs` için `position:sticky`; ana kaydırma sağ panelde olsun.
5. [ ] **Sistem sayfasına da sekmeler**: Ayarlar'daki düzenin aynısı. Örnek gruplar: Donanım, Konuşma motoru ve modeller, Toplantı modu (LLM), Anlam arama, Gürültü, Klasör izleme. `system.js` veya app.js içindeki sistem bölümüne bak.
6. [ ] **Boş sayfalar**: sayfanın ortası boş kalmasın. Simgeli, ortalanmış bir boş durum gösterilsin ("Henüz kayıtlı kişi yok" + ne işe yaradığı + düğme): Kişiler, Asistan ilk açılış, kayıt listesi boşken, Öğrenilen düzeltmeler. Sayfalardaki küçük yazılar (12–13 px) büyütülsün: `.hint`, `.pmeta`, sayfa açıklamaları en az 14–15 px.
7. [ ] **Her sayfada iskelet (skeleton) yükleme**: Asistan, Kişiler, Ayarlar, Sistem, kayıt açılışı, Analiz sekmesi. `skeleton.js` (`skeleton(root, kind)`) var; eksik sayfalara ekle ve türleri genişlet.
8. [ ] **Tüm oranları kontrol et**
   - `scratchpad/overflow.js` (CDP): %100, %125, %150, %175 yakınlaştırmada ve dar pencerede (1024×700, 800×600) bütün sayfalarda yatay taşma olmamalı.
   - Menü katlı ve açık hâllerinde ekran görüntüsü al.
9. [ ] **Basit sürüm** (kullanıcı EVREN'in kullanılmasını istedi, onay verildi)
   - Ana sürümdeki değişiklikleri aktar: tek düğme boyutu, textarea stili, arayüz boyutu (bridge + app.py), sekmeli Ayarlar (`settings.js` ortak), mix düzeltmesi, updater DETACHED düzeltmesi (zaten f3c674c).
   - Sol menü Basit'e de gerekiyor mu? Basit'in başlığı sade, önce bak, sade kalsın.
   - EVREN ile inceleme: `evren-claude.cmd -Model glm-5.3` ile git worktree içinde "Basit Sürüm'ü baştan sona incele, hataları listele". EVREN bazen zaman aşımına uğruyor; o zaman `deepseek-v4.1-flash`, olmazsa sonnet alt ajan.
   - Bulunan hataları düzelt, testleri çalıştır (380+). Gerçek uygulamada CDP ile kontrol et (`SESDEFTERIBASIT_HOME`).
10. [ ] **Sürüm 1.3.1**
    - `version.py` → 1.3.1, release notları (Türkçe).
    - Derleme: ana sürüm `build_windows.ps1 -Gpu`, Basit kendi betiğiyle. Ardından imza kontrolü ve `edition.txt` kontrolü.
    - GitHub release v1.3.1 + 4 dosya (`tools/dev/upload.sh`). Büyük NVIDIA dosyası bazen TLS hatası veriyor, yeniden dene.
    - `make_release_json.py` ile `surum.json` üret, FTP'ye yükle.
      - FTP bilgileri: `Desktop\Projeler\Ses Defteri\sesdefteri@selimoguz.com.tr ftp.txt`. Satır 1 kullanıcı adı, satır 3 şifre; asla yazdırma, şifreyi geçici bir netrc dosyasına koy ve iş bitince sil.
      - Sunucu: `ftp.selimoguz.com.tr`, kök klasör `/ses-defteri/`. `curl -k --ssl-reqd`, çünkü sertifika adı tutmuyor.
    - Bu bilgisayardaki kurulu sürümü (NVIDIA) güncelle.
11. [ ] Hafızayı güncelle; kullanıcıya özet ver.

## Notlar
- Test kopyası: `SESDEFTERI_HOME=scratchpad\uihome` ve `SESDEFTERI_MODEL_DIR=%APPDATA%\SesDefteri\models`, CDP portu 9333.
  - Kullanıcının kurulu Ses Defteri'si açıkken aynı WebView verisi kullanılamaz; ayrı ev klasörü şart.
  - Türkçe JS kodunu `node cdp.mjs eval`'a PowerShell'den değil Bash'ten ver.
- Büyük JS dosyaları önbellekten gelebilir: kod değiştikten sonra uygulamayı yeniden başlat.
- Kullanıcının kurulu NVIDIA uygulaması bu bilgisayarda açık olabilir: kapatma.
- Rehber düğmesi kaldırıldı (39299b1), 1.3.1 ile kullanıcılara gidecek.
