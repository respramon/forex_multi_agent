# Strategi dan risiko

## Trend dan konteks timeframe

Bullish: close > EMA20 > EMA50 > EMA200 dan EMA50 naik dibanding lima bar sebelumnya.
Bearish: susunan terbalik dan EMA50 turun. Sisanya RANGE, yang tidak memiliki strategi
entry aktif. Minimum 250 bar tertutup; angka seed EMA/ATR dapat berbeda dari platform
yang menggunakan histori atau metode seed berbeda.

| Timeframe pemicu | Konteks wajib |
|---|---|
| M5 | M15 dan H1 |
| M15 | H1 dan H4 |
| H1 | H4 dan Daily |
| H4 | Daily |
| Daily | H4 sebagai konfirmasi lebih rendah; Daily tetap penentu utama |

Lima pemeriksaan: keselarasan trend, zona RSI, arah histogram MACD, candle directional
atau pola bullish/bearish, dan sisi harga terhadap BB tengah. Default 4/5. Trend
selaras dan RSI harus lolos sekalipun jumlah konfirmasi sudah cukup. BUY mensyaratkan
RSI 50–72; SELL 28–50. Skor = jumlah lolos / 5 × 100. Skor 100 tidak berarti peluang
menang 100%, dan tidak mengalahkan veto lain.

## Pemicu

| Strategi | Aturan ringkas |
|---|---|
| Breakout | Close menembus high/low 20 bar sebelumnya dengan buffer 0,1 ATR; candle sebelumnya belum di sisi breakout |
| Pullback | Candle menyentuh area EMA20 ± 0,15 ATR dan menutup kembali di sisi trend, dengan konfirmasi candle |
| Trend following | Close melampaui high/low candle sebelumnya sesuai trend |

Prioritas pemilihan: breakout → pullback → trend following. Batas ekstensi harga
2,5 ATR dari EMA20 mencegah mengejar gerakan. ATR > 2,5× rata-rata historis pembanding
menolak lonjakan volatilitas. Spread > 0,15 ATR menolak transaksi.

S/R berasal dari pivot high/low ketat pada 120 bar terakhir dengan dua bar di kiri
dan kanan; dua bar kanan harus sudah tutup. Struktur HH/HL atau LH/LL membutuhkan
setidaknya dua swing masing-masing. Fibonacci hanya dibuat jika urutan swing
terkonfirmasi sesuai arah trend; tidak ada anchor berarti tidak ada level Fibonacci.

Proxy SMC: close melewati swing (BOS), wick menyapu lalu kembali (liquidity sweep),
serta gap antara candle pertama dan ketiga (FVG). Ini observasi heuristik. Tidak ada
deteksi order block institusional atau bukti likuiditas tersembunyi. SMC dan Fibonacci
tidak dihitung sebagai konfirmasi independen dalam kuota lima pemeriksaan.

## Fundamental

Kalender harus berstatus `ok`, segar ≤ 15 menit, mencakup seluruh jendela 30 menit
sebelum/sesudah sekarang dan kedua mata uang pasangan forex.
FundamentalAgent memberi veto untuk high-impact. Data actual/forecast/previous ditampilkan
sebagai konteks; tidak ada aturan universal bahwa kejutan data tertentu selalu
menaikkan mata uang.

Sentimen Alpha Vantage dirata-ratakan dengan bobot relevansi ticker mata uang;
artikel di luar 24 jam ditolak. Minimal tiga observasi segar per mata uang. Skor
pasangan = (skor base − skor quote) / 2. Skor berlawanan kuat (< −0,4 untuk BUY atau
> +0,4 untuk SELL) menjadi veto. Sentimen kosong menambah catatan keterbatasan dan
tidak dihitung netral. CurrencySentimentAgent menghasilkan ABSTAIN ketika sentimen
pasangan tidak lengkap, dan VETO untuk sentimen yang berlawanan kuat.

## Level transaksi

