# Ses Defteri 1.4.0 planı

Kaynak: kullanıcının 22.11.2026 gece istekleri. 1.3.1 ayrıca YAYINLANMAZ: önce özellikler kodlanır, sonra test, sonra doğrudan 1.4.0 yayını.
Kullanıcının seçimi: A'nın hepsi; B'den 1, 3, 5, 6, 7, 9 (yedek alma + geri yükleme), 10, 11 (isteğe bağlı ayar). B 2, 4, 8, 12 YOK. Kod EVREN'e (deepseek-v4.1-flash; glm-5.3 boşsa) yazdırılır, Claude kontrol eder.

## A. Kullanıcının istedikleri
1. [x] **Asistan iş yapabilsin (eylemler).** Model yalnızca cevap vermesin, uygulamada işlem de yapsın; her işlemden önce kullanıcıya düğmeyle onay sorulsun.
   - "Ece'yi kişilere ekle":
     - Bütün kayıtlarda adı Ece olan konuşmacıları bul. Adın geçtiği satırlara değil, Ece'nin kendi konuştuğu satırlara bak.
     - Seslerini karşılaştır, gruplara ayır: "3 kayıtta Ece var. 2'si aynı ses, 1'i farklı görünüyor."
     - Her grubu dinlenebilir örnekle göster, sonra sor: "Hepsi aynı Ece mi? Hangi Ece'ye ekleyeyim / yeni kişi mi?"
     - Kayıt kayıt tek tek sormasın, gruplayarak sorsun.
   - Diğer eylemler:
     - "Konuşmacı 2 Ahmet"
     - "son toplantının tutanağını çıkar"
     - "X kaydını aç"
     - "geçen haftaki toplantıların kararlarını listele"
     - "Ahmet'in görevlerini Word'e aktar"
   - Yöntem:
     - Niyet şemasına `eylem` alanı eklenir.
     - Her eylem bir bridge fonksiyonuna bağlanır.
     - Cevap balonunun içinde onay düğmeleri gösterilir.
2. [x] **Kişileri otomatik öğren daha akıllı olsun.**
   - Bugün yalnızca "benim adım Ece" gibi kendini tanıtmalardan öğreniyor. Hitapla bulunan ("Günaydın Ece") ya da elle verilen adlardan öğrenmiyor; bu yüzden Ece öğrenilmedi.
   - Bir konuşmacıya ad verilince (elle, hitaptan ya da yapay zekâ önerisinden) şu öneri gösterilsin: "Ece Kişiler'e eklensin mi? Sesi sonraki kayıtlarda tanınır." Düğmeler: Ekle / Var olan Ece'ye ekle / Hayır.
3. [x] **Adsız konuşmacılar için bilgi kutusu.**
   - Kayıtta "Konuşmacı 1/2" kaldıysa üstte bir kutu çıksın: "Konuşmacılara ad verin".
   - Her konuşmacı için ad kutusu ve sesinden kısa bir örneği dinleme düğmesi olsun.
   - Ad yazılınca bütün satırlar güncellensin ve 2. maddedeki öneri gösterilsin.
4. [x] **Dışa aktarma:**
   - Konuşmacı seçimi kontrol edilsin: hiç kimse seçilmemişse herkesin satırları aktarılsın, seçilenler varsa yalnızca onlarınki.
   - Bu durum düğmenin yanında açıkça yazsın ("Herkes" / "2 kişi").

## B. Önerilen yeni özellikler (kullanıcı seçecek)
1. Teams/Meet/Zoom görüşmesi başlayınca "Kaydedeyim mi?" bildirimi.
2. Kayıt sırasında "önemli an" işareti (kısayol tuşu); metinde işaretli görünür, tutanağa girer.
3. Konuşma süreleri: kim ne kadar konuştu (çubuk grafik), kayıt sayfasında ve tutanakta.
4. Görevleri Outlook takvimine/görevlerine aktarma (.ics) ve hazır e-posta özeti taslağı.
5. Tutanağı PDF olarak da kaydetme.
6. Oynatıcı: hız (0.75–2x), sessizlikleri atla, 5 sn geri/ileri.
7. Kayıtlara etiket/klasör, yıldız, toplu silme/dışa aktarma.
8. Metni çevirme (TR↔EN, internetsiz model).
9. Tüm verileri yedekle / geri yükle (tek zip).
10. Disk koruması: kayıttan önce boş yer uyarısı; N gün sonra ham sesi silme seçeneği.
11. Sistem tepsisi simgesi + Windows ile başlat + tepsiden kayıt başlat/durdur.
12. Kayıtları parolayla koruma / şifreleme (KVKK).

## C. Genel kalite turu
- 1.3.1 planının 8. adımı yapılmadı: bütün sayfaları %100/125/150/175 yakınlaştırmada, 1024×700 ve 800×600 pencerede, açık/koyu temada, Türkçe/İngilizce dilde ekran görüntüsüyle kontrol et.
- `kvkk-audit` becerisiyle KVKK ön kontrolü.
- `web-design-guidelines` ile erişilebilirlik incelemesi: odak halkaları, klavyeyle kullanım, kontrast.
- Basit sürüm aynı turdan geçsin.

## Durum (23.11.2026 gece)
- A 1-4, B 1/3/5/6/7/9/10/11 kodlandı (EVREN glm-5.3 + deepseek, Claude kontrol), 593 test.
- Toplantı algılama: yeni Windows'ta kayıt defteri LastUsedTimeStop yok; Windows ses oturumlarından (pycaw) okunuyor.
- Kayıt listesinde etiket/ad/sil ⋯ menüsünde. Asistan kartı takılma, 'İyi' adı, PDF '0 dk' düzeltildi.
- Basit 1.4.0: yalnızca düzeltmeler (yeni özellikler Basit'e eklenmedi, sade kalsın).
