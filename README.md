# maClean

maClean, macOS uygulamalarını ilişkili dosyalarıyla birlikte güvenli biçimde
kaldıran ve daha önce silinmiş uygulamalardan kalmış olabilecek dosyaları
incelemenize yardım eden ücretsiz, açık kaynak bir araçtır.

Hiçbir dosyayı kalıcı olarak silmez. Uygulama paketleri ve seçtiğiniz ilişkili
öğeler macOS Çöp Kutusu'na taşınır.

## Neler yapar?

### Uygulama Kaldır

Kurulu uygulamaları aranabilir bir listede gösterir. Bir uygulama seçildiğinde
ana bundle kimliği, yardımcı `.app`, `.appex` ve `.xpc` kimlikleri ile
okunabilen application-group yetkileri kullanılarak ilişkili dosyalar
doğrulanır.

İki kaldırma modu vardır:

- **Standart kaldır:** Uygulama paketi, doğrulanmış cache, log, saved state,
  WebKit ve HTTP storage verileri.
- **Tamamen kaldır:** Standart kapsama ek olarak doğrulanmış Preferences,
  Application Support ve uygulamaya özel Containers verileri.

Paylaşılan veya sahipliği kanıtlanamayan dosyalar otomatik seçilmez. Uygulama
paketi Çöp'e taşınamazsa ilişkili verilere dokunulmaz.

Uzun sonuç listeleri native bir tablo kullanır. Satır ayrıntıları tablonun
altındaki panelde gösterilir; seçim sütununa tıklayabilir veya klavyeden
**Space** ile seçim yapabilirsiniz. Sütun başlıkları sonuçları sıralar.

### Eski Kalıntıları Tara

`~/Library` altındaki eski adayları güvenlik-öncelikli kurallarla tarar.
Yalnızca kimliği doğrulanabilen kalıntılar seçilebilir; yalnız isim
benzerliğiyle bulunanlar sahiplik doğrulanamadığı için seçilemez, inceleme
amacıyla listelenir. Son 30 günde değişmiş, okunamayan veya paylaşılan öğeler
de korunur. Tarama kurulu uygulama envanterini `/Applications` ve
`~/Applications` ile sınırlar; Homebrew/DMG gibi başka yolla kurulmuş
uygulamaların verisi bu nedenle aday görünebilir.

`Group Containers` ve `Application Scripts`, güvenli biçimde tek bir silinmiş
uygulamaya bağlanamadıkları için eski heuristik taramada önerilmez.

Sonuçlar burada da aynı native tabloda listelenir; tıklayarak veya **Space**
ile seçim ve sütun başlığıyla sıralama (aktif sütunda yön oku ile) aynı biçimde
çalışır. Görünen seçilebilir adayları tek adımda işaretlemek için **Tümünü
İşaretle**, işaretleri kaldırmak için **Temizle** düğmelerini kullanabilirsiniz.
Tam Disk Erişimi verilmemişse tarama öncesi bir uyarı bandı çıkar.

### Klavye kısayolları

Menü çubuğundan da erişilebilen kısayollar:

- **⌘O** — `.app` dosyası seç
- **⌘R** — kurulu uygulamaları yenile
- **⌘⇧R** — kalıntı taramasını başlat
- **⌘1 / ⌘2** — sekmeler arası geçiş
- **⌘F** — aktif sekmenin arama kutusuna odaklan
- **⌘A** — kalıntı sekmesinde görünen seçilebilir adayları işaretle

## Güvenlik yaklaşımı

- Kalıcı silme yoktur.
- Sistem uygulamaları ve maClean'in kendisi kaldırılamaz.
- Sembolik link uygulamalar reddedilir.
- Taşıma öncesi yol, inode ve değiştirilme bilgileri yeniden doğrulanır.
- Çalışan uygulamalar kapatılmadan kaldırma başlamaz.
- Paylaşılan application-group verisi yalnız tek uygulamaya ait olduğu
  kanıtlanırsa tam kaldırmaya dahil edilir.
- Erişilemeyen konumlar sessizce başarılı sayılmaz; arayüzde eksik tarama
  uyarısı gösterilir.

0.1.1 ve daha eski sürümler için [güvenlik uyarısını](SECURITY.md) okuyun.

## Yerel envanter ve gizlilik

maClean, daha önce gördüğü ve kendi üzerinden kaldırdığı uygulamaları
hatırlayabilmek için aşağıdaki yerel dosyayı kullanır:

```text
~/Library/Application Support/maClean/state-v1.json
```

Bu dosyada yalnız uygulama adı, bundle kimliği, uygulama yolu, yardımcı
kimlikler, okunabilen application-group değerleri ve görülme zamanları tutulur.
Dosya içerikleri kaydedilmez ve herhangi bir sunucuya gönderilmez.

## Hazır uygulama

[Releases](../../releases) sayfasından Mac mimarinize uygun ZIP dosyasını ve
yanındaki `.sha256` checksum dosyasını indirin.

Ücretsiz proje Apple Developer sertifikasıyla imzalanıp notarize edilmediği
için ilk açılışta Gatekeeper uyarısı çıkabilir:

1. `maClean.app` dosyasına sağ tıklayın ve **Aç** seçeneğini kullanın.
2. Gerekirse **Sistem Ayarları → Gizlilik ve Güvenlik → Yine de Aç** yolunu
   izleyin.

Bu uyarı kaynak kodunun veya ZIP bütünlüğünün doğrulanmadığı anlamına gelmez.
Release hattı paketi ad-hoc imzalar, açılan ZIP üzerinde kod imzasını doğrular
ve SHA-256 checksum üretir.

## Kaynaktan çalıştırma

Python 3.10 veya üzeri gereklidir.

```bash
git clone https://github.com/sayweer/maClean.git
cd maClean
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

## Geliştirme

```bash
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q
python scripts/benchmark_ui.py --rows 200
```

Doğrulanmış yerel release oluşturmak için:

```bash
bash scripts/build_release.sh
```

Betik PyInstaller paketini üretir, ad-hoc imzalar, AppleDouble girdisi
içermeyen ZIP oluşturur, sembolik linkleri ve açılan paketin kod imzasını
doğrular, smoke test çalıştırır ve SHA-256 checksum yazar.

## Bilinen sınırlamalar

- Ücretsiz dağıtım nedeniyle notarization yoktur.
- Başka uygulamalar tarafından paylaşılan container'lar otomatik temizlenmez.
- İzin gerektiren konumlar için Tam Disk Erişimi gerekebilir; verilmemişse
  kalıntı sekmesinde proaktif bir uyarı gösterilir.
- Kurulu uygulama envanteri `/Applications` ve `~/Applications` ile sınırlıdır.
  Homebrew, `/opt` veya DMG'den çalışan uygulamalar bu listede görünmez.
- Ad benzerliği tek başına sahiplik kanıtı değildir; bu adaylar seçilemez,
  yalnızca inceleme için listelenir.
- Yönetici yetkisi yükseltilmez; `/Applications` altındaki bazı paketler macOS
  izinleri nedeniyle taşınamayabilir.

## Katkı

Hata raporlarında özel dosya içeriği veya kişisel tam yollar paylaşmayın.
Güvenlik sorunları için [SECURITY.md](SECURITY.md) yönergelerini izleyin.

## Lisans

[MIT](LICENSE)
