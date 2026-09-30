# Multi-agent khusus forex

Versi 0.2.0 memisahkan delapan agen spesialis dari `ForexCoordinator`. Agen
mempunyai metode `assess`, input yang sesuai perannya, dan pesan keluaran sendiri.
Koordinator memakai pesan tersebut untuk menentukan keputusan akhir. Mesin
indikator, strategi, dan risiko yang telah diuji tetap dipakai oleh agen pemiliknya.

Metode agen adalah **deterministik berbasis aturan Python**. Narasi model bahasa
bersifat opsional setelah keputusan tim selesai. Semua agen berjalan dalam satu
proses sesuai dependensi; multi-agent tidak membutuhkan delapan model AI atau
delapan proses server. Tim tidak mengirim order broker.

## Agen dan jadwal

| ID | Input utama | Keluaran | Dependensi |
|---|---|---|---|
| `data_validation` | Snapshot dan kebijakan server | AnalysisContext tervalidasi | Tidak ada |
| `technical` | Candle tutup semua timeframe terkait | Observasi indikator dan struktur | Data |
| `fundamental` | Kalender kedua mata uang dan cutoff | Kelayakan kalender, veto berita, konteks sentimen | Data |
| `market_conditions` | Quote dan observasi teknikal | Kelayakan spread, volatilitas, dan harga berjalan | Data, teknikal |
| `portfolio` (preflight) | Akun, jurnal, dan posisi broker | Batas harian, eksposur, rekonsiliasi | Data |
| `strategy` | Observasi teknikal, quote, spesifikasi broker | Proposal setup atau ABSTAIN | Data, teknikal, kondisi pasar |
| `currency_sentiment` | Sentimen base/quote dan arah proposal | APPROVE, ABSTAIN, atau VETO | Fundamental, strategi |
| `risk` | Proposal dan kondisi akun | Units/lot, biaya, margin, RR bersih | Data, teknikal, kondisi pasar, strategi |
| `portfolio` (sized) | State portofolio dan estimasi risiko baru | Persetujuan/veto eksposur setelah sizing | Data, risiko |

PortfolioAgent melakukan dua pemeriksaan dengan fase berbeda, sehingga sinyal
yang lolos dapat mempunyai sembilan penilaian dari **delapan agen**. Pemeriksaan
terakhir memasukkan risiko kandidat ke anggaran portofolio dan setiap mata uang.

## Kontrak pesan

Setiap `AgentAssessment` membawa `agent_id`, `verdict`, `phase`, `depends_on`,
`reasons`, `warnings`, `evidence`, dan `payload` internal. Payload memuat domain
objek seperti candle, akun, atau proposal yang dibutuhkan agen berikutnya.
`payload` tidak disalin ke jejak publik. `agent_reports` hanya menyertakan bukti
yang dipilih agen dan aman untuk bentuk JSON; akun tetap merupakan informasi
privat di laporan pengguna dan tidak dikirim sebagai bukti ke model bahasa.

| Verdict | Makna |
|---|---|
| APPROVE | Pemeriksaan milik agen lolos |
| OBSERVE | Observasi teknikal; tidak mengizinkan transaksi |
| PROPOSE | Kandidat strategi atau usulan pengguna; belum mendapat izin risiko |
| ABSTAIN | Tidak ada kandidat atau tidak ada konfirmasi sentimen yang memadai |
| VETO | Agen menemukan alasan wajib menahan keputusan |
| ERROR | Input, kontrak keluaran, atau pelaksanaan agen gagal |

Koordinator memeriksa identitas agen, verdict yang diizinkan untuk perannya,
kelengkapan payload, dependensi, dan bukti JSON tanpa NaN/Infinity. Persetujuan
risiko harus cocok dengan flag `approved` hasil sizing; persetujuan fundamental
harus cocok dengan veto kalender. Pesan yang tidak dapat digunakan memblokir
keputusan. Input snapshot tidak dapat menonaktifkan agen atau mengganti kebijakan.

