# Ses Defteri v1.3.0 planı

> **Bu dosya işin ana kaydıdır.** Sohbet sıfırlanırsa ya da yeni oturum açılırsa önce bu dosya okunur.
> Her adım bitince kutucuk `[x]` yapılır, yanına kısa not ve commit kodu yazılır. Karar değişirse "Kararlar" bölümü güncellenir.
> Yazıldığı tarih: 2026-11-21. İlgili skill: `ses-defteri` (`~/.claude/skills/ses-defteri/SKILL.md`).

## Neden
v1.2.0 yayında. Kullanıcı (Selim) ve Umut Akbaş şunları istiyor:
- Programın kendini güncellemesi: kayıtlar ve ayarlar silinmeden.
- Toplantıyı programın içinden kaydetmek, istenirse canlı yazıya dökmek.
- Kayıtlara soru sorulabilen yerel bir AI asistan: "geçen hafta Ahmet uygulama için ne demişti?"
- Şirket logosuyla Word toplantı tutanağı.
- Kurulum dosyalarında "Selim Oğuz" imzası.

Her şey çevrimdışı çalışır. Tek istisna kapatılabilir güncelleme kontrolüdür.

## Kararlar (kullanıcının cevapları, 2026-11-21)
| Konu | Karar |
|---|---|
| Sürümler | **Ana** sürüme hepsi. **Basit** sürüme sadece Kaydet, Word tutanak (AI'sız) ve güncelleme. Basitte AI sohbet ve canlı yazı yok. |
| Kayıt | Bilgisayar sesi + mikrofon birlikte kaydedilir. **Canlı yazı bir seçenek**, varsayılan kapalı, her an durdurulabilir (bilgisayar kasarsa, slayt açarken vb.). |
| AI sohbet modeli | Toplantı modundaki mevcut model kullanılır (qwen3.5-4b vb.), ek indirme yok. Kayıtlar için yerel **SQLite** (kullanıcı "mysql" dedi, SQLite aynı işi kurulumsuz görür). |
| AI tanıma | Kişiler sayfasındaki herkesi tanır. Her kişiye isteğe bağlı **unvan** ve **açıklama** yazılabilir. Sabit künye: **Selim Oğuz** (geliştirici), **Umut Akbaş** (fikir babası). |
| AI kuralları | Sadece kayıtlardan ve uygulama hakkındaki bilgilerden cevap verir. Bulamazsa "bulamadım" der, uydurmaz. Konu dışı isteklere girmez. Bugünün tarihini bilir. Büyük model yok. |
| Tutanak | **İkisi de:** program içinde ayarlar (logo, şirket adı, renk, bölümler) ve isteyen kendi **Word şablonunu** yer tutucularla yükler. Yeni **Ayarlar** sayfasında. |
| Güncelleme | Her açılışta `https://selimoguz.com.tr/ses-defteri/surum.json` kontrol edilir. Kurulu sürüm (Normal / NVIDIA / Basit) tanınır, aynısı GitHub'dan indirilip kurulur. `%APPDATA%` verisi korunur. Kullanıcı site dosyalarını hosting paneli/FTP ile kendisi yükler. Ayrı Ryzen sürümü yok. |
| İmza | **Ücretsiz, kendi oluşturduğumuz** "Selim Oğuz" sertifikası. Para verilmeyecek. Mavi SmartScreen uyarısı kalır, kullanıcıya söylendi. |

## Kod haritası (keşiften, Ana Sürüm)
- **Ayarlar:**
  - `backend/asr.py:22-50` `get_settings`/`set_setting` → `%APPDATA%\SesDefteri\settings.json`.
  - JS'ye açılış `backend/bridge.py:223-251`: her yeni anahtar için `get_settings`'e bir satır, `set_settings`'e bir `if` dalı gerekir.
  - JS tarafı `call("set_settings", {...})` (`frontend/app.js:14-17`).
- **Sayfa kalıbı:**
  - `frontend/system.js` ve `people.js`: IIFE, `open()` diğer görünümleri gizler, `homeBtn` ile kapanır.
  - Header düğmeleri `index.html:23-30`, `<main id=... hidden>` satırı `index.html:100-101`, scriptler `218-224`.
  - i18n için `Object.assign(I18N.tr, {...})`.
  - **Bilinen hata:** sayfalar birbirini gizlemiyor (Kişiler açıkken Sistem açılırsa ikisi de görünür). Ayarlar eklenirken bu düzeltilecek.
- **Word:**
  - `backend/export.py`: `render()` docx dalı satır 261-299, `render_analysis()` 223-258, `_analysis_blocks()` 99-180.
  - `Api.save_word` `bridge.py:280`.
  - Analiz alanları: `summary, chapters, topics, decisions[].text, tasks[].owner/task/due, open_questions, stats.speakers, people[], score`.
- **Ağ:** sadece `urllib.request` (`engines/whispercpp.py:140`, `semantic.py:80`, `llm/catalog.py:140` Range ile devam eder).
- **Sürüm ve baskı:**
  - Sürüm 3 yerde elle yazılı: `installer/SesDefteri.iss:13`, `installer/version_info.txt`, release notları. Uygulama içinde sürüm yok.
  - NVIDIA baskısı yalnızca `_MEIPASS/nvidia` DLL'lerinin varlığıyla ayrılıyor (`engines/ct2.py:17-28`).
- **Inno:**
  - AppId `{6C1F7A52-3B1E-4E7B-9A55-5E5DEF7E1A01}`, `PrivilegesRequired=lowest`.
  - `[Run]` girdisi `skipifsilent` olduğu için sessiz kurulumdan sonra program açılmıyor.
  - `AppMutex` yok.
- **Mikrofon:**
  - `backend/people.py:524` `Recorder` (sounddevice, 16 kHz mono, belleğe, 60 sn'de durur) yalnızca ses örneği için.
  - **Bilgisayar sesi (loopback) yakalama hiç yok.**
- **İş kuyruğu:**
  - `Api.start_job(path)` (`bridge.py:119`) → `store.create_job` → `pipeline.enqueue` → `run_job(..., keep_source=True)`. Geçici dosya için `keep_source=False`.
  - Tek ağır iş kilidi: `pipeline._queue_lock`.
- **ASR:**
  - `asr.load_model()` modeli açık tutar. `asr.transcribe(samples, dur, progress)` 16 kHz float32 tampon alır, `Word(start,end,text,prob)` döner. Canlı yazı için uygundur.
  - `chunking.speech_regions` duraklamada keser.
  - whisper.cpp her çağrıda süreç açar, canlıda ct2 tercih edilir.
  - `auto` dilde `detect_languages` önbelleği var.
- **LLM:**
  - `backend/llm/__init__.py` `generate(prompt, schema=None, system=None, max_tokens, temperature, cancel, timeout)`. Her çağrı yeni bir `llama-completion.exe` süreci açar (model her seferinde yüklenir), `--json-schema` destekler.
  - `llm.available()` ile kontrol edilir.
  - `analysis.py` LLM'den önce `asr.release()` çağırır.
- **Arama:**
  - `backend/semantic.py`: e5-base ONNX, `jobs/<id>/embeddings.npy+json`.
  - `search(q, limit, per_job)` → `job_id, filename, seg, start, speaker, text, score`.
  - Tarih filtresi yok. `transcript.json["created"]` epoch zamanı.
- **Kişiler:**
  - `people/<id>/person.json`: `id, name, created, samples, embedding...`, dışarıya açılan alanlar `_public()` `people.py:169`.
  - Konuşmacı: `segments[i].speaker` int, `speakers{"0": "Ad"}`.
- **Basit Sürüm** ayrı yerel repo: `..\Basit Sürüm`. Derlerken `..\Ana Sürüm\.venv` kullanır. Kendi AppId'si `{6268B6E2-114E-4972-B995-1EFBC7815E3E}`.

---

## Aşama 0: Hazırlık
- [x] Bu plan dosyası ve `ses-defteri` skill'i oluşturuldu, hafızaya işaret eklendi.
- [x] Önceki oturumdan kalan yardımcılar repoya kopyalandı: `tools/dev/cdp.mjs` (WebView2'yi CDP ile sürmek: `eval`, `shot`) ve `tools/dev/upload.sh` (büyük dosyaları curl ile GitHub release'e yükler, sürüm etiketi argümanla verilir).
- [x] (gerek kalmadı: v1.3.0 çıktı, NVIDIA kurulumu orada) v1.2.0'ın eksik `SesDefteri-NVIDIA.zip` dosyası yüklendi (`tools/dev/upload.sh v1.2.0 dist/SesDefteri-NVIDIA.zip`). 2026-11-21: önceki oturumdan kalan bir curl yüklemesi hâlâ çalışıyordu; önce `gh release view v1.2.0` ile kontrol et, yoksa yeniden yükle.

## Aşama 1: Sürüm bilgisi, imza, güncelleme sistemi (Ana + Basit)
Bu aşama önce gelir: v1.3.0'ı kuran herkes sonraki sürümleri kendiliğinden alır.

**Durum (2026-11-21, Ana Sürüm):**
- [x] (commit 23acfb4) 1a sürüm ve baskı: `backend/version.py`, `tools/set_version.py`, `edition.txt` derlemede yazılır, Hakkında'da "Sürüm 1.3.0 · Standart" görünür.
- [x] 1b imza: sertifika oluşturuldu (parmak izi `8032931C62F4F826CF46A2566FCCBBE05130D6F3`, `version.py`'de). `tools/sign.ps1` derlemede exe ve setup'ları imzalar. Gerçek dosyada denendi: bizim imza geçer, 1 bayt değişen dosya `HashMismatch` ile reddedilir, başkasının imzası reddedilir.
- [x] **Kullanıcı yapacak:** `.\tools\backup_cert.ps1` ile sertifika yedeği (parolayı kendisi girer). Sertifika kaybolursa kurulu programlar sonraki güncellemeleri reddeder.
- [x] 1c güncelleyici: `backend/updater.py`, köprü metodları, `frontend/updater.js` şeridi, `tests/test_updater.py` (29 test). Uygulamada sahte sunucuyla (`SESDEFTERI_UPDATE_URL`) denendi: şerit çıktı → indirdi → doğruladı → "hazır". "Kur ve yeniden başlat" gerçek kurulumla Aşama 6'da denenecek.
- [x] Inno: `AppMutex=SesDefteriMutex` (`app.py` oluşturur), sessiz kurulumdan sonra açılış (`Check: WizardSilent`), sürüm `/DAppVersion` ile.
- [x] Site: `site/ses-defteri/index.html` + `logo.svg`, `tools/make_release_json.py` → `surum.json`.
- [x] Ayarlar'da "otomatik denetle" anahtarı ve "Şimdi denetle" düğmesi → Aşama 2'de (arka uç hazır: ayar `update_check`, `window.updater.check(true)`).
- [x] Basit Sürüm'e aktarma → Aşama 5.

**1a. Sürüm ve baskı tek yerden**
- `backend/version.py`: `VERSION = "1.3.0"`.
- Baskı bilgisi `edition()` ile okunur: `_MEIPASS/edition.txt` dosyasından (`standart` / `nvidia` / `basit`). Geliştirme ortamında `dev` döner.
- `build_windows.ps1` her baskıya `edition.txt` yazar.
  - `version_info.txt` ve `.iss` içindeki `AppVersion` derlemede `version.py`'den üretilir (`/DAppVersion=...`). Böylece sürüm tek yerde yazılır.
- Hakkında penceresinde sürüm ve baskı gösterilir: "1.3.0 · NVIDIA".

**1b. Ücretsiz imza ("Selim Oğuz")**
- `tools/make_cert.ps1` sertifikayı bir kez oluşturur:
  - `New-SelfSignedCertificate -Type CodeSigningCert -Subject "CN=Selim Oğuz" -CertStoreLocation Cert:\CurrentUser\My`, 10 yıllık.
  - Yedek `.pfx` repo DIŞINA kaydedilir (`%USERPROFILE%\Documents\SesDefteri-imza.pfx`). Şifreyi kullanıcı belirler, Claude görmez.
- `tools/sign.ps1` imzalar: `Set-AuthenticodeSignature -Certificate ... -TimestampServer http://timestamp.digicert.com -HashAlgorithm SHA256`.
- `build_windows.ps1` sırası: PyInstaller → `SesDefteri.exe` imzalanır → Inno paketler → `*-Setup.exe` imzalanır.
- Sertifikanın parmak izi (thumbprint) `backend/version.py` içine `SIGNER_THUMBPRINT` olarak yazılır. Güncelleyici bunu kullanır (1c).
- **Not:** Windows bu sertifikaya güvenmez, SmartScreen uyarısı kalır. Kazancı: dosya özelliklerinde "Selim Oğuz" yazar, ayrıca güncelleyici indirdiği dosyanın gerçekten bizden geldiğini doğrulayabilir.

**1c. Güncelleyici** (`backend/updater.py` + `bridge.py` metodları `check_update`, `download_update`, `install_update`, `update_status`)
- **Ne zaman bakar:** açılıştan 5 sn sonra arka planda `GET https://selimoguz.com.tr/ses-defteri/surum.json`.
  - Zaman aşımı 5 sn, `urllib`, `User-Agent: SesDefteri/<sürüm>`.
  - İnternet yoksa ya da hata olursa sessizce geçer.
  - Ayar `update_check` (varsayılan açık). Ayarlar'da "Şimdi denetle" düğmesi.
- **`surum.json` biçimi:**
  ```json
  {"version":"1.3.0","date":"2026-12-01","notes_tr":"...","notes_en":"...",
   "files":{"standart":{"url":"https://github.com/selo159951/ses-defteri/releases/download/v1.3.0/SesDefteri-Setup.exe","size":0,"sha256":"..."},
            "nvidia":{...},"basit":{...}}}
  ```
- Sürümler sayı olarak karşılaştırılır (`1.10.0 > 1.9.0`). Yeni sürüm varsa üstte şerit çıkar: "Yeni sürüm 1.3.0 · Neler yeni · Güncelle · Sonra". "Sonra" o sürümü 1 gün susturur.
- **İndirme:**
  - Kendi baskısının dosyasını `%TEMP%\SesDefteri-update\` klasörüne indirir. İlerleme yüzdesi gösterilir, kopan indirme `.part` ve Range ile devam eder (`llm/catalog.py` kalıbı).
  - Doğrulama: boyut + **sha256** + **Authenticode imzası** (`Get-AuthenticodeSignature`, parmak izi `SIGNER_THUMBPRINT` olmalı). Biri tutmazsa kurulmaz, dosya silinir.
- **Kurulum:**
  - Çalışan bir iş varsa önce sorulur ("İşlenen kayıt duraklatılsın mı?"). Kuyruk durumu zaten diske yazılıyor ve devam ettirilebiliyor.
  - Sonra `Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS` çalıştırılır ve program kapanır.
- **Inno değişiklikleri (iki .iss):**
  - Program açıkken kurulum yapılmasın diye `AppMutex=SesDefteriMutex` (Basit için `SesDefteriBasitMutex`); `app.py` açılışta bu mutex'i oluşturur.
  - `[Run]` bölümüne sessiz kurulum sonrası programı açan ikinci bir satır: `Flags: nowait; Check: WizardSilent`.
- **Veri güvenliği:** kurulum sadece `{app}` klasörüne yazar. `%APPDATA%\SesDefteri` (kayıtlar, kişiler, ayarlar, modeller) hiç dokunulmaz.
  - `[InstallDelete]` yalnızca `{app}\_internal`'ı siler (doğru davranış).
  - Bunu test et: 1.2.0 kur → kayıt ekle → 1.3.0'a güncelle → kayıtlar ve ayarlar duruyor mu?
- **Site dosyaları:** `site/ses-defteri/` (repoda) içinde `index.html` (indirme sayfası: üç kurulum dosyası, sürüm notları, Türkçe) ve `surum.json`.
  - `tools/make_release_json.py` dosyaları `dist` ve Basit çıktısından okuyup boyut ve sha256'yı doldurur.
  - Kullanıcı bu klasörü hosting paneliyle `selimoguz.com.tr/ses-defteri/` altına yükler.
- **Testler** (`tests/test_updater.py`):
  - sürüm karşılaştırma
  - bozuk ya da eksik json
  - sha256 uyuşmazlığı → kurulmaz
  - baskı eşleme
  - internet yok → sessiz

## Aşama 2: Ayarlar sayfası + toplantı tutanağı
**Durum (2026-11-21, Ana Sürüm):**
- [x] Ayarlar sayfası (`frontend/settings.js`): Şirket (ad, renk, logo), Tutanak bölümleri (aç/kapa + sıra), Kendi Word şablonu (yükle / örnek indir / kaldır), Güncellemeler (otomatik denetle + Şimdi denetle + sürüm). "Kayıt" bölümü Aşama 3'te eklenecek.
- [x] Sayfa hatası giderildi: ortak `showPage()` + `pageopen` olayı (`app.js`); `openJob` de sayfaları gizler.
- [x] `backend/minutes.py`: yerleşik tutanak + şablon doldurma (bölünmüş run, liste paragrafı, görev tablo satırı, üst/alt bilgi, `{logo}`, Türkçe/ASCII adlar). Örnek şablon dosya olarak tutulmuyor, `minutes.sample_template()` ile anında üretiliyor ("Örnek şablonu indir").
- [x] Köprü: `get/set_minutes_settings`, `pick_logo`, `remove_logo`, `pick_template`, `remove_template`, `save_sample_template`, `save_minutes`. Kayıt sayfasında "Tutanak" düğmesi.
- [x] `tests/test_minutes.py` (22 test), toplam 416 test geçti. Uygulamada sahte kayıtla denendi (ekran görüntüleriyle).
- [ ] Analiz sekmesine de "Tutanak" düğmesi (isteğe bağlı, kayıt sayfasındaki düğme yeterli olabilir).
- [x] Basit Sürüm'e aktarma → Aşama 5.

**2a. Ayarlar sayfası** (`frontend/settings.js`, header'a `settingsBtn`)
- Mevcut "Seçenekler" dişlisiyle karışmasın diye ikon `sliders`. Lucide yolu `icons.js`'e eklenir.
- **Bölümler:**
  1. **Şirket:**
     - ad
     - logo yükle, önizlemeli → `%APPDATA%\SesDefteri\branding\logo.png` (en fazla 1 MB, png/jpg)
     - renk
  2. **Tutanak:**
     - Hangi bölümlerin çıkacağı ve sırası: katılımcılar, özet, bölümler, kararlar, görevler, açık sorular, tam metin eki. Yukarı/aşağı okları ile sıralanır.
     - Şablon kısmı: "Word şablonu yükle" / "Örnek şablonu indir" / "Şablonu kaldır".
  3. **Kayıt:**
     - canlı yazı varsayılanı
     - mikrofon seçimi
     - bilgisayar sesi açık/kapalı
  4. **Güncelleme:**
     - otomatik denetle (aç/kapa)
     - şimdi denetle
     - kurulu sürüm ve baskı
- Sayfalar arası gizleme hatası düzeltilir: ortak `showPage(id)` yardımcısı `app.js`'e eklenir, system/people/settings hepsi bunu kullanır.
- Yeni ayar anahtarları: `company_name, company_color, minutes_sections, update_check, update_snooze, live_default, rec_mic, rec_system`.
- Hepsi `bridge.get_settings/set_settings`'e eklenir. Logo ve şablon için ayrı metodlar: `pick_logo`, `pick_template`, `remove_template`, `save_sample_template`.

**2b. Tutanak üretimi** (`backend/minutes.py`, `Api.save_minutes(job_id, lang)`)
- **Yerleşik tutanak** (şablon yoksa), python-docx ile:
  - üst bilgide logo + şirket adı
  - başlık: kayıt adı
  - tarih, süre, katılımcılar (konuşmacılar ve konuşma payları)
  - ayarlardaki sırayla özet / bölümler / kararlar / görevler **tablosu** (Kim, Ne, Ne zaman) / açık sorular
  - istenirse tam metin eki
  - Başlık rengi şirket rengi olur. Analiz verisi `_analysis_blocks` ile aynı alanlardan okunur.
- **Analiz yoksa** (ya da Basit sürümde): katılımcılar, tarih, süre ve tam metin. Ana sürümde "Önce Analiz yapılsın mı?" diye sorulur.
- **Kullanıcı şablonu** (`%APPDATA%\SesDefteri\templates\tutanak.docx`):
  - Tekil yer tutucular: `{tarih} {saat} {süre} {kayıt} {şirket} {özet} {katılımcılar}`. ASCII karşılıkları da kabul edilir: `{ozet} {sure} {kayit} {sirket} {katilimcilar}`.
  - Liste yer tutucuları: Paragrafta tek başına `{kararlar}`, `{açık_sorular}`, `{bölümler}` varsa paragraf her madde için çoğaltılır, aynı stil korunur.
  - Tablo satırında `{görev.kim}` / `{görev.ne}` / `{görev.tarih}` varsa satır her görev için çoğaltılır.
  - `{logo}` yerine resim konur.
  - Gövde, tablolar, üst ve alt bilgi taranır.
  - Word yer tutucuyu farklı "run"lara bölebildiği için önce paragraftaki run'lar birleştirilir (biçim ilk run'dan alınır).
- `tools/make_sample_template.py`, `assets/tutanak-ornek.docx` dosyasını üretir: tüm yer tutucular ve açıklamaları içinde.
- **Düğmeler:** kayıt sayfasında "Word olarak kaydet"in yanına **"Tutanak"**. Analiz sekmesinde de olur.
- **Testler** (`tests/test_minutes.py`):
  - yerleşik tutanak (analizli ve analizsiz)
  - şablon doldurma: bölünmüş run, tablo çoğaltma, üst bilgi, ASCII yer tutucu
  - bozuk şablon → anlaşılır hata

## Aşama 3: Toplantı kaydı (Ana + Basit) ve canlı yazı (sadece Ana)
**Durum (2026-11-21, Ana Sürüm):**
- [x] 3.0 Deneme: `soundcard` (BSD) WASAPI loopback bu PC'de çalışıyor; sessizlikte de takılmadan sıfır veriyor. `requirements.txt` ve spec'e eklendi (`collect_all("soundcard")`, `cffi`). **Paketlenmiş exe'de çalıştığı Aşama 6 derlemesinde doğrulanacak.**
- [x] `backend/meeting_recorder.py`: iki iz 48→16 kHz (sinc alçak geçiren), her 0,1 sn diske `.pcm`, duraklat, cihaz kopsa diğeri sürer, durdurunca karıştır (sessiz mikrofon yükseltilir) → `Toplantı <tarih saat>.wav` → normal iş. İş `audio.mp3`'ü oluşturunca ham klasör silinir. Çökme sonrası `leftovers()` / `recover()` / `discard()`.
- [x] `LiveWriter`: ~12 sn'lik parçalar, en sessiz anda kesilir, düşük öncelikli iş parçacığı, 2 kez üst üste ses süresinden yavaşsa kendini durdurur ("slow"), hata olursa "error". Dosya işlenirken açılmaz ("busy").
- [x] Köprü: `rec_devices, start_meeting, rec_status, set_live, pause_meeting, stop_meeting, cancel_meeting, rec_leftovers, recover_recording, discard_recording`; ayarlar `rec_system, rec_mic, rec_mic_id, live_default, rec_notice_done`. `Api.LIVE_TEXT` (Basit'te False olacak).
- [x] Arayüz: `frontend/recorder.js` — ana sayfada "Toplantıyı kaydet", her sayfada görünen kırmızı şerit (süre, iki seviye çubuğu, Canlı yazı anahtarı, Duraklat, Durdur ve metne çevir, Sil), canlı metin paneli, ilk kayıtta KVKK uyarısı, yarım kalan kayıt şeridi. Ayarlar'da "Toplantı kaydı" kartı.
- [x] `tests/test_meeting_recorder.py` (14 test), toplam 430 test geçti.
- [x] Gerçek denemede: hoparlörden çalınan örnek konuşmayla 93 sn kayıt, canlı yazı 8 satır doğru yazdı, durdurunca iş "Tamamlandı" oldu, ham dosyalar silindi.
- [ ] Gerçek bir Teams/Meet görüşmesinde iki kişili deneme (kullanıcı yapabilir).
- [x] Basit Sürüm'e aktarma (canlı yazısız) → Aşama 5.
**3.0. Deneme (önce bu):** bilgisayar sesi yakalama.
- Aday: **`soundcard`** kütüphanesi (MIT, WASAPI loopback): `sc.get_microphone(sc.default_speaker().name, include_loopback=True)`.
- Bu PC'de YouTube videosu çalarken 10 sn kayıt yapılıp dinlenir. PyInstaller paketine girdiği doğrulanır (`collect_all("soundcard")`).
- Olmazsa yedek: `PyAudioWPatch`.

**3a. Kaydedici** (`backend/meeting_recorder.py`, people.py'deki `Recorder`'dan ayrı)
- **Yakalama:** iki iş parçacığı.
  - Hoparlör loopback'i (genelde 48 kHz stereo) ve mikrofon.
  - Her biri mono 16 kHz'e çevrilip kendi dosyasına yazılır: `%APPDATA%\SesDefteri\recordings\<tarih-saat>\system.wav` ve `mic.wav`.
  - 30 sn'de bir `flush` ile diske yazılır. Program çökse bile kayıt kalır.
  - Açılışta yarım kalmış kayıt varsa "Kurtarılsın mı?" diye sorulur.
- **Durdurunca:**
  - İki iz süre farkına göre hizalanıp karıştırılır (saat kayması için iz uzunluklarına göre yeniden örnekleme), seviye normalize edilir → `kayit.wav`.
  - `Api.start_job(path)` ile sıraya girer. Dosya adı `Toplantı 2026-11-21 14.30` olur.
  - Ham izler, iş bitince silinir.
- **Arayüz:**
  - Ana sayfada bırakma alanının yanında büyük **Kaydet** düğmesi.
  - Kayıt şeridi gösterir: süre, iki seviye çubuğu (Mikrofon / Bilgisayar), **Duraklat**, **Durdur ve işle**, **İptal**.
  - Program küçültülse de kayıt sürer. Görev çubuğu simgesinde kırmızı nokta olur (pywebview izin verirse; yoksa başlık "● Kaydediliyor").
- **KVKK notu:** ilk kayıtta tek seferlik uyarı: "Kayda başlamadan önce katılımcılara haber verin."
- **Basit sürümde de aynı Kaydet düğmesi olur.** Canlı yazı yoktur.

**3b. Canlı yazı (Ana, seçenek)**
- Kayıt şeridinde **"Canlı yazı"** anahtarı var, varsayılan Ayarlar'dan gelir (`live_default`, başta kapalı). Kayıt sırasında istenen an açılıp kapatılabilir.
- **Çalışma şekli:**
  - Ayrı bir iş parçacığı her ~10–15 sn'de birikmiş karışık sesi `chunking.speech_regions` ile bir duraklamadan keser.
  - `asr.transcribe` ile yazıya döker. Model `asr.load_model` ile açık tutulur.
  - Sonuç zaman damgalı satırlar olarak kayıt şeridinin altındaki panele eklenir.
  - Konuşmacı ayrımı canlıda yapılmaz, son işlemde yapılır.
- **Bilgisayarı yormamak için:**
  - İş parçacığı düşük öncelikte çalışır (`SetThreadPriority` BELOW_NORMAL).
  - CPU'da ct2 `cpu_threads` en fazla 2 olur.
  - **Gerideyse kendiliğinden durur:** yazıya dökme ses süresinden uzun sürerse (2 kez üst üste) canlı yazı durur. Toast: "Bilgisayar zorlanıyor, canlı yazı durduruldu. Kayıt devam ediyor, metin toplantı bitince hazırlanır."
  - O sırada bir dosya işleniyorsa (`pipeline` kuyruğu dolu) canlı yazı açılmaz, nedeni yazılır.
- Canlı metin önizlemedir. Durdurunca normal tam işlem (konuşmacılar, isimler, analiz) yapılır.
- **Testler:**
  - kaydedici sahte ses kaynağıyla (yakalama katmanı enjekte edilebilir)
  - karıştırma ve hizalama
  - çökme sonrası kurtarma
  - canlı işçinin gerideyken durması (sahte `transcribe` yavaşlatılarak)

## Aşama 4: AI sohbet (sadece Ana)
**Durum (2026-11-22, Ana Sürüm):**
- [x] Kişilere `title` / `note` (`people.set_person_info`), Kişiler kartında iki alan.
- [x] `backend/chatdb.py`: `sohbet.db` (SQLite FTS5, Türkçe harfler katlanmış, basit Türkçe ek kesme `stem()`), satırlar + analiz maddeleri (özet/karar/görev/açık soru), `sync()` mtime ile, yalnız `done` işler.
- [x] `backend/chat.py`: tarihler kodla (`resolve_dates`: bugün/bugünkü/dün/geçen hafta/bu ay/N gün önce/son N gün/12 kasım/tam tarih/"geçen salı", "salı günü"; tek başına "cuma" tarih sayılmaz). Soru türü (karar/görev/soru/özet/genel) ve dolgu kelimeleri de kodla; model yalnız niyet (kayıt/uygulama/konu dışı), kişiler, anahtar kelimeler ve cevap için. Uydurma kelimeler bir şey bulmazsa kişi/tarih filtresiyle o kişinin satırlarına düşer. Kaynak numaraları kodla doğrulanır, `**` ve sondaki "Kaynak:" temizlenir. Konu dışı → sabit ret. "Kim yaptı" → sabit künye (Selim Oğuz, Umut Akbaş).
- [x] Köprü `chat_info`, `chat_ask`, `chat_cancel` (dosya işlenirken "busy", model yoksa "no_model", LLM'den önce `asr.release()`).
- [x] Arayüz `frontend/chat.js`: üstte **Asistan** düğmesi, örnek sorular, balonlar, kaynak çipleri (tıklayınca kayıt o satırda açılır), Durdur, Yeni sohbet.
- [x] `tests/test_chat.py` (55 test), toplam 484 test geçti.
- [x] Gerçek modelle (Qwen 3.5 4B, NVIDIA) denendi: "Dün Mehmet ne demişti?", "Dünkü toplantıda hangi kararlar alındı?", "Bu uygulamayı kim yaptı?", şiir isteği (ret). Soru başına ~12 sn.
- [ ] Gerçek, uzun kayıtlarla (birçok toplantı) cevap kalitesi kullanıcı tarafından denenmeli.
**4a. Kişi bilgisi**
- `person.json`'a isteğe bağlı `title` (unvan) ve `note` (açıklama) alanları eklenir.
- `_public()`'e eklenir. `people.js` kişi kartında "Unvan / Açıklama" düzenleme alanı olur.

**4b. Yerel veritabanı** (`backend/chatdb.py`, `%APPDATA%\SesDefteri\sohbet.db`, SQLite + FTS5)
- **Tablolar:**
  - `jobs(id, filename, created, duration)`
  - `lines(job_id, seg, start, end, speaker, text)` + FTS5 sanal tablosu `lines_fts(text)`, `tokenize='unicode61 remove_diacritics 2'`
  - `people(id, name, title, note)`
- **Güncellik:** açılışta ve her iş bittiğinde ya da metin düzenlendiğinde güncellenir. `transcript.json` mtime karşılaştırılır.
- Kaynak her zaman JSON dosyalarıdır, veritabanı silinirse yeniden kurulur.

**4c. Soru akışı** (`backend/chat.py`, `Api.chat_ask(question, history)`, `chat_cancel`)
1. **Tarih çözümü (kodla, güvenilir):**
   - "bugün, dün, bu hafta, geçen hafta (önceki Pzt–Paz), bu ay, geçen ay, N gün/hafta önce, Pazartesi..." gibi Türkçe ve İngilizce ifadeler Python'da tarih aralığına çevrilir. Bugünün tarihi `datetime.now()`.
   - Model bu aralığı değiştirmez. Sadece kodun yakalayamadığı durumda modelin önerisi kullanılır.
2. **Soru çözümleme (LLM, `--json-schema`):** `{"niyet":"kayit|uygulama|kapsam_disi","kisiler":[],"anahtar":[],"konu":""}`.
   - Sistem metninde şunlar var: bugünün tarihi ve günü, kişiler listesi (ad, unvan, açıklama), sabit künye.
   - Kişi adları veritabanındaki konuşmacı adlarıyla eşlenir (büyük/küçük harf ve Türkçe karakter duyarsız).
3. **Arama (kodla):**
   - tarih aralığı + kişi filtresi
   - FTS5 (`kelime*` önek eşlemesi, Türkçe ekler için)
   - arama modeli varsa `semantic.search` sonuçları da tarih ve kişiye göre süzülüp eklenir
   - en iyi ~25 satır, her biri ±1 satır bağlamla
4. **Cevap (LLM, `--json-schema`):** `{"cevap":"...","kaynaklar":[1,4],"bulundu":true}`.
   - Model yalnızca numaralı satırları görür. Cevap Türkçe ya da sorunun dilinde olur.
5. **Kurallar** (sistem metni + kod kontrolü):
   - Yalnızca verilen satırlardan ve uygulama bilgisinden cevap verilir.
   - Satır yoksa model çağrılmadan "Bu tarihlerde/bu kişiyle ilgili bir kayıt bulamadım" denir.
   - `kapsam_disi` niyetinde kibarca reddedilir: "Ben sadece toplantı kayıtlarınız hakkında yardımcı olabilirim."
   - Sistem metni gösterilmez.
   - Cevaptaki kaynak numaraları gerçekten verilen satırlar mı, kodla doğrulanır.
6. **Sohbet geçmişi:** son 3 soru-cevap, "peki ya Umut?" gibi devam sorularına bağlam olur.
- **Hız:** her LLM çağrısı yeni süreç açar, yani soru başına 2 çağrı yapılır. Bekleme sırasında "Düşünüyor..." ve İptal gösterilir.
- **Çakışma:** dosya işlenirken soru sorulursa "Kayıt işleniyor, bitince cevaplanacak" der ve sıraya alır. Bunun için `analysis` kuyruk kalıbı kullanılır. Model yoksa "Sistem sayfasından modeli indirin" bağlantısı gösterilir.

**4d. Arayüz** (`frontend/chat.js`, header'a **Asistan** düğmesi, ikon `message-circle`)
- sohbet balonları
- altta soru kutusu
- her cevabın altında kaynak çipleri: "Haftalık toplantı · 12 Kas · 14:32 · Ahmet". Tıklanınca kayıt açılır ve o saniyeye gider (`openJob` + seek).
- "Yeni sohbet" düğmesi
- örnek sorular: "Geçen hafta hangi kararlar alındı?", "Ahmet'e verilen görevler neler?"
- Geçmiş sadece oturum boyunca tutulur (diskte değil).

**Testler** (`tests/test_chat.py`, LLM sahte `generate` ile):
- tarih ifadeleri: geçen hafta sınırları ve yıl dönümü
- FTS ve kişi filtresi
- kayıt bulunamadığında model çağrılmaz
- konu dışı soru reddedilir
- uydurma kaynak numarası atılır

## Aşama 5: Basit Sürüm'e aktarma (`..\Basit Sürüm`)
**Durum (2026-11-22):** [x] Basit commit d1bba14. Aktarma betiği: version/updater/minutes/meeting_recorder + updater.js/recorder.js/settings.js aynen kopyalandı; köprüde `LIVE_TEXT=False`, `SIMPLE=True` (tutanak = katılımcılar + tam metin, şablonsuz); `window.SIMPLE_EDITION` ile Ayarlar sade (kayıt, şirket, güncelleme). AppMutex `SesDefteriBasitMutex`, sessiz kurulum sonrası açılış, imza, `edition.txt=basit`. Derleme betiğindeki eski `System32<TAB>ar.exe` hatası düzeltildi. Basit 380 test, Ana 484 test geçti. Ayarlar sayfası kaynak koddan açılıp kontrol edildi.
**NOT:** Basit'i kaynak koddan test ederken `SESDEFTERI_MODEL_DIR` boş klasöre işaret ederse 2,2 GB model indirmeye başlıyor; testte uygulamayı hemen kapat ya da modelli klasör ver.
- [x] `version.py` (`edition=basit`), updater, AppMutex, `[Run]` sessiz sonrası açılış, imza
- [x] Sade Ayarlar: şirket adı, logo, güncelleme aç/kapa (tutanak bölümleri ve şablon yüklemesi de olabilir, basit tutulur)
- [x] Kaydet düğmesi (canlı yazı yok)
- [x] Tutanak (AI'sız: katılımcılar, tarih, süre, tam metin; şablon yüklenmişse şablon)
- [x] Testler (`tests/test_simple.py` + yeni testler)
- Basit'te stash'teki "unfinished 5-hour recording work" çalışmasına DOKUNULMAZ.

## Aşama 6: Yayın
- [x] Tüm testler: Ana ve Basit.
- [x] Gerçek uygulamada CDP ile ekran görüntüsü kontrolü: Ayarlar, Tutanak, Kaydet, Asistan, güncelleme şeridi.
- [x] Güncelleme uçtan uca denenir: yerel bir test sunucusunda (`python -m http.server`) `surum.json` → 1.3.0-test kurulumu → güncelleme → kayıtlar ve ayarlar korunmuş mu? Test için güncelleme adresi `SESDEFTERI_UPDATE_URL` ortam değişkeniyle değiştirilebilir.
- [x] Sürüm 1.3.0: `version.py`, release notları `.claude/release-notes-1.3.0.md` (Türkçe, gerçek kayıt adı yok).
- [x] Derle ve imzala:
  - `build_windows.ps1 -Gpu` (Ana) → `Projeler\Ses Defteri\Ana Sürüm`
  - Basit `build_windows.ps1` → `Projeler\Ses Defteri\Basit Sürüm`
- [x] GitHub: README güncellenir (yeni özellikler, güncelleme, imza notu), push, release v1.3.0 + 5 dosya (`tools/dev/upload.sh`).
  - Basit setup da release'e eklenir: `SesDefteri-Basit-Setup.exe`. Güncelleyici onu GitHub'dan indirecek.
  - Basit'in kaynak kodu GitHub'a gitmez, sadece setup dosyası.
- [x] `site/ses-defteri/` için `make_release_json.py` çalıştırılır. Kullanıcıya "şu klasörü siteye yükle" denir ve yüklendikten sonra adres kontrol edilir.
- [x] Bu PC'ye NVIDIA 1.3.0 kurulur (yalnızca NVIDIA kurulu kalır). Hafıza notu güncellenir.

## Doğrulama özeti
- `.\.venv\Scripts\python -m pytest tests` (Ana) ve Basit testleri yeşil.
- Uygulama test verisiyle açılır: `SESDEFTERI_HOME` geçici klasör, `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9333`, `node tools/dev/cdp.mjs shot x.png`.
- Kayıt: gerçek video sesi + mikrofonla 1 dk kayıt → iş tamamlanır, iki taraf da metinde.
- Canlı yazı: açık/kapalı geçişi; CPU'yu yapay yüklerken kendiliğinden durması.
- Sohbet: test kayıtlarıyla "geçen hafta X ne dedi" → doğru kaynak; uydurma yok; konu dışı ret.
- Güncelleme: yerel sunucuyla tam tur, veri korunuyor.
- **Test edilemeyen:** AMD/Ryzen bilgisayar elde yok.

## Risk ve notlar
- Küçük model (4B) bazen yanlış anlar. Bu yüzden tarih ve arama kodla yapılır, model yalnızca anlama ve cevap yazmada kullanılır. Her cevapta kaynak olur.
- Her LLM çağrısı modeli yeniden yükler, sohbet yavaş olabilir. Gerekirse sonraki sürümde `llama-server` ile model açık tutulur, ama "yerel sunucu yok" ilkesi nedeniyle şimdilik yapılmıyor.
- Güncelleme kontrolü programın tek internet çağrısı olur. README'de açıkça yazılır ve Ayarlar'dan kapatılabilir.
- Self-signed imza SmartScreen uyarısını kaldırmaz. Kullanıcıya söylendi.

---
## DEVAM NOTU (2026-11-22, oturum sıkıştırılmadan önce)
Kullanıcının isteği: "kalan aşamaları sırayla tamamla, sonra kapsamlı test yap, uyurken uyandırma, iş bitince PC'yi kapat". Token tasarrufu iste: kısa çalış.
- Aşama 0–5 BİTTİ (Ana son commit 300f565, Basit d1bba14). Ana 484, Basit 380 test geçiyor.
- Aşama 6 sürüyor:
  1. [~] Ana derleme arka planda başladı: `build_windows.ps1 -Gpu`, günlük: scratchpad `build_main.log` (session 38abbbec). Bitince dist'te 4 dosya: SesDefteri-Setup.exe, SesDefteri.zip, SesDefteri-NVIDIA-Setup.exe, SesDefteri-NVIDIA.zip. İmzalı olmalı (`Get-AuthenticodeSignature`, parmak izi 8032931C…).
  2. [ ] Paket kontrolü: dist\SesDefteri\SesDefteri.exe'de `soundcard` var mı (`_internal\soundcard`), uygulama açılıyor mu.
  3. [ ] Basit derle: `..\Basit Sürüm\build_windows.ps1` → Projeler\Ses Defteri\Basit Sürüm.
  4. [ ] README (Ana) güncelle: kayıt + canlı yazı, Asistan, Ayarlar/tutanak, güncelleme (tek internet kullanımı, kapatılabilir), imza notu. Sürüm notları `.claude/release-notes-1.3.0.md` (Türkçe, gerçek kayıt adı yok).
  5. [ ] Bu PC'ye NVIDIA 1.3.0 sessiz kur (`/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /TASKS=desktopicon`), açılıyor mu, 26 kayıt duruyor mu, Hakkında "1.3.0 · NVIDIA".
  6. [ ] Güncelleme turu testi: yerel `python -m http.server` + `SESDEFTERI_UPDATE_URL` ile kurulu uygulamada gerçek setup'la "Kur ve yeniden başlat" (veri korunuyor mu).
  7. [ ] GitHub: commit+push, `gh release create v1.3.0 --draft`, dosyalar `bash tools/dev/upload.sh v1.3.0 <dosyalar>` (Basit setup da), boyutları kontrol, `--draft=false --latest`.
  8. [ ] `tools/make_release_json.py` → site/ses-defteri/surum.json; kullanıcıya "site/ses-defteri klasörünü selimoguz.com.tr/ses-defteri/'ye yükle" notu (OKU.txt'ye de yaz).
  9. [ ] Hafıza (ses-defteri-status.md) güncelle, sonra `shutdown /s /t 60` ile PC'yi kapat (kullanıcı istedi). Yüklemeler bitmeden kapatma.

### 02:50 ilerleme
- [x] Paket kontrolü: soundcard paketli exe'de çalışıyor; edition.txt Set-Content ile yazılmıyordu → .NET (3ee0a5e, Basit e4d308b)
- [x] Basit derlendi, imzalı; README + .claude/release-notes-1.3.0.md
- [x] NVIDIA 1.3.0 bu PC'ye sessiz kuruldu: 26 kayıt, 'Sürüm 1.3.0 · NVIDIA'
- [x] Güncelleme döngüsü: DETACHED_PROCESS yüzünden kurulum başlamıyordu → düzeltildi (f2e5e9f, Basit f3c674c); elle doğrulandı (70 sn'de yeniden açıldı)
- [x] Yeniden derleme (byp0p0mfr) → uygulama içi döngüyü tekrar test et → surum.json yeniden üret → GitHub

### 05:40 bitti
- [x] Yeniden derleme + uygulama içi güncelleme döngüsü baştan sona doğrulandı (65 sn, 26 kayıt korundu)
- [x] GitHub v1.3.0 yayınlandı (latest): SesDefteri-Setup.exe, SesDefteri.zip, SesDefteri-Basit-Setup.exe (ece5906)
- [x] SesDefteri-NVIDIA-Setup.exe yüklenemedi: bu ağda büyük yüklemeler TLS hatasıyla kesiliyor (curl SEC_E_MESSAGE_ALTERED, gh bad record MAC). Başka ağdan: `bash tools/dev/upload.sh v1.3.0 dist/SesDefteri-NVIDIA-Setup.exe`, sonra make_release_json.py --nvidia ile surum.json yeniden üret
- [x] KULLANICI: site/ses-defteri (surum.json, index.html, logo.svg) → selimoguz.com.tr/ses-defteri/ (site/OKU.txt)


### Açık kalanlar (2026-11-22)
- [ ] Gerçek Teams/Meet görüşmesinde iki kişili kayıt denemesi (kullanıcı)
- [ ] Asistan cevap kalitesi gerçek, çok toplantılı kayıtlarla (kullanıcı)
- [ ] Rehber düğmesi kaldırıldı (39299b1): bir sonraki sürümle (1.3.1) dağıtılacak
- [ ] İsteğe bağlı: Analiz sekmesine Tutanak düğmesi; site yazı tiplerini kendi sunucuda barındırmak
