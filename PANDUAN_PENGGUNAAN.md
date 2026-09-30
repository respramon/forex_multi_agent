# Panduan Penggunaan Forex Multi-Agent

Panduan ini berlaku untuk **versi 0.2.0: delapan agen spesialis forex dan satu koordinator**. Jalankan semua perintah dari **folder utama proyek** (`forex_ai_agent`), baik setelah mengekstrak paket ZIP maupun setelah clone GitHub. Pasangan yang didukung adalah EUR/USD, GBP/USD, USD/JPY, dan AUD/USD. Lihat `python -m forex_agent --help` dan [README](README.md) untuk daftar perintah.

> **Batas penting:** proyek ini membantu analisis, pemeriksaan risiko, pencatatan, dan simulasi. Proyek **tidak mengirim order** ke broker. Semua contoh bawaan menggunakan data sintetis bertanggal 15 Januari 2026, bukan harga atau sinyal pasar saat ini. Skor konfirmasi dan hasil simulasi bukan peluang menang atau bukti profitabilitas.

## 1. Siapkan komputer dan coba demo

Yang dibutuhkan: **Python 3.11 atau lebih baru** dan Git. Untuk demo, tidak perlu memasang paket Python tambahan maupun memiliki API key.

```bash
python --version
git clone https://github.com/respramon/forex_ai_agent.git
cd forex_ai_agent
python -m forex_agent agents
python -m forex_agent demo
```

Di Windows, jika `python` tidak dikenali, gunakan launcher `py -3` sebagai pengganti `python` pada contoh perintah. Hasil demo normal akan menampilkan `EUR/USD`, `M15`, `BUY`, area entry, stop loss, take profit, dan ukuran posisi. **Angka tersebut hanya contoh sintetis**; jangan menyalinnya untuk transaksi nyata.

Coba kondisi ketika transaksi ditolak karena berita fiktif:

```bash
python -m forex_agent demo --scenario news
```

Hasil yang diharapkan adalah `NO_TRADE`; area entry, stop loss, take profit, dan rasio risiko/imbalan akan menjadi `N/A`. Setiap pemanggilan `demo` memakai database sementara yang baru, sehingga cocok untuk belajar tanpa mengubah jurnal tersimpan.

Jika memakai ZIP, cukup ekstrak lalu jalankan `cd forex_ai_agent`; langkah clone
tidak diperlukan. `python -m forex_agent agents` menampilkan peran delapan agen.
Laporan terminal menampilkan verdict setiap agen dan keputusan koordinator.
Untuk melihat bukti serta dependensinya, jalankan `python -m forex_agent demo --json`.
Field `coordination.vetoed_by` menunjukkan sumber veto; `not_run` menjelaskan agen
yang dilewati sesuai mode atau penolakan sebelumnya. Lihat [panduan multi-agent](docs/MULTI_AGENT.md).

## 2. Pilih fungsi yang sesuai

| Keperluan | Perintah utama | Arti hasil |
|---|---|---|
| Melihat daftar agen forex | `agents --json` | Peran, dependensi, metode, dan pasangan yang didukung |
| Mengamati pasar tanpa level transaksi | `analyze --mode analyst` | `ANALYSIS_ONLY` |
| Memeriksa syarat sinyal dan ukuran posisi | `analyze --mode signal` | `BUY`, `SELL`, atau `NO_TRADE` |
| Memeriksa transaksi yang Anda usulkan | `risk --trade ...` | `APPROVED_RISK` atau `REJECTED` |
| Mencatat transaksi dan hasilnya | `journal open/close/summary` | Catatan pada SQLite |
| Menguji alur pada data historis | `backtest` | Hasil replay simulasi |

`APPROVED_RISK` berarti usulan memenuhi pemeriksaan **risiko**, bukan berarti arah dan strategi sudah benar. `NO_TRADE` adalah hasil yang sah, misalnya ketika data tidak lengkap, kalender tidak tepercaya, quote kedaluwarsa, atau batas risiko terlampaui. Skor `confidence` menunjukkan kecocokan dengan aturan, **bukan probabilitas keuntungan**.

## 3. Jalankan contoh analisis dan pemeriksaan risiko

Perintah di bawah menggunakan berkas contoh dalam `examples/`. Opsi `--db` menunjuk ke database SQLite yang disimpan di `data/`.

