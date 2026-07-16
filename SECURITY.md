# Güvenlik

## Desteklenen sürümler

| Sürüm | Durum |
|---|---|
| 0.2.x | Destekleniyor |
| 0.1.1 ve öncesi | Güvenlik güncellemesi gerekli |

## v0.1.1 güvenlik uyarısı

v0.1.1, bundle kimliği biçimindeki bazı klasörleri yalnızca kurulu uygulama
listesinde bulunmadıkları için yüksek güvenli kalıntı olarak gösterebilir.
Özellikle `Group Containers`, `Application Scripts`, arka plan yardımcıları ve
paylaşılan uygulama verileri yanlış pozitif olabilir.

v0.1.1 kullanıyorsanız:

- “Tümünü seç” özelliğini kullanmayın.
- Group Containers ve Application Scripts sonuçlarını taşımayın.
- Her yolu Finder'da kontrol edin.
- Mümkün olan en kısa sürede 0.2.x sürümüne geçin.

maClean kalıcı silme yapmaz; öğeleri Çöp Kutusu'na taşır. Yanlış taşınan bir
öğeyi Çöp boşaltılmadan önce geri yükleyebilirsiniz.

## Güvenlik açığı bildirme

Aktif kullanıcı verisinin yanlış aday gösterilmesi, izin verilen dizin dışına
çıkılması veya paket bütünlüğü sorunları için GitHub deposunda güvenlik bildirimi
açın. Bildirime kişisel dosya yolları veya özel dosya içerikleri eklemeyin.
