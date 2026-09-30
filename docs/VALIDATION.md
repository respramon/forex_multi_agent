# Validasi 0.2.0 multi-agent forex

Pemeriksaan versi multi-agent dilakukan pada 30 September 2026 menggunakan
Python 3.12.14 di Linux.
Perintah untuk mengulang pengujian:

```bash
python -m unittest discover -s tests -v
python -m forex_agent agents --json
python -m forex_agent demo --json
python -m forex_agent demo --scenario news --json
python -m scripts.generate_examples
python -m scripts.generate_agent_replay_example
python -m forex_agent backtest --data examples/agent-replay.synthetic.json --out data/agent-result.json
python -m forex_agent backtest --data examples/backtest.synthetic.json --strategy sma --out data/sma-result.json
python -m compileall -q forex_agent
python -m pip wheel . --no-deps --wheel-dir dist
```

Hasil verifikasi: **107 pengujian lulus**, paket wheel 0.2.0 berhasil dibangun, fixture
contoh berhasil diregenerasi. Tes HTTP memakai server localhost sungguhan dengan
database sementara, sedangkan API eksternal memakai respons mock.

| Area | Bukti yang diperiksa |
|---|---|
| Indikator | Seed EMA, RSI datar/naik/turun, ATR dengan gap, engulfing, pivot tertunda |
| Risiko | Empat pasangan forex, akun non-USD, konversi JPY, kontrak broker, komisi minimum, biaya RR, minimum units, step, margin |
| Multi-agent | Delapan agen, veto independen, veto sentimen, eksposur setelah sizing, kegagalan setiap agen, pesan salah/NaN/dependensi hilang, jejak keputusan dan publikasi |
| Khusus forex | Penolakan logam/kripto/saham; batas pasangan pada instrument dan provider; gap rollover forex tetap ketat |
| Signal | BUY dan SELL, multi-timeframe wajib, sinyal duplikat, output tanpa level saat ditolak |
| Data | Candle future/partial/duplikat/NaN, quote stale/future, pair atau konversi salah |
| Fundamental/disiplin | Kalender unknown, berita high-impact, spread tinggi, batas kerugian |
| Jurnal | Net P/L, expectancy R, profit factor, drawdown P/L tertutup, tengah malam Bangkok, persistensi |
| Adapter | OANDA closed candle dan pemetaan spec/konversi; filter waktu dan skor ticker sentimen |
| AI | Payload tidak membawa saldo/units, hasil resmi tidak dimutasi, respons tidak selesai gagal eksplisit |
| HTTP | Health, autentikasi, manifest tim, laporan multi-agent end-to-end, JSON rusak/NaN, tidak ada endpoint order atau pembacaan path request |
| Replay agent | Sinyal dari aturan yang sama dengan Signal Mode, calendar as-of, larangan actual masa depan, area entry dan next-open |
| Replay determinism | Semua gap exit diproses sebelum fill pada open yang sama; trigger exit memakai sisi bid/ask yang diinferensikan dari midpoint dan spread |
| Rekonsiliasi | Perbedaan ID, units, SL, snapshot akun berubah, migrasi jurnal lama |
| API reliability | Idempotency journal-open, query boolean ketat, readiness database, penulisan JSON atomik dan permission `0600` |
| Riset | Interval timeframe candle cocok dengan metadata model; biaya per candle dan financing pada replay |

## Belum diverifikasi langsung

- Koneksi akun OANDA, entitlement Alpha Vantage, dan model OpenAI dengan kredensial
  pengguna. Dokumentasi resmi telah diperiksa; contract tests memakai mock.
- Build/run Docker di lingkungan ini; berkas Docker/Compose disertakan untuk
  dijalankan dan diperiksa di host pengguna.
- Matrix CI Python 3.11 dan 3.13 serta Windows/macOS; workflow GitHub menjalankan
  matrix tersebut setelah diunggah. Pengujian lokal hanya Python 3.12 Linux.
- Profitabilitas strategi, backtest out-of-sample pada data **pasar nyata**, latency/slippage aktual, dan
  ketahanan layanan publik. Simulasi sintetis menguji alur dan invariant perangkat
  lunak, bukan kemampuan memperoleh profit.
- Kesesuaian state OANDA saat koneksi jaringan nyata. Snapshot `/openTrades` dan
  versi transaksi diuji memakai mock; rekening dengan perubahan di tengah
  pengambilan perlu diuji pada akun practice.

## Evaluasi berikutnya pada lingkungan pengguna

Konfirmasi spesifikasi kontrak dan biaya broker; cocokkan satu snapshot dengan chart
broker yang memakai batas candle sama. Rekonsiliasi semua posisi dan initial_risk
jurnal. Lakukan paper trading, ukur selisih fill/biaya dan expectancy setelah biaya,
lalu uji parameter pada data terpisah. Jangan memilih parameter hanya dari hasil
fixture sintetis. Semua output tetap merupakan bantuan analisis dan pengambilan
keputusan, tanpa jaminan keuntungan atau pengiriman order otomatis.
