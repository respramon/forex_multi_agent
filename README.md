# Forex Multi-Agent

Sistem analisis **khusus forex** berbahasa Indonesia dengan **delapan agen spesialis
dan satu ForexCoordinator**, kontrol risiko, jurnal SQLite, CLI, API lokal, serta
narasi AI opsional. Setiap agen menghasilkan penilaian sendiri dengan alasan dan
bukti; koordinator mematuhi veto wajib sebelum menerbitkan sinyal. Agen spesialis
menggunakan aturan Python yang dapat dijalankan tanpa model bahasa. AI opsional
menjelaskan keputusan tim yang telah diperiksa mesin.

**Mulai tanpa API key:** Python 3.11+ dan standard library sudah cukup.

```bash
git clone https://github.com/respramon/forex_multi_agent.git
cd forex_multi_agent
python -m forex_agent agents
python -m forex_agent demo
python -m forex_agent demo --scenario news
python -m unittest discover -s tests -v
```

Contoh pertama menampilkan setup dari **data sintetis**, contoh kedua menunjukkan
penolakan menjelang berita penting fiktif. Keduanya memakai jam simulasi tetap,
bukan harga pasar saat ini. Tidak ada pengiriman order ke broker.

Paket unduhan berisi satu folder proyek lengkap. Mulai dari
[PANDUAN_PENGGUNAAN.md](PANDUAN_PENGGUNAAN.md); petunjuk mengunggah folder ke GitHub
ada di [GITHUB_UPLOAD.md](GITHUB_UPLOAD.md).

## Tim multi-agent forex

| Agen | Tanggung jawab |
|---|---|
| DataValidationAgent | Pasangan forex, candle tutup, keselarasan timestamp, quote, dan data akun |
| TechnicalAgent | Trend, momentum, struktur, pola harga, dan indikator lintas timeframe |
| FundamentalAgent | Cakupan kalender kedua mata uang dan veto berita high-impact |
| MarketConditionsAgent | Spread, volatilitas, status pasar, dan usia candle pemicu |
| PortfolioAgent | Drawdown, eksposur mata uang, jurnal, rekonsiliasi, serta risiko setelah sizing |
| StrategyAgent | Proposal trend following, breakout, pullback, atau usulan pengguna dalam mode risk |
| CurrencySentimentAgent | Dukungan/pertentangan sentimen base dan quote terhadap arah proposal |
| RiskAgent | Ukuran posisi, biaya, margin, anggaran risiko, dan RR bersih |

`ForexCoordinator` menggabungkan pesan agen dengan kebijakan `mandatory_veto`.
Proposal strategi tidak dapat menimpa penolakan data, kalender, pasar, portofolio,
sentimen berlawanan kuat, atau risiko. Sentimen yang tidak lengkap menghasilkan
`ABSTAIN` dan tidak dianggap konfirmasi. Kegagalan agen menghasilkan keputusan
yang diblokir. Agen dijadwalkan sesuai dependensi dalam satu proses; SQLite tetap
memakai transaksi atomik untuk publikasi sinyal.

```bash
python -m forex_agent agents --json
python -m forex_agent demo --json --out data/team-report.json
```

Laporan JSON menyertakan `agent_reports` dan `coordination`, termasuk verdict,
alasan, bukti, agen yang memveto, agen yang tidak dijalankan, serta status akhir.
Mode analyst hanya menjalankan agen data, teknikal, dan fundamental. Detail kontrak,
alur, dan migrasi tersedia di [docs/MULTI_AGENT.md](docs/MULTI_AGENT.md).

## Cakupan

| Kebutuhan | Implementasi |
|---|---|
| Instrumen | EUR/USD, GBP/USD, USD/JPY, AUD/USD; logam, kripto, dan saham ditolak |
| Multi-timeframe | M5, M15, H1, H4, Daily; candle tutup saja |
| Indikator | EMA20/50/200, SMA20, RSI14 Wilder, MACD12/26/9, Bollinger20/2, ATR14 Wilder |
| Struktur | Pivot terkonfirmasi, support/resistance, HH/HL atau LH/LL, Fibonacci 38,2/50/61,8% |
| Price action | Engulfing, pin bar, doji, inside bar |
| Strategi | Trend following, breakout, pullback; proxy BOS/sweep/FVG sebagai konteks SMC |
| Fundamental | Filter kalender ekonomi, actual/forecast/previous yang disuplai, sentimen mata uang |
| Risiko | Sizing otomatis, konversi mata uang, spread/slippage/komisi, margin, RR bersih ≥ 2 |
| Disiplin | Batas harian, eksposur gabungan per mata uang, cooldown, deduplikasi sinyal |
| AI | Adapter OpenAI Responses untuk penjelasan opsional; skor mesin bukan peluang menang |

