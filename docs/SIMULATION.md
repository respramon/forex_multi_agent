# Simulasi penggunaan multi-agent forex

Dokumen ini dihasilkan oleh `python -m scripts.generate_examples`. Seluruh harga,
kalender, kontrak, akun USD 10.000, dan hasil jurnal di bawah adalah **sintetis**.
Laporan menampilkan penilaian agen spesialis dan keputusan ForexCoordinator.
Jam simulasi 15 Januari 2026 pukul 12:00 UTC (19:00 Asia/Bangkok). Data bukan pasar
sekarang, dan hasil jurnal bukan backtest maupun bukti profitabilitas.

## 1. Signal Mode — kondisi memenuhi aturan

```bash
python -m forex_agent demo
```

```text
PAIR: EUR/USD
TIMEFRAME: M15
MARKET CONDITION: TRENDING
TREND: BULLISH
SETUP: TREND_FOLLOWING | BUY
ENTRY AREA: [1.10132, 1.10147]
STOP LOSS: 1.10044
TAKE PROFIT: 1.1037
RISK/REWARD: 1:2.01
ALASAN ANALISIS: Trend M15: BULLISH; struktur: MIXED. | Konteks: H1 BULLISH, H4 BULLISH | Konfirmasi 5/5: trend_multi_timeframe, rsi_zone, macd_momentum, price_action, bollinger_direction; RSI14 69.7, MACD histogram 0.000206844. | Sentimen tidak lengkap; agen sentimen tidak memberi konfirmasi arah. | TREND_FOLLOWING: RR bersih 2.01; sizing pada sisi area entry terburuk.
TINGKAT KEPERCAYAAN: 100 — Bukan probabilitas menang; indikator dapat berkorelasi.
RISIKO YANG PERLU DIPERHATIKAN: Trading berleverage dapat merugi; stop loss tidak menjamin batas rugi saat gap. | SIMULASI SINTETIS/HISTORIS — bukan harga atau sinyal pasar saat ini. | Sentimen pasangan tidak lengkap; tidak diasumsikan netral atau dijadikan konfirmasi. | Setup kedaluwarsa pada candle berikutnya; hitung ulang risiko sebelum entry manual.
LOT SIZE: 0.900000 (90000 units); estimasi rugi 97.58 USD
LAPORAN AGEN:
  data_validation [analysis]: APPROVE — Pemeriksaan selesai.
  technical [analysis]: OBSERVE — Trend M15: BULLISH; struktur: MIXED.; Konteks: H1 BULLISH, H4 BULLISH
  fundamental [analysis]: APPROVE — Pemeriksaan selesai.
  market_conditions [analysis]: APPROVE — Pemeriksaan selesai.
  portfolio [preflight]: APPROVE — Pemeriksaan selesai.
  strategy [analysis]: PROPOSE — Konfirmasi 5/5: trend_multi_timeframe, rsi_zone, macd_momentum, price_action, bollinger_direction; RSI14 69.7, MACD histogram 0.000206844.
  currency_sentiment [analysis]: ABSTAIN — Sentimen tidak lengkap; agen sentimen tidak memberi konfirmasi arah.
  risk [analysis]: APPROVE — Pemeriksaan selesai.
  portfolio [sized]: APPROVE — Pemeriksaan selesai.
KOORDINATOR: BUY
DATA: SYNTHETIC — not market data | 2026-01-15T12:00:00Z
```

Anggaran maksimum USD 100. Ukuran yang lolos juga dibatasi langkah units dan margin.
Risiko dihitung pada batas entry terburuk, termasuk estimasi biaya. Entry pada harga
berbeda membutuhkan perhitungan ulang. Skor 100 berarti lima pemeriksaan indikator
lolos pada data buatan; skor tersebut bukan probabilitas atau akurasi prediksi.

## 2. Signal Mode — berita penting

```bash
python -m forex_agent demo --scenario news
```

```text
PAIR: EUR/USD
TIMEFRAME: M15
MARKET CONDITION: TRENDING
TREND: BULLISH
SETUP: NONE | NO_TRADE
ENTRY AREA: N/A
STOP LOSS: N/A
TAKE PROFIT: N/A
RISK/REWARD: N/A
ALASAN ANALISIS: Trend M15: BULLISH; struktur: MIXED. | Konteks: H1 BULLISH, H4 BULLISH | Berita high-impact USD: Rilis inflasi contoh (fiktif) (2026-01-15T12:15:00Z).
TINGKAT KEPERCAYAAN: N/A — Skor kesesuaian aturan, bukan probabilitas menang.
RISIKO YANG PERLU DIPERHATIKAN: Trading berleverage dapat merugi; stop loss tidak menjamin batas rugi saat gap. | SIMULASI SINTETIS/HISTORIS — bukan harga atau sinyal pasar saat ini. | Sentimen pasangan tidak lengkap; tidak diasumsikan netral atau dijadikan konfirmasi.
LAPORAN AGEN:
  data_validation [analysis]: APPROVE — Pemeriksaan selesai.
  technical [analysis]: OBSERVE — Trend M15: BULLISH; struktur: MIXED.; Konteks: H1 BULLISH, H4 BULLISH
  fundamental [analysis]: VETO — Berita high-impact USD: Rilis inflasi contoh (fiktif) (2026-01-15T12:15:00Z).
  market_conditions [analysis]: APPROVE — Pemeriksaan selesai.
  portfolio [preflight]: APPROVE — Pemeriksaan selesai.
KOORDINATOR: NO_TRADE; veto: fundamental
DATA: SYNTHETIC — not market data | 2026-01-15T12:00:00Z
```