```bash
python -m forex_agent analyze --snapshot examples/synthetic_snapshot.json --mode analyst
python -m forex_agent analyze --snapshot examples/synthetic_snapshot.json --mode signal --db data/panduan-sinyal.sqlite3
python -m forex_agent risk --snapshot examples/synthetic_snapshot.json --trade examples/proposed_trade.json --db data/panduan-sinyal.sqlite3
```

Perintah pertama hanya menyajikan observasi. Perintah kedua dapat menghasilkan sinyal contoh beserta entry, stop, target, dan ukuran posisi. Perintah ketiga menilai usulan pada [`examples/proposed_trade.json`](examples/proposed_trade.json); pemeriksaan risiko tidak menerbitkan sinyal baru.

Jika perintah **signal** yang sama dijalankan lagi dengan snapshot dan `--db` yang sama, hasil dapat menjadi `NO_TRADE` karena pencegahan sinyal duplikat. Gunakan database yang sama untuk satu akun; untuk belajar dengan keadaan baru, gunakan nama database latihan yang baru. Jangan menghapus jurnal akun nyata demi mengulang contoh.

Tambahkan `--json` untuk menampilkan laporan JSON di terminal, atau `--out data/laporan.json` untuk menyimpan laporan. Opsi `--policy config/risk.json` memakai berkas kebijakan yang disediakan; sesuaikan parameter hanya setelah memahami konsekuensinya. Rincian perhitungan ada di [strategi dan risiko](docs/STRATEGY_AND_RISK.md).

## 4. Catat transaksi latihan

Gunakan **database latihan terpisah** supaya langkah ini tidak bercampur dengan sinyal di bagian 3:

```bash
python -m forex_agent journal --db data/panduan-jurnal.sqlite3 open --file examples/journal_trade.json
python -m forex_agent journal --db data/panduan-jurnal.sqlite3 close --id demo-001 --net-pnl 180 --closed-at 2026-01-15T14:00:00Z
python -m forex_agent journal --db data/panduan-jurnal.sqlite3 summary --simulated
```

