"""Fictional meetings (Turkish) for the semantic-search tests and the model measurement.
No real recordings or people: Deniz, Burak and Elif do not exist.

QUERIES: (query, meeting index, segment index that must be found among the top results)."""

SPEAKERS = {"0": "Deniz", "1": "Burak", "2": "Elif"}

MEETINGS = [
    ("Fiyat toplantısı", [
        (0, "Günaydın arkadaşlar, bugün gündemimizde abonelik paketlerimiz var."),
        (1, "Geçen çeyrekte maliyetler çok arttı, sunucu faturaları neredeyse iki katına çıktı."),
        (2, "Bence önümüzdeki aydan itibaren aylık ücretleri yüzde on beş yükseltmemiz gerekiyor."),
        (0, "Müşteriler zam haberini nasıl karşılar, bundan biraz çekiniyorum."),
        (1, "Eski müşterilere üç ay boyunca eski fiyattan devam edelim, yeniler yeni fiyatı ödesin."),
        (2, "Rakip firmalar zaten geçen yıl fiyatlarını artırdı, biz geride kaldık."),
        (0, "Tamam, ücret değişikliğini ilk hafta duyuralım, e-posta ile bilgilendirme yapalım."),
        (1, "Yıllık pakette indirim oranını yüzde yirmide tutarız."),
    ]),
    ("Mobil uygulama planı", [
        (1, "Mobil uygulamanın yeni sürümünde giriş ekranında bir hata çıkıyor, bazı telefonlarda kilitleniyor."),
        (0, "Hatayı cuma gününe kadar düzeltebilir miyiz, yoksa yayını erteleyelim mi?"),
        (2, "Test ekibi iki gün daha istiyor, özellikle eski Android sürümlerinde denemeleri bitmedi."),
        (1, "Yayın tarihini on beş Mart olarak belirleyelim, mağaza onayı için üç gün pay bırakırız."),
        (0, "Karanlık mod isteği çok geliyor, bir sonraki sürüme alabiliriz."),
        (2, "Bildirim ayarlarını da sadeleştirmemiz lazım, kullanıcılar kafası karışık diyor."),
        (1, "Ben önümüzdeki hafta tasarım ekibiyle oturup ekranları gözden geçiririm."),
    ]),
    ("Müşteri şikayetleri", [
        (2, "Bu ay en çok şikayet teslimat gecikmesinden geldi, kargo firması sözünü tutmadı."),
        (0, "Siparişlerin bir kısmı on günü aştı, müşteriler iade talep ediyor."),
        (1, "Kargo firmasını değiştirmeyi düşünüyoruz, iki alternatiften teklif aldım."),
        (2, "İade süreçlerini hızlandırmak için para iadesini üç iş günü içinde yapalım."),
        (0, "Müşteri hizmetleri ekibine ek kişi lazım, telefonlar cevapsız kalıyor."),
        (1, "Özür mesajı olarak indirim kuponu göndermek iyi bir fikir olabilir."),
    ]),
    ("Bütçe ve işe alım", [
        (0, "Gelecek yıl için yazılım ekibine iki yeni geliştirici almak istiyoruz."),
        (1, "Maaş bütçemiz sınırlı, ancak bir kişilik kadro açabiliriz."),
        (2, "Pazarlama harcamalarını yüzde on kısarsak işe alım için kaynak çıkar."),
        (0, "Mülakatları nisan ayında yapalım, adaylar için bir teknik ödev hazırlayalım."),
        (1, "Uzaktan çalışma politikasını da netleştirmeliyiz, haftada iki gün ofis olabilir."),
        (2, "Ofis kirası artıyor, daha küçük bir yer bakmak mantıklı olabilir."),
    ]),
]

QUERIES = [
    ("fiyat artışı ne zaman konuşulmuştu", 0, 2),
    ("fiyatları yükseltmek", 0, 2),
    ("müşteriler fiyat artışına tepki verir mi", 0, 3),
    ("uygulamadaki çökme sorunu", 1, 0),
    ("ne zaman yayınlayacağız", 1, 3),
    ("gece teması", 1, 4),
    ("paket ne zaman geç geldi", 2, 0),
    ("geri ödeme ne kadar sürede", 2, 3),
    ("yeni eleman alımı", 3, 0),
    ("evden çalışma kuralları", 3, 4),
    ("ofis masrafları", 3, 5),
    ("giderleri azaltmak", 3, 2),
]