## 3. Analyst Mode

```bash
python -m forex_agent demo --mode analyst --json
```

Status `ANALYSIS_ONLY`; entry/SL/TP null. Bagian `technical` berisi observasi seluruh
timeframe yang relevan; `fundamentals` memuat event dan kualitas cakupan/sentimen.

## 4. Risk Manager Mode

```bash
python -m forex_agent risk --snapshot examples/synthetic_snapshot.json --trade examples/proposed_trade.json --db data/demo.sqlite3
```

```text
PAIR: EUR/USD
TIMEFRAME: M15
MARKET CONDITION: TRENDING
TREND: BULLISH
SETUP: USER_PROPOSAL | APPROVED_RISK
ENTRY AREA: [1.10147, 1.10147]
STOP LOSS: 1.10044
TAKE PROFIT: 1.1037
RISK/REWARD: 1:2.01
ALASAN ANALISIS: Trend M15: BULLISH; struktur: MIXED. | Konteks: H1 BULLISH, H4 BULLISH | USER_PROPOSAL: RR bersih 2.01; sizing pada sisi area entry terburuk. | APPROVED_RISK hanya kelayakan risiko; tidak mengonfirmasi strategi atau arah trading.
TINGKAT KEPERCAYAAN: N/A — Skor kesesuaian aturan, bukan probabilitas menang.
RISIKO YANG PERLU DIPERHATIKAN: Trading berleverage dapat merugi; stop loss tidak menjamin batas rugi saat gap. | SIMULASI SINTETIS/HISTORIS — bukan harga atau sinyal pasar saat ini. | Sentimen pasangan tidak lengkap; tidak diasumsikan netral atau dijadikan konfirmasi.
LOT SIZE: 0.900000 (90000 units); estimasi rugi 97.58 USD
LAPORAN AGEN:
  data_validation [analysis]: APPROVE — Pemeriksaan selesai.
  technical [analysis]: OBSERVE — Trend M15: BULLISH; struktur: MIXED.; Konteks: H1 BULLISH, H4 BULLISH
  fundamental [analysis]: APPROVE — Pemeriksaan selesai.
  market_conditions [analysis]: APPROVE — Pemeriksaan selesai.
  portfolio [preflight]: APPROVE — Pemeriksaan selesai.
  strategy [analysis]: PROPOSE — Pemeriksaan selesai.
  risk [analysis]: APPROVE — Pemeriksaan selesai.
  portfolio [sized]: APPROVE — Pemeriksaan selesai.
KOORDINATOR: APPROVED_RISK
DATA: SYNTHETIC — not market data | 2026-01-15T12:00:00Z
```

Jika units usulan diubah menjadi 1.000.000, risiko/margin melampaui aturan dan
hasilnya REJECTED. Ini bisa dicoba pada salinan `proposed_trade.json`.

## 5. Journal Mode

```bash
python -m forex_agent journal --db data/demo.sqlite3 open --file examples/journal_trade.json
python -m forex_agent journal --db data/demo.sqlite3 close --id demo-001 --net-pnl 180 --closed-at 2026-01-15T14:00:00Z
python -m forex_agent journal --db data/demo.sqlite3 summary --simulated
```

Hasil contoh dari satu trade fiktif:

```json
{
  "mode": "journal",
  "simulated": true,
  "closed_trades": 1,
  "open_trades": 0,
  "net_pnl": 180.0,
  "win_rate": 1.0,
  "profit_factor": null,
  "profit_factor_note": "null jika belum ada kerugian tertutup; bukan bukti profit pasti.",
  "expectancy_r": 1.844550658480964,
  "max_closed_pnl_drawdown": 0.0,
  "by_setup": {
    "TREND_FOLLOWING": {
      "trades": 1,
      "net_pnl": 180.0,
      "sum_r": 1.844550658480964
    }
  },
  "review": "Bandingkan expectancy R per setup, biaya, disiplin SL, dan sampel. Drawdown ini hanya P/L tertutup."
}
```

Sampel satu transaksi tidak cukup untuk menyimpulkan edge strategi. Profit factor
null ketika belum ada kerugian tertutup; tidak ditampilkan sebagai tak terhingga.

## 6. Jalur penolakan lain

- `python -m forex_agent demo --scenario stale`: quote kedaluwarsa → NO_TRADE.
- `python -m forex_agent demo --scenario range`: trend/konfirmasi tidak cukup → NO_TRADE.
- Jalankan analisis signal dua kali memakai snapshot dan database yang sama:
  permintaan kedua → NO_TRADE karena fingerprint sudah diterbitkan.
- Hapus `fundamentals` atau satu timeframe konteks dari salinan snapshot:
  data tidak lengkap → NO_TRADE.

JSON keluaran setiap skenario disertakan di folder `examples/`. Contoh dapat
diregenerasi tanpa API key; file yang dihasilkan hanya mengganti fixture sintetis.
