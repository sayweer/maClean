# maClean

macOS'ta sildiğiniz uygulamaların geride bıraktığı **öksüz önbellek, ayar ve
log dosyalarını** bulup güvenle Çöp Kutusu'na taşıyan, basit ve ücretsiz bir
açık kaynak araç.

Bir uygulamayı Çöp'e attığınızda, ona ait veriler çoğu zaman
`~/Library/Caches`, `~/Library/Application Support`, `~/Library/Preferences`
gibi klasörlerde kalır. Zamanla bu "öksüz" dosyalar birikip disk alanınızı
doldurur. maClean bunları bulur — ama **hiçbir şeyi kalıcı silmez**, yalnızca
Çöp Kutusu'na taşır; yani her işlem geri alınabilir.

> CleanMyMac gibi ücretli araçlara alternatif olarak, tek bir işe odaklanan
> küçük ve şeffaf bir araç.

---

## Özellikler

- Silinmiş uygulamaların `~/Library` altındaki kalıntılarını tespit eder
  (Caches, Application Support, Preferences, Logs, Containers, Saved State,
  Group Containers, WebKit, HTTPStorages, Application Scripts).
- **İki katmanlı sonuç:** kimliğiyle kesin eşleşen kalıntılar ("Uygulama
  kalıntıları") ile isim benzerliğine dayanan tahminler ("Dikkatli inceleyin")
  ayrı gösterilir.
- Her öğe için boyut ve konum; en büyükten küçüğe sıralı.
- Silme yerine **Çöp Kutusu'na taşıma** — geri alınabilir.
- Apple sistem bileşenlerine ve hâlâ yüklü uygulamalara **asla dokunmaz**.

---

## Güvenlik

maClean güvenliği önceleyecek şekilde tasarlandı:

- **Kalıcı silme yok.** Her şey Çöp Kutusu'na taşınır; yanlışlıkla bir şey
  seçtiyseniz Çöp'ten kurtarabilirsiniz.
- **Varsayılan olarak hiçbir şey seçili gelmez.** Ne taşınacağına siz karar
  verirsiniz.
- **Apple bileşenleri korunur.** `com.apple.*` ile başlayan hiçbir şey ve
  `/System` alanı asla değerlendirilmez.
- **Yüklü uygulamalar korunur.** Hâlâ `/Applications` içinde olan bir
  uygulamanın verisi (yardımcı süreçleri ve güncelleyicileri dâhil) öksüz
  sayılmaz.
- Yalnızca kullanıcı seviyesi `~/Library` taranır; yönetici (sudo) izni
  gerektiren sistem konumlarına dokunulmaz.

---

## Kurulum

### Seçenek A — Hazır uygulamayı indir (en kolay)

1. [Releases](../../releases) sayfasından en son `maClean.app.zip` dosyasını
   indirin ve çıkarın.
2. `maClean.app`'i `Uygulamalar` klasörüne taşıyın.
3. **İlk açılışta Gatekeeper uyarısı** göreceksiniz. Bunun nedeni uygulamanın
   ücretli bir Apple Developer sertifikasıyla imzalanmamış olmasıdır (açık
   kaynak, ücretsiz bir proje). Uygulama güvenlidir; kaynağı bu depodadır.
   Açmak için:
   - **maClean.app**'e sağ tıklayın → **Aç** → çıkan pencerede tekrar **Aç**.
   - Veya: **Sistem Ayarları → Gizlilik ve Güvenlik** → aşağıda "maClean
     engellendi" uyarısının yanındaki **Yine de Aç**'a tıklayın.
   - Bunu yalnızca bir kez yapmanız yeterlidir; sonraki açılışlar normaldir.

### Seçenek B — Kaynaktan çalıştır

Python 3.10+ gerektirir (geliştirme Python 3.14 ile yapıldı).

```bash
git clone <bu-depo-url>
cd maClean
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

---

## Kullanım

1. **Taramayı Başlat**'a tıklayın. maClean yüklü uygulamalarınızı ve
   `~/Library` kalıntılarını tarar (genellikle birkaç saniye).
2. Sonuçları inceleyin. "Uygulama kalıntıları" bölümü yüksek güvenlidir;
   "Dikkatli inceleyin" bölümü ise isim tahminine dayanır — burada hâlâ
   kullandığınız araçların (ör. paket yöneticisi önbellekleri) çıkabileceğini
   unutmayın.
3. Silmek istediğiniz öğelerin kutularını işaretleyin (bölüm başlığındaki
   **Tümünü seç** / **Temizle** ile toplu seçim yapabilirsiniz).
4. **Seçilenleri Çöp'e Taşı**'ya tıklayın ve onaylayın.
5. Fikrinizi değiştirirseniz dosyaları Çöp Kutusu'ndan geri alabilirsiniz.

---

## Sorun Giderme

**Bazı klasörler taranamıyor / eksik görünüyor.**
macOS gizlilik koruması (TCC) nedeniyle bazı konumlara erişim kısıtlı olabilir.
Daha kapsamlı tarama için **Sistem Ayarları → Gizlilik ve Güvenlik → Tam Disk
Erişimi** altından maClean'e (veya kaynaktan çalıştırıyorsanız Terminal'e) izin
verebilirsiniz. Erişilemeyen öğeler zaten sessizce atlanır, uygulama çökmez.

---

## Bilinen Sınırlamalar

- İsim bazlı ("Dikkatli inceleyin") eşleştirme %100 kesin değildir; bu yüzden
  ayrı bir bölümde gösterilir ve varsayılan olarak seçili gelmez.
- Bir uygulamanın yardımcı bileşeninin kendi kimliğiyle bıraktığı nadir
  kalıntılar tespit edilemeyebilir.
- Çok büyük önbellek klasörlerinde boyut hesaplama birkaç saniye sürebilir.

---

## Yol Haritası (v1 sonrası)

- Tarayıcı önbelleği, eski loglar ve geliştirici araçları için ayrı temizlik
  kategorileri
- Yinelenen (duplicate) dosya bulucu
- GitHub Actions ile otomatik build ve release
- (Opsiyonel) kod imzalama ve notarization

---

## Katkı

Geliştirme bağımlılıkları için `requirements-dev.txt` kullanın ve testleri
çalıştırın:

```bash
pip install -r requirements-dev.txt
pytest
```

Uygulamayı `.app` olarak paketlemek için:

```bash
pyinstaller maclean.spec --noconfirm
# çıktı: dist/maClean.app
```

---

## Lisans

[MIT](LICENSE) — dilediğiniz gibi kullanın, değiştirin, paylaşın.