## Empat mode

| Mode | Perintah | Hasil |
|---|---|---|
| Analyst | `analyze --mode analyst` | Observasi teknikal/fundamental tanpa entry/SL/TP |
| Signal | `analyze --mode signal` | BUY, SELL, atau NO_TRADE dengan alasan dan sizing |
| Risk Manager | `risk --trade ...` | APPROVED_RISK atau REJECTED untuk transaksi usulan |
| Journal | `journal ...` | Catat buka/tutup dan evaluasi P/L bersih, R, win rate, profit factor |

`APPROVED_RISK` menilai aturan risiko; pengguna tetap perlu menilai kelayakan arah
dan setup. `NO_TRADE` mengosongkan level entry, stop, target, dan RR.

## Riset paper: backtest dan baseline ML

Replay `agent` (bawaan CLI) memakai **aturan Signal Mode yang sama**: indikator,
konfirmasi timeframe, veto kalender, sizing, dan jurnal simulasi. Dataset contoh
di bawah **sepenuhnya sintetis**; hasilnya tidak mengukur potensi profit di pasar.
Replay SMA tetap tersedia sebagai contoh pengujian mesin fill, dengan pilihan
`--strategy sma` yang eksplisit.

```bash
python -m forex_agent backtest --data examples/agent-replay.synthetic.json --out data/agent-result.json
python -m forex_agent backtest --data examples/backtest.synthetic.json --strategy sma --out data/sma-result.json
python -m forex_agent train --data examples/backtest.synthetic.json --pair EUR/USD --timeframe M5 --out data/model.synthetic.json
python -m forex_agent predict --model data/model.synthetic.json --data examples/backtest.synthetic.json
```

Replay agent memerlukan `context_frames` yang sudah tutup dan
`fundamentals_history` berisi snapshot kalender **sebagaimana diketahui saat itu**.
Kalender yang tidak ada/kedaluwarsa memblokir sinyal. Harga candle dan kalender
nyata harus diperoleh dari sumber historis yang sah; contoh sintetis tidak
mewakili pasar. Backtest memvalidasi candle seluruh simbol sebelum replay, memproses sinyal pada
penutupan dan fill pada open berikutnya, mendahulukan stop jika stop serta target
terjangkau pada candle yang sama, membatalkan fill agent di luar area entry,
dan menghentikan order baru setelah batas drawdown. Spread, slippage, dan
financing per unit dapat berupa angka tetap atau deret per candle. Output
lengkap berisi event, transaksi, metrik, ringkasan alasan penolakan, hash dataset,
dan ekuitas mark-to-market.
`train` memakai fitur kausal, split menurut waktu dengan purge batas label,
normalisasi pada training saja, dan test yang tidak digunakan untuk memilih
ambang. Timeframe model diverifikasi terhadap interval candle. Skor model belum
dikalibrasi sebagai peluang menang. Format dataset,
asumsi, batas, audit, benchmark dan roadmap ada di
[PLATFORM_ROADMAP.md](docs/PLATFORM_ROADMAP.md).

Order paper tersimpan dalam ledger SQLite terpisah dengan idempotensi `client_id`
dan `execution_id`, fill parsial, dan reservasi risiko. Jalur ini tidak
mengirim order ke broker; OANDA pada aplikasi lama tetap baca saja.

## Instalasi opsional

Perintah `python -m forex_agent` berjalan langsung dari folder. Untuk command `forex-agent`:

```bash
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install .
forex-agent demo
```

Tidak ada dependency runtime pihak ketiga yang wajib. Instalasi paket menggunakan
setuptools sebagai build tool. Credential dibaca dari environment OS. `.env.example`
adalah panduan; file `.env` tidak dibaca otomatis oleh CLI.

## Jalankan analisis dan risiko

