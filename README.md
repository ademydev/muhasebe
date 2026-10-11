# Hesap · Kişisel Muhasebe

İlk sürüm internet bağlantısı ve üçüncü taraf paket gerektirmeyen kişisel bir web uygulamasıdır. Python ile yerel çalıştırıldığında veriler uygulama klasöründeki `data.json` dosyasına yazılır. GitHub Pages üzerinde çalıştırıldığında aynı iş kuralları tarayıcının bu siteye ait yerel saklama alanını kullanır; Pages statik barındırma Python API’si çalıştırmadığı için veriler cihaz/tarayıcı bazında kalır.

## Çalıştırma

Python 3.9 veya üstü yeterlidir:

```bash
python3 app.py
```

Tarayıcıda `http://127.0.0.1:8765` adresini açın. Bu uygulama eski siteden ayrı olarak 8765 portunu kullanır. Sunucuyu durdurmak için terminalde `Ctrl+C` kullanın. Farklı bir port seçmek için `PORT=8787 python3 app.py` komutunu çalıştırabilirsiniz. Veri dosyasını farklı konumda tutmak için `FINANCE_DATA_FILE=/path/to/data.json` ayarlanabilir.

Uygulama localhost üzerinden sunulduğunda çevrimdışı arayüz için service worker kurulur. İlk sayfa yüklemesi için yerel sunucu çalışıyor olmalıdır; kayıtlar Python sunucusunun yerel JSON dosyasında saklanır.

## GitHub Pages

Depo `main` dalının kök klasörü Pages kaynağı olarak seçildiğinde `https://ademydev.github.io/muhasebe/` adresinde açılabilir. CSS, JavaScript, manifest ve service worker bağlantıları depo alt yolu ile çalışacak göreli adresler kullanır. Pages sürümü finansal kayıtları yalnızca o tarayıcının yerel saklama alanında tutar; GitHub’a finansal kayıt göndermez.

Yerel Python sürümündeki kayıtlar ile Pages sürümünün tarayıcı kayıtları otomatik eşitlenmez. Taşımak isterseniz yerel uygulamadan JSON yedeği indirip Pages sürümünde **Hesap ayarları → Yedek geri yükle** yoluyla içe aktarın. Yedek dosyasını depoya eklemeyin.

## Finansal kurallar

- Tutarlar tam sayı kuruş olarak saklanır.
- Gerçekleşmiş bakiye = açılış bakiyesi + gelirler − giderler.
- Kalan borç = borç toplamı − borç ödemeleri.
- Kullanılabilir bakiye = gerçekleşmiş bakiye − kalan borç.
- Açılış bakiyesi gelir değildir. Borç kaydı gerçekleşmiş gider değildir. Borç ödemesi, borç geçmişi ve gider hareketi olarak tek atomik işlemde eklenir.
- Alacak tahsilatı, tahsilat kaydı ve gelir hareketi olarak tek atomik işlemde eklenir.
- Kayıtlar hesap kimliğiyle kapsamlanır; hesaplar arası transfer ilk sürümde yoktur.

## Testler

Yalnızca Python standart kütüphanesiyle:

```bash
python3 -m unittest discover -s tests -v
```

## Veri yedeği

Arayüzden **Yedekle** ile tüm ilişkileri ve kimlikleri taşıyan JSON dosyası indirilir. Geri yükleme mevcut verilerle kimlikleri koruyarak birleştirir; bozuk bağlantılar doğrulamadan geçmez. Tarayıcı depolaması ya da yerel dosya tek başına yedek yerine geçmez; JSON yedeğini ayrıca güvenli bir konumda saklayın.
