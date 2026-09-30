# Tools dan API

| Komponen | Status dalam paket | Kegunaan dan konfigurasi |
|---|---|---|
| Python standard library | Aktif tanpa kredensial | Indikator, policy, sizing, CLI, HTTP, SQLite |
| OANDA v20 REST | Adapter baca aktif | Candle, bid/ask, spesifikasi instrumen, account NAV/margin, konversi dan daftar tiket terbuka |
| CSV/JSON | Adapter aktif | Snapshot broker alternatif dan kalender yang dinormalisasi |
| Alpha Vantage NEWS_SENTIMENT | Adapter aktif | Skor sentimen mata uang per ticker, bobot relevansi |
| OpenAI Responses | Adapter opsional aktif | Narasi ringkas dari laporan yang sudah divalidasi |
| Trading Economics calendar | Sumber integrasi eksternal; adapter unduhan belum dibuat | Normalisasi kalender ke kontrak JSON |
| MetaTrader 5 | Belum diimplementasikan | Ekspor candle/metadata lewat CSV atau buat adapter sendiri |
| API eksekusi order | Tidak disediakan | Keputusan dan eksekusi tetap pada pengguna |

## OANDA

Kunci: `OANDA_API_TOKEN`, `OANDA_ACCOUNT_ID`. `--environment practice` adalah default;
`live` hanya mengubah sumber data baca. Adapter tidak memanggil endpoint order.

Endpoint GET yang dipakai:

- `/v3/accounts/{accountID}/instruments?instruments=...`
- `/v3/accounts/{accountID}/summary`
- `/v3/accounts/{accountID}/openTrades`
- `/v3/accounts/{accountID}/instruments/{instrument}/candles`
- `/v3/accounts/{accountID}/pricing?instruments=...&includeHomeConversions=true`

Summary dan openTrades harus memiliki `lastTransactionID` yang sama; jika status
akun berubah di antaranya, snapshot ditolak untuk diambil ulang. Tiket mencakup
ID, units saat ini, entry, attached SL/TP. Posisi tanpa SL/TP atau konversi yang
dibutuhkan akan diblokir oleh Signal/Risk Mode. Metadata broker menentukan
pipLocation, displayPrecision, precision units, minimum,
maksimum, margin, dan komisi jika disediakan. Konvensi units per lot diberikan
pengguna. Bila pair tidak tersedia atau konversi tidak ada, pengambilan gagal dengan
pesan eksplisit. Tidak ada pengganti harga berupa angka buatan.

Transport HTTPS menolak redirect, mempunyai timeout, batas respons 10 MiB dan maksimal
tiga percobaan GET pada kegagalan sementara. Error tidak mencetak token atau URL
berisi kredensial. Snapshot disimpan ke `data/` dan harus segera dipakai agar segar.

## Alpha Vantage

Set `ALPHAVANTAGE_API_KEY`, lalu:

```bash
python -m forex_agent fetch-sentiment --currency USD --out data/usd-sentiment.json
python -m forex_agent fetch-sentiment --currency EUR --out data/eur-sentiment.json
```

Gabungkan kedua object ke array `sentiment` di kalender sebelum pengambilan snapshot.
Adapter memakai `function=NEWS_SENTIMENT`, filter `tickers=FOREX:USD` atau mata uang
terpilih, rentang 24 jam, dan skor ticker yang relevan. Response kuota/entitlement
atau JSON tanpa feed dianggap gagal. Paket tidak mengasumsikan semua paket akun
menyediakan setiap instrumen/frekuensi; periksa hak akses penyedia.

## Kalender eksternal

Trading Economics mendokumentasikan kalender per rentang tanggal/negara serta
importance 1/2/3. Integrator dapat menormalisasi field berikut:

| Field sumber | Field agent |
|---|---|
| Date dengan timezone yang telah dikonfirmasi | `time` ISO 8601 timezone-aware |
| Currency/negara yang dipetakan eksplisit | `currency` ISO: USD/EUR/GBP/JPY/AUD |
| Importance 1/2/3 | `impact` low/medium/high |
| Event | `title` |
| SourceURL atau URL sumber | `source` |
| Actual/Forecast/Previous | `actual` / `forecast` / `previous` |

Jangan menebak timezone dari string tanpa offset atau menebak mata uang ketika
Currency kosong. Ambil rentang yang mencakup jendela berita, simpan cakupan dan waktu
fetch, lalu set `status=ok` hanya jika pemeriksaan berhasil. Akses, lisensi data,
delay dan kuota mengikuti akun penyedia. Sampel kalender dalam paket tidak boleh
digunakan sebagai kalender aktual.

## OpenAI

Set `OPENAI_API_KEY` dan `OPENAI_MODEL`, gunakan `--explain`. Adapter HTTPS memanggil
`POST https://api.openai.com/v1/responses`, memakai `instructions`, `input`,
`store=false`, dan membaca semua bagian `output_text` dari message output.
Model dipilih pengguna; tidak ada asumsi akses atau harga model. Respons tidak
selesai/refusal/kosong gagal menjadi narasi, tanpa mengganti laporan deterministik.

Narasi bukan output yang diberi wewenang transaksi. Untuk menambah chat/tool calling,
pertahankan satu jalur melalui `ForexAgent.analyze`; jangan izinkan LLM menulis
langsung `risk`, mengganti policy, atau mengisi harga dari ingatan.

## Dokumentasi resmi yang diperiksa

Rujukan implementasi diperiksa pada 25 September 2026. Tautan menjelaskan antarmuka;
uji dengan API key akun pengguna tetap diperlukan.

- [OANDA pricing dan account-scoped candles](https://developer.oanda.com/rest-live-v20/pricing-ep/)
- [OANDA instrument specification dan pip/units](https://developer.oanda.com/rest-live-v20/primitives-df/)
- [OANDA home conversion factors](https://developer.oanda.com/rest-live-v20/pricing-df/)
- [OANDA candle definition dan complete](https://developer.oanda.com/rest-live-v20/instrument-df/)
- [OANDA account dan daftar instrumen](https://developer.oanda.com/rest-live-v20/account-ep/)
- [Alpha Vantage NEWS_SENTIMENT](https://www.alphavantage.co/documentation/#news-sentiment)
- [Trading Economics economic calendar](https://docs.tradingeconomics.com/economic_calendar/snapshot/)
- [OpenAI text generation dan Responses](https://developers.openai.com/api/docs/guides/text)
