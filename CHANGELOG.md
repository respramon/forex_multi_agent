# Changelog

## 0.2.0 — 30 September 2026

- Delapan agen spesialis forex menghasilkan penilaian terstruktur dan bertukar
  hasil melalui ForexCoordinator.
- Koordinator memakai veto wajib, menolak pesan agen yang tidak valid, serta
  menahan keputusan bila agen atau publikasi jurnal gagal.
- Laporan terminal/JSON menyertakan verdict, bukti, dependensi, fase portofolio,
  sumber veto, agen yang dilewati, dan keputusan akhir.
- CLI `agents` dan API GET `/v1/agents` menyediakan roster tim.
- CLI, API, dan replay memakai koordinator yang sama; ForexAgent tetap menjadi
  antarmuka kompatibel bagi pemanggil lama.
- Cakupan dibatasi ke EUR/USD, GBP/USD, USD/JPY, dan AUD/USD. XAU/USD serta instrumen
  non-forex ditolak.
- Model narasi opsional menerima ringkasan verdict tanpa bukti akun agen dan tidak
  dapat mengganti keputusan.
- Dokumentasi, contoh sintetis, schema, workflow CI, dan pengujian diperbarui.

## 0.1.0

Fondasi analisis forex, indikator, strategi, kontrol risiko, jurnal SQLite, CLI,
API lokal, integrasi baca OANDA, backtest/replay, serta baseline riset ML.