```bash
# Contoh file yang disertakan: simulasi, bukan pasar berjalan.
python -m forex_agent analyze --snapshot examples/synthetic_snapshot.json --mode analyst
python -m forex_agent analyze --snapshot examples/synthetic_snapshot.json --mode signal --db data/demo.sqlite3 --json
python -m forex_agent risk --snapshot examples/synthetic_snapshot.json --trade examples/proposed_trade.json --db data/demo.sqlite3

# Semua parameter risiko tersentral di config/risk.json.
python -m forex_agent demo --policy config/risk.json --out data/report.json

# Instrument/timeframe lain; NO_TRADE adalah keluaran yang sah.
python -m forex_agent demo --pair "USD/JPY" --timeframe H1
```

Demo memakai database sementara baru setiap kali. Analisis file memakai SQLite
persisten; permintaan sinyal yang sama akan ditolak jika sudah diterbitkan.
Mode Analyst dan Risk Manager tidak mengonsumsi kuota penerbitan sinyal.

## Narasi AI opsional

Set `OPENAI_API_KEY` dan `OPENAI_MODEL` ke model yang tersedia pada proyek API Anda,
lalu tambahkan `--explain`:

```bash
python -m forex_agent demo --explain
```

Ringkasan pair, status, alasan, risiko, dan timestamp dikirim untuk narasi. Saldo,
posisi, isi jurnal, dan bukti akun dalam laporan agen tidak disertakan. Model
menerima ringkasan verdict tim. Prompt utama berada di
[`forex_agent/prompts/system.md`](forex_agent/prompts/system.md). Output AI berada di
`ai_commentary_unverified`; kegagalan AI tidak mengubah hasil perhitungan.
Biaya dan ketersediaan model mengikuti akun penyedia.

## Sumber data berjalan

Adapter OANDA mendukung pengambilan candle, quote, metadata instrumen, NAV, margin,
jumlah trade terbuka, dan konversi mata uang. Environment bawaan adalah **practice**.
Pasangan forex yang tersedia mengikuti akun dan divisi broker.

```bash
# Set OANDA_API_TOKEN dan OANDA_ACCOUNT_ID melalui environment terlebih dahulu.
# Gunakan kalender aktual yang sudah dinormalisasi, bukan contoh sintetis.
python -m forex_agent fetch-oanda --pair "EUR/USD" --contract-size 100000 --day-start-equity 10000 --fundamentals data/calendar-current.json --out data/market.json
python -m forex_agent analyze --snapshot data/market.json --mode signal --db data/account-practice.sqlite3
```

`--contract-size` adalah konvensi **units per lot** broker Anda. Contoh 100.000 untuk
forex harus sesuai spesifikasi akun Anda. OANDA menerima units; lot di laporan adalah
ekuivalen berdasarkan ukuran kontrak yang Anda berikan. `--day-start-equity` harus
sesuai ekuitas awal hari akun pada timezone jurnal (bawaan Asia/Bangkok).

Kalender di versi ini diimpor melalui JSON terverifikasi dari pengguna/pipeline
eksternal; adapter unduhan kalender otomatis belum disertakan. Jika kalender tidak
diketahui, kedaluwarsa, atau tidak mencakup mata uang terkait, sinyal diblokir.
Adapter sentimen Alpha Vantage sudah tersedia; hasilnya dapat digabungkan ke
`fundamentals.sentiment`. Lihat [integrasi](docs/INTEGRATIONS.md).

Jumlah trade terbuka snapshot harus sama dengan jurnal. Rekonsiliasi tiket, ukuran,
level entry/SL/TP, dan batas bawah risiko kini diperiksa pada semua posisi nyata.
Adapter OANDA mengambil `/openTrades`; bila daftar tiket, ID jurnal, level,
konversi, atau versi transaksi akun tidak cocok, Signal/Risk Mode ditolak.
Simpan `broker_trade_id` di entri jurnal nyata. Posisi dari broker lain harus
menyediakan `broker_open_trades` dengan kontrak yang sama.

## Jurnal

```bash
python -m forex_agent journal --db data/demo.sqlite3 open --file examples/journal_trade.json
python -m forex_agent journal --db data/demo.sqlite3 close --id demo-001 --net-pnl 180 --closed-at 2026-01-15T14:00:00Z
python -m forex_agent journal --db data/demo.sqlite3 summary --simulated
# Untuk jurnal akun nyata lama, tautkan ID tiket sesudah mencocokkan detailnya:
python -m forex_agent journal --db data/account-practice.sqlite3 link --id ID_JURNAL --broker-trade-id ID_OANDA
# Setelah perubahan units/SL/TP broker, perbarui catatan secara konservatif:
python -m forex_agent journal --db data/account-practice.sqlite3 amend --id ID_JURNAL --file data/amend-trade.json
```

