# HTTP API lokal

Jalankan `python -m forex_agent serve`. Token `FOREX_API_TOKEN` wajib minimal 32
karakter. Default bind 127.0.0.1:8000. Kebijakan risiko ditentukan server melalui
`--policy`, bukan melalui request. Tidak ada endpoint untuk mengubah kebijakan atau
mengirim order broker. Server standard library cocok untuk integrasi lokal/internal
kecil; paket ini belum mencakup hardening layanan publik.

| Method dan path | Input | Output |
|---|---|---|
| GET `/health` | Tanpa auth | status dan execution_enabled=false |
| GET `/ready` | Tanpa auth | pemeriksaan database dan status kesiapan |
| GET `/v1/agents` | Auth | Delapan agen, peran, dependensi, metode, dan pasangan forex |
| POST `/v1/analyze` | snapshot, timeframe, mode analyst/signal | Laporan resmi |
| POST `/v1/risk` | snapshot, timeframe, proposed_trade | Laporan risiko |
| POST `/v1/journal/open` | Record trade (lihat examples/journal_trade.json) | trade_id |
| POST `/v1/journal/close` | trade_id, net_pnl, closed_at | status closed |
| POST `/v1/journal/link` | trade_id, broker_trade_id (jurnal nyata lama) | status linked |
| POST `/v1/journal/amend` | trade_id, units, entry, stop, target, initial_risk | status amended |
| GET `/v1/journal?simulated=true` | Auth; query opsional | Ringkasan jurnal simulasi |

`/v1/analyze` dan `/v1/risk` memakai koordinator multi-agent yang sama dengan CLI
dan replay. Laporan menambahkan `agent_reports` (agen, fase, verdict, dependensi,
alasan, bukti) dan `coordination` (agen yang memveto/tidak dijalankan, status akhir,
status publikasi). `/v1/agents` mengembalikan roster tetap; request tidak dapat
menonaktifkan agen wajib atau mengganti kebijakan veto. Detail ada di
[MULTI_AGENT.md](MULTI_AGENT.md).

Semua request POST memakai `Content-Type: application/json`. Batas body 4 MiB,
60 request/menit/IP, timeout koneksi 15 detik. Tidak ada CORS terbuka. HTTP 400 untuk
body/input tidak valid, 401 tanpa token, 404 endpoint tidak dikenal, 413 body melebihi
batas, 415 tipe body tidak sesuai, 429 kuota. Keputusan NO_TRADE/REJECTED memakai HTTP
200 karena merupakan hasil bisnis yang valid, bukan kegagalan HTTP. Parameter query
`simulated` harus tepat satu nilai `true` atau `false`.

Untuk `POST /v1/journal/open`, kirim `Idempotency-Key` atau field JSON `client_id`.
Pengulangan dengan key dan payload yang sama mengembalikan trade yang sama; payload
berbeda dengan key yang sudah dipakai menghasilkan HTTP 409.

## Contoh request Python tanpa dependency

Pastikan server dan token sudah disiapkan, lalu jalankan dari root proyek:

```python
import json
import os
import urllib.request
from pathlib import Path

snapshot = json.loads(Path("examples/synthetic_snapshot.json").read_text())
body = {"snapshot": snapshot, "timeframe": "M15", "mode": "signal"}
request = urllib.request.Request(
    "http://127.0.0.1:8000/v1/analyze",
    data=json.dumps(body).encode(),
    headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + os.environ["FOREX_API_TOKEN"],
    },
)
with urllib.request.urlopen(request, timeout=20) as response:
    print(json.dumps(json.load(response), indent=2))
```

Mengulang request signal yang sama ke DB server yang sama menghasilkan NO_TRADE.
Untuk membaca ulang observasi, gunakan mode analyst. Server tidak membaca path
lokal dari body: kirim object snapshot, bukan nama file atau URL untuk di-fetch.

`proposed_trade` pada `/v1/risk`:

```json
{"side":"BUY","entry":1.10147,"stop":1.10044,"target":1.10370,"units":90000}
```

Nilai contoh hanya untuk snapshot sintetis yang disertakan. `units` dapat dihilangkan
untuk menghitung ukuran otomatis. Request risiko tidak menerbitkan sinyal dan tidak
menilai semua syarat strategi. `risk_evaluation` dapat muncul ketika usulan ditolak
untuk menjelaskan besaran yang melampaui batas.

## Persistensi

Transaksi nyata baru perlu `broker_trade_id` pada `/v1/journal/open`. Snapshot
nyata untuk `/v1/analyze` dan `/v1/risk` perlu `broker_open_trades` yang cocok
dengan jurnal. Default DB `data/journal.sqlite3`. Gunakan satu proses kebijakan konsisten dan satu
DB per akun. Semua koneksi menggunakan transaksi SQLite. Identitas pengguna/API key
multi-tenant, sinkronisasi tiket broker otomatis, TLS terminator dan observability
operasional belum termasuk. Lihat [SECURITY.md](../SECURITY.md) untuk batas deployment.
