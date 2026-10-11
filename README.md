# Hesap · Kişisel Muhasebe

Uygulamanın yerel Python sürümü kayıtları proje klasöründeki `data.json` dosyasına yazar. GitHub Pages sürümü statik HTML/CSS/JavaScript olarak çalışır ve kurulum tamamlandığında Supabase Auth ile kullanıcıya özel bulut kaydı kullanır. Yerel sürüm Supabase'e bağlanmaz.

## Çalıştırma

Python 3.9 veya üstü yeterlidir:

```bash
python3 app.py
```

Tarayıcıda `http://127.0.0.1:8765` adresini açın. Bu uygulama eski siteden ayrı olarak 8765 portunu kullanır. Sunucuyu durdurmak için terminalde `Ctrl+C` kullanın. Farklı bir port seçmek için `PORT=8787 python3 app.py` komutunu çalıştırabilirsiniz. Veri dosyasını farklı konumda tutmak için `FINANCE_DATA_FILE=/path/to/data.json` ayarlanabilir.

Uygulama localhost üzerinden sunulduğunda çevrimdışı arayüz için service worker kurulur. İlk sayfa yüklemesi için yerel sunucu çalışıyor olmalıdır; kayıtlar Python sunucusunun yerel JSON dosyasında saklanır.

## GitHub Pages

Depo `main` dalının kök klasörü Pages kaynağı olarak seçildiğinde `https://ademydev.github.io/muhasebe/` adresinde açılabilir. CSS, JavaScript, manifest ve service worker bağlantıları depo alt yolu ile çalışacak göreli adresler kullanır. Supabase kurulumu tamamlandıktan sonra Pages finansal kayıtları oturum açmış kullanıcının RLS korumalı bulut satırında saklar. GitHub'a finansal kayıt gönderilmez.

Yerel Python sürümündeki kayıtlar ile Supabase bulut kaydı otomatik eşitlenmez. Taşımak isterseniz yerel uygulamadan JSON yedeği indirip Pages sürümünde giriş yaptıktan sonra **Hesap ayarları → Yedek geri yükle** yoluyla içe aktarın. Yedek dosyasını depoya eklemeyin.

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

## Supabase kimlik doğrulama ve GitHub Pages bulut kaydı

GitHub Pages sürümü e-posta/parola ile Supabase Auth kullanır. Oturum yokken muhasebe ekranları ve veriler yüklenmez. Bu statik projede `NEXT_PUBLIC_*` ortam değişkenleri derleme olmadan sunulamadığı için tarayıcıya açık `supabase-config.js` yapılandırma dosyası kullanılır. Dosyada yalnızca proje URL'si ve publishable key bulunmalıdır; `service_role` veya `sb_secret_*` anahtarlarını buraya koymayın. Publishable key gizli değildir; veritabanı erişimini RLS sağlar.

### Supabase kurulumu

1. Supabase Dashboard → SQL Editor bölümünde önce `public.hesap_user_states` tablosu var mı kontrol edin. Varsa sütunlarını, RLS durumunu ve mevcut politikaları inceleyin; mevcut nesneyi silmeyin.
2. Yeni tablo yoksa `supabase-schema.sql` dosyasını SQL Editor'e yapıştırıp çalıştırın. Bu betik kullanıcı başına bir JSONB program durumu tablosu ve `auth.uid() = user_id` tabanlı select/insert/update politikaları kurar; delete politikası vermez. Mevcut tabloyla çakışma varsa betiği çalıştırmadan önce şemayı inceleyin.
3. Authentication → URL Configuration içinde **Site URL** değerini `https://ademydev.github.io/muhasebe/` yapın. **Redirect URLs** listesine `https://ademydev.github.io/muhasebe/` ekleyin. Başka bir domain veya yerel geliştirme adresi kullanıyorsanız onu da açıkça ekleyin.
4. Authentication → Providers → Email bölümünde e-posta sağlayıcısını açık tutun ve doğrulama e-postasını etkinleştirin. SMTP/şablon ve parola sıfırlama e-postasını Supabase Auth ayarlarından yapılandırın.
5. `supabase-config.js` içindeki URL ve publishable key'i Supabase Project Settings → API ekranındaki değerlerle eşleştirin. Bu statik Pages yayını için bu dosyanın tarayıcıya sunulması gerekir; dosyaya gizli anahtar eklemeyin.
6. `supabase-schema.sql`, `supabase-config.js` ve uygulama dosyalarını GitHub Pages'in kullandığı `main` dalına gönderin; Pages derleme/deploy işlemi tamamlandıktan sonra doğrulanmış e-posta ile kayıt ve giriş yapın.

### Bulut veri ve aktarım davranışı

Her doğrulanmış kullanıcı için `hesap_user_states` tablosunda tek satır bulunur; `state` JSONB alanında o kullanıcının tüm bağımsız çalışma alanları ve finansal kayıtları tutulur. Satırın `user_id` değeri istemciden alınan serbest bir kimlik değil, Auth oturumundaki kullanıcıdır. RLS her satırı yalnız sahibi için sınırlar. `revision` karşılaştırmalı güncelleme eşzamanlı yazmaları saptar; çakışan kayıt reddedilir ve kullanıcıdan sayfayı yenilemesi istenir. Realtime açık diğer oturumlara değişiklik bildirimi gönderir.

İlk bulut kaydı boş oluşturulur. Mevcut tarayıcıdaki `hesap-pages-data-v1` verisi okunmaz, silinmez veya otomatik yüklenmez. Önceki yerel/Pages uygulamasından aktarım gerekiyorsa giriş yapmadan önce JSON yedeği indirin; yeni sürümde giriş yaptıktan sonra **Hesap ayarları → Yedek geri yükle** ile kullanıcı onayı vererek yükleyin. Yerel Python sunucusu `data.json` dosyasını kullanmaya devam eder ve Supabase ile eşitlenmez. Kimlik doğrulama/bulut senaryoları gerçek Supabase projesinde e-posta ve iki ayrı kullanıcıyla ayrıca doğrulanmalıdır.