`180` adalah laba bersih **fiktif** dalam mata uang akun; pada data sendiri, isikan P/L setelah biaya aktual. `--simulated` menampilkan jurnal simulasi. Pencatatan `open` dan `close` **tidak membuka atau menutup posisi di broker**. Jangan jalankan `open` contoh dua kali pada database yang sama karena `trade_id` contoh adalah `demo-001`. Panduan pencocokan posisi nyata dengan tiket broker ada di [README bagian Jurnal](README.md#jurnal) dan [kontrak data](docs/DATA_CONTRACT.md).

## 5. Gunakan data sendiri jika sudah siap

### Pilihan A: impor CSV

Siapkan `M5.csv`, `M15.csv`, `H1.csv`, `H4.csv`, dan `Daily.csv` di satu folder. Header setiap file:

```csv
time,open,high,low,close,volume,complete
```

`time` harus berupa **waktu penutupan** candle dengan zona waktu, misalnya `2026-01-15T12:00:00Z`. Hanya gunakan candle selesai; tiap timeframe yang dibutuhkan memerlukan sedikitnya 250 candle. Siapkan metadata snapshot terpisah tanpa `frames`, sesuai [kontrak data](docs/DATA_CONTRACT.md) dan [contoh metadata](examples/metadata.synthetic.json), lalu jalankan:

```bash
python -m forex_agent import-csv --folder data/csv --metadata data/metadata.json --out data/snapshot.json
python -m forex_agent analyze --snapshot data/snapshot.json --mode analyst --db data/akun-latihan.sqlite3
```

Program tidak meresampling CSV secara otomatis. Metadata, waktu, quote, akun, konversi, dan kalender harus cocok dengan keadaan sebenarnya; jangan menandai data nyata sebagai simulasi atau memakai metadata sintetis sebagai data akun.

### Pilihan B: ambil snapshot OANDA practice (opsional)

Siapkan environment variables `OANDA_API_TOKEN` dan `OANDA_ACCOUNT_ID` untuk akun Anda, serta file kalender **aktual dan terverifikasi** `data/calendar-current.json` sesuai [kontrak kalender](docs/DATA_CONTRACT.md#kalender-dan-sentimen). `.env.example` hanya daftar nama variabel: membuat file `.env` saja **tidak** membuat CLI membacanya. Jangan masukkan token ke repositori.

```bash
python -m forex_agent fetch-oanda --pair "EUR/USD" --environment practice --contract-size 100000 --day-start-equity 10000 --fundamentals data/calendar-current.json --out data/market.json
python -m forex_agent analyze --snapshot data/market.json --mode analyst --db data/akun-practice.sqlite3
```

Angka `100000` (units per lot) dan `10000` (ekuitas awal hari dalam mata uang akun) **hanya contoh**: ganti sesuai spesifikasi broker dan akun. `practice` adalah pilihan bawaan; adapter OANDA membaca data akun/pasar dan **tidak mengirim order**, termasuk bila sumber data diubah ke `live`. Gunakan snapshot segera karena quote, akun, konversi, dan kalender memiliki batas usia. Unduhan kalender ekonomi otomatis belum disediakan: tanpa kalender yang sah dan mencakup mata uang terkait, sinyal diblokir. Jangan mengubah `status` kalender menjadi `ok` tanpa pemeriksaan sumber. Lihat [rincian integrasi](docs/INTEGRATIONS.md).

Untuk posisi nyata yang sudah terbuka, samakan tiket, ukuran, entry, stop, dan target antara broker dan jurnal sebelum meminta `signal` atau `risk`; perbedaan akan menyebabkan penolakan. Mulailah dari `analyst` untuk memeriksa data tanpa menerbitkan sinyal.

## 6. Fitur lanjutan (opsional)

**Replay dan model riset** berikut memakai data sintetis bawaan. Berkas hasil ditulis di `data/`, yang diabaikan Git:

```bash
python -m forex_agent backtest --data examples/agent-replay.synthetic.json --out data/agent-result.json
python -m forex_agent train --data examples/backtest.synthetic.json --pair EUR/USD --timeframe M5 --out data/model.synthetic.json
python -m forex_agent predict --model data/model.synthetic.json --data examples/backtest.synthetic.json
```

`backtest` memakai aturan signal utama secara bawaan; opsi `--strategy sma` hanya contoh mesin replay lain. Skor model `predict` belum dikalibrasi menjadi peluang menang. Untuk riset dengan data historis sendiri, periksa format dan batas evaluasinya di [roadmap riset](docs/PLATFORM_ROADMAP.md).

**Narasi AI** dapat ditambahkan dengan environment variables `OPENAI_API_KEY` dan `OPENAI_MODEL`, lalu `python -m forex_agent demo --explain`. Ini memerlukan akses model pada akun API Anda. Komentar AI berada pada field `ai_commentary_unverified`; ia tidak mengubah keputusan mesin. Jika narasi gagal, hasil analisis utama tetap tersedia. API lokal tersedia melalui `serve`, tetapi membutuhkan `FOREX_API_TOKEN` minimal 32 karakter; contoh request ada di [dokumen API](docs/API.md).

## Jika terjadi masalah

| Gejala | Tindakan |
|---|---|
| `No module named forex_agent` | Pastikan terminal berada di root hasil clone (`cd forex_ai_agent`) dan memakai Python 3.11+. |
| `NO_TRADE` pada percobaan ulang | Periksa alasan pada output; snapshot dan database yang sama bisa dianggap sinyal duplikat. |
| `NO_TRADE` atau penolakan pada data sendiri | Periksa usia quote/akun/konversi, candle yang sudah tutup, cakupan dan usia kalender, serta kecocokan posisi broker dengan jurnal. |
| `fetch-oanda` gagal | Periksa environment variables, hak akses akun/instrumen, dan file kalender yang diberikan lewat `--fundamentals`. |
| `--explain` tidak memberi narasi | Periksa `OPENAI_API_KEY`, `OPENAI_MODEL`, dan akses model pada proyek API Anda; keputusan dasar tetap dapat dibaca. |
| Bingung dengan opsi suatu perintah | Jalankan `python -m forex_agent <perintah> --help`, misalnya `python -m forex_agent analyze --help`. |

Untuk memeriksa instalasi kode secara lokal, jalankan `python -m unittest discover -s tests -v`. Pengujian yang tercatat di [dokumen validasi](docs/VALIDATION.md) menggunakan mock untuk integrasi eksternal; koneksi akun Anda, hasil pasar nyata, dan kemampuan memperoleh profit perlu diperiksa sendiri secara terpisah. Saat menambahkan panduan ini ke repo, simpan file di **root repositori** agar tautan relatif di atas bekerja. Hindari mem-push token, data akun, atau database jurnal.
