**NEXOAUDIO · Qt Studio AI (v4.3)**

Amaç: Tek dosyalık, FFmpeg tabanlı masaüstü uygulamasıyla videolardaki sesi; gürültü azaltma, de-esser, EQ (presence), kompresör, seviye sabitleme ve LUFS kalibrasyonu adımlarından geçirip doğal, canlı ve stüdyo kalitesine yaklaştırmak. Adobe Podcast’e benzer “Podcast Enhance (Beta)” modu dahildir. Orijinal/Filtreli önizleme, yüzde barı, iptal ve hızlı dışa aktarma vardır.

**Başlıca Özellikler**

- AI Studio ve Podcast Enhance (Beta) zincirleri
- 
- Orijinal / Filtreli klip önizleme (video kopya, ses mono; hızlı)
- 
- Yüzde ilerleme ve log dosyası
- 
- Humanize, stil profilleri (Natural/Warm/Crisp/Radio)
- 
- RNNoise (.model) desteği (varsa), yoksa AFFTDN fallback
- 
- Dışa aktarımda her zaman işlenmiş ses
- 
- Logo: pencere simgesi + üst araç çubuğu + başlık satırında tıklanabilir


**Kurulum**


- FFmpeg ve FFprobe sistem PATH’inde olmalı.
- 
- Python 3.10+ önerilir.
- 
- Gerekli paket:
- 
- pip install PySide6
- 
- Çalıştırma
- python ses.py

**Logo Ayarı**

Kodun başındaki:

```
LOGO_IMAGE_URL = "osmantemiz.com"
LOGO_LINK_URL  = "osmantemiz.com"
```


değerlerini kendi logon ve bağlantınla değiştir.


<img width="1917" height="1016" alt="Image" src="https://github.com/user-attachments/assets/ba817218-da2e-42d4-9894-04f683451cee" />

**Sistem Gereksinimleri**

- Windows 10/11, macOS, veya Linux
- 
- FFmpeg 6+ önerilir (arnndn/afftdn/agate/equalizer/loudnorm)