## Keputusan akhir

1. Data harus valid sebelum observasi berjalan.
2. Fundamental, kondisi pasar, dan portofolio harus menyetujui sebelum proposal.
3. StrategyAgent harus menghasilkan PROPOSE. ABSTAIN menghasilkan NO_TRADE.
4. Sentimen yang berlawanan kuat memveto proposal. Sentimen tidak lengkap boleh
   ABSTAIN tetapi tidak menambah skor konfirmasi.
5. RiskAgent dan pemeriksaan portofolio setelah sizing harus menyetujui.
6. Koordinator mengklaim fingerprint sinyal secara atomik pada SQLite. Duplikasi,
   kuota harian, cooldown, atau kegagalan jurnal tetap menahan publikasi.

Satu veto wajib cukup untuk menahan transaksi. Tidak ada voting mayoritas yang
dapat mengalahkan veto risiko. NO_TRADE/REJECTED mengosongkan entry, SL, TP, RR,
sizing, arah, dan identitas sinyal. `coordination.vetoed_by` dapat menyebut
`signal_journal` atau `coordinator` untuk penolakan di luar agen spesialis.

## Mode dan antarmuka

| Mode | Agen yang dijalankan | Publikasi sinyal |
|---|---|---|
| Analyst | Data, teknikal, fundamental | Tidak; status ANALYSIS_ONLY |
| Signal | Seluruh tim selama dependensi lolos | BUY/SELL setelah seluruh pemeriksaan dan klaim jurnal |
| Risk | Data, teknikal, fundamental, pasar, portofolio, strategi usulan pengguna, risiko | Tidak; hanya APPROVED_RISK/REJECTED |
| Journal | Perintah pencatatan SQLite | Tidak |

Analyst tetap menyajikan observasi dan alasan veto kalender, tanpa meminta data
akun atau quote. Risk Mode memeriksa geometri dan risiko proposal pengguna tanpa
mengklaim bahwa arah tersebut dikonfirmasi strategi/sentimen. Agen yang dilewati
tercantum pada `coordination.not_run`.

```bash
python -m forex_agent agents
python -m forex_agent agents --json
python -m forex_agent demo --json
python -m forex_agent demo --scenario news --json
python -m forex_agent demo --pair USD/JPY
```

CLI, POST `/v1/analyze`, POST `/v1/risk`, dan replay `--strategy agent` memakai
koordinator yang sama. GET `/v1/agents` menyediakan roster dengan autentikasi API.
Lihat keluaran yang dihasilkan kode di `examples/signal_output.json` dan
`examples/news_no_trade_output.json`.

## Kompatibilitas dan cakupan

`ForexAgent(journal, policy).analyze(...)` tetap tersedia sebagai turunan
`ForexCoordinator`, sehingga pemanggil lama memperoleh tim baru secara otomatis.
Field laporan sebelumnya tetap tersedia; `agent_reports` dan `coordination`
ditambahkan. Kebijakan risiko, jurnal, format snapshot, dan mode replay tetap
memakai sumber yang sama.

Pasangan yang diizinkan: **EUR/USD, GBP/USD, USD/JPY, AUD/USD**. XAU/USD dan instrumen
non-forex ditolak pada batas data, provider, jurnal, instrumen, serta paper orders.
Untuk jurnal lama yang masih memuat logam, gunakan jurnal akun forex yang sesuai
dengan seluruh posisi akun dan jangan menghilangkan posisi broker untuk melewati
rekonsiliasi. Broker dengan posisi di luar cakupan akan menghasilkan penolakan.

Model riset `train`/`predict` tetap menjadi jalur terpisah dan tidak memberi
otorisasi transaksi kepada agen. Pengujian baru ada di `tests/test_multi_agent.py`;
bukti dan batas validasi ada di [VALIDATION.md](VALIDATION.md).