Masukkan P/L dalam mata uang akun **setelah semua komisi, swap, dan biaya aktual**.
`initial_risk` adalah risiko kas awal termasuk estimasi biaya, bukan persen. Simulasi
dan transaksi nyata dipisahkan dalam kueri. Gunakan satu database per akun dan mata
uang. Untuk transaksi nyata baru, tambahkan `"broker_trade_id":"ID_OANDA"` pada
file JSON pembukaan jurnal. File amend berisi `units`, `entry`, `stop`, `target`,
dan `initial_risk`; cadangan risiko awal tidak boleh diturunkan. Jurnal tidak
mengirim atau menutup order broker.

## API lokal dan Docker

```bash
# Contoh Bash: token acak disimpan hanya dalam environment sesi.
export FOREX_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python -m forex_agent serve --policy config/risk.json
# Terminal lain: GET http://127.0.0.1:8000/health
```

Untuk Docker, set environment token yang sama lalu jalankan:

```bash
docker compose up --build
```

API berada di localhost port 8000. `/health` dan `/ready` tidak membutuhkan auth;
endpoint lain membutuhkan `Authorization: Bearer ...`. SQLite tersimpan pada named
volume. Untuk retry `journal/open`, gunakan `Idempotency-Key` atau `client_id` agar
catatan tidak diduplikasi. Petunjuk request dan batas pemakaian server ada di
[API.md](docs/API.md).

## Parameter bawaan

| Aturan | Nilai |
|---|---:|
| Risiko per transaksi / batas keras | 1% / 2% |
| RR bersih minimum | 1:2 |
| Minimum jarak SL | 1,5 × ATR14; struktur dapat memperlebar |
| Konfirmasi | 4 dari 5; keselarasan trend dan RSI wajib |
| Kerugian harian | 3% ekuitas awal hari |
| Risiko portofolio terbuka | 4% ekuitas |
| Risiko terbuka per mata uang | 3% ekuitas; tidak saling menetralkan posisi |
| Transaksi / sinyal per hari | Masing-masing maksimum 3 |
| Kekalahan beruntun dalam hari jurnal | 3 |
| Jeda antar-aktivitas / antar-sinyal | 60 menit |
| Jendela berita high-impact | 30 menit sebelum dan sesudah |
| Maksimum usia quote/akun/konversi | 120 detik |
| Maksimum usia kalender | 15 menit |

Nilai ini adalah aturan desain contoh yang perlu dievaluasi dengan data broker
Anda. Skor konfirmasi bukan estimasi probabilitas, dan belum ada klaim profitabilitas
atau validasi hasil strategi pada data pasar nyata.

## Isi proyek

| Lokasi | Isi |
|---|---|
| `forex_agent/` | Engine, indikator, strategi, risiko, replay agent, adapter, CLI, API, jurnal |
| `forex_agent/agents/` | Delapan agen spesialis dan kontrak pesan antaragen |
| `forex_agent/prompts/` | Prompt sistem utama |
| `config/` | Aturan risiko |
| `docs/ARCHITECTURE.md` | Arsitektur dan workflow |
| `docs/MULTI_AGENT.md` | Koordinasi agen, verdict, veto, dan kompatibilitas |
| `docs/STRATEGY_AND_RISK.md` | Definisi strategi, rumus, asumsi dan batas implementasi |
| `docs/INTEGRATIONS.md` | Tools/API, autentikasi, sumber dokumentasi resmi |
| `docs/DATA_CONTRACT.md` | Format snapshot, kalender, CSV, waktu dan mata uang |
| `docs/SIMULATION.md` | Contoh penggunaan dan output yang dihasilkan kode |
| `docs/VALIDATION.md` | Hasil pengujian dan bagian yang belum diuji langsung |
| `examples/` | Snapshot sintetis, output, proposal, contoh jurnal |
| `schemas/` | JSON Schema snapshot |
| `tests/` | Pengujian aturan dan integrasi dengan mock |
| `.github/workflows/` | CI Python 3.11–3.13 |

## Kontribusi dan data

CI menjalankan tes Python 3.11–3.13 dan contoh replay sintetis. Jangan unggah
`.env`, snapshot akun nyata, kalender berlisensi, atau database jurnal. File
sensitif ditempatkan di `data/` yang diabaikan Git. Lisensi MIT; lihat
[SECURITY.md](SECURITY.md).