Area entry = close ± 0,1 ATR, dibulatkan keluar ke tick broker. Sizing memakai batas
terburuk: sisi atas untuk BUY dan bawah untuk SELL. SL berada minimal 1,5 ATR dari
entry dan di luar ekstrem lima candle terakhir dengan buffer 0,2 ATR. Target dihitung
agar RR setelah estimasi biaya minimal dua. Target dibulatkan menjauh dari entry.
Jika S/R terkonfirmasi menghalangi target, hasilnya NO_TRADE.

Semua level memakai **midpoint**. Spread penuh dimasukkan sebagai estimasi biaya
round trip, ditambah allowance slippage 0,05 ATR dan komisi round trip. Ini belum
merupakan harga fill bid/ask aktual. Risk Manager menggunakan konvensi midpoint yang
sama; jangan memasukkan harga fill ask dan menambahkan spread lagi tanpa konversi.

## Rumus ukuran posisi

Dengan E = ekuitas, r = fraksi risiko, q = jumlah units, D = jarak entry–SL,
T = jarak entry–TP, L/G = faktor konversi kerugian/keuntungan quote ke mata uang akun,
S = spread + allowance slippage:

```text
budget = E × r
commission(q) = max(q × komisi_per_unit_roundtrip, minimum_komisi_roundtrip)
estimated_loss(q) = q × (D + S) × L + commission(q)
net_reward(q) = q × (T × G − S × L) − commission(q)
net_RR = net_reward(q) / estimated_loss(q)
estimated_margin(q) = q × entry × position_conversion × margin_rate
lots = q / contract_size
```

q terbesar dibatasi oleh budget, maksimum units broker, dan 50% free margin,
kemudian dibulatkan ke bawah mengikuti `units_step`. Noise floating-point pada
batas grid dinormalisasi pada sepuluh desimal grid; hasil diverifikasi kembali
dengan toleransi kas 1e−8 mata uang akun. Ukuran di bawah minimum broker ditolak.
Permintaan units manual yang melebihi batas ditolak dan diberi suggested_units.
Perbedaan faktor gain/loss dan komisi minimum tetap diperiksa pada RR akhir.

Contoh matematis tanpa biaya: akun USD 10.000, risiko 1%, EUR/USD entry 1,1000 dan
SL 1,0950 → 20.000 units = 0,20 lot jika 1 lot = 100.000 units. Untuk USD/JPY entry
150 dan SL 149 dengan faktor konversi 1/150 JPY ke USD, anggaran USD 100 →
15.000 units = 0,15 lot. Kedua contoh hanya ilustrasi perhitungan, bukan setup pasar.

## Disiplin portofolio

- Kerugian harian memakai maksimum antara penurunan ekuitas dari awal hari dan
  kerugian P/L bersih jurnal hari ini; deposit/withdrawal membutuhkan penyesuaian baseline.
- Trade harian dihitung dari waktu buka; P/L dan streak dari waktu tutup. Hari
  bawaan Asia/Bangkok. Streak kekalahan direset ketika hari berubah atau trade non-rugi ditutup.
- Risiko terbuka adalah jumlah `initial_risk` seluruh trade terbuka. Pengurangan
  risiko setelah trailing SL tidak otomatis diasumsikan. Kenaikan risiko posisi
  di broker harus direkonsiliasi; aplikasi belum menyinkronkan perubahan SL.
- Eksposur per mata uang dijumlahkan secara konservatif tanpa saling menghapus hedge.
  EUR/USD dan GBP/USD sama-sama memakai anggaran USD. Ini bukan model korelasi statistik.
- Signal Mode dibatasi terpisah: maksimal tiga penerbitan sehari, jeda 60 menit,
  satu fingerprint per pair/timeframe/candle/arah, tersimpan secara atomik.

Pengaturan broker, gap, swap, likuiditas, slippage aktual, perubahan konversi, dan
ketidaklengkapan jurnal dapat membuat rugi riil berbeda. Stop loss dan estimasi
risiko tidak menjamin batas kerugian. Validasi dengan paper trading dan data aktual
sebelum mengandalkan strategi. Replay aturan Signal Mode tersedia, tetapi fixture
yang disertakan sintetis dan belum memvalidasi profitabilitas pada data pasar nyata.
