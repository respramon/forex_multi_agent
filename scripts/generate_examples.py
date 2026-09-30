"""Run from project root: python -m scripts.generate_examples."""

import json
from pathlib import Path
from forex_agent.agent import ForexCoordinator, format_report
from forex_agent.agents import agent_manifest
from forex_agent.demo import make_snapshot
from forex_agent.journal import Journal
from forex_agent.models import utc


def save(path, value):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main():
    snapshot = make_snapshot()
    save("examples/agents_manifest.json", agent_manifest())
    save("examples/synthetic_snapshot.json", snapshot)
    save("examples/calendar.synthetic.json", snapshot["fundamentals"])
    save("examples/metadata.synthetic.json", {k: v for k, v in snapshot.items() if k != "frames"})
    with Journal() as journal:
        agent = ForexCoordinator(journal)
        analyst = agent.analyze(snapshot, mode="analyst")
        signal = agent.analyze(snapshot, mode="signal")
        if signal["status"] != "BUY":
            raise RuntimeError("Fixture trend-following tidak lolos; periksa perubahan logika.")
        proposal = {"side": "BUY", "entry": signal["entry_area"][1], "stop": signal["stop_loss"],
                    "target": signal["take_profit"], "units": signal["risk"]["units"]}
        risk = agent.analyze(snapshot, mode="risk", proposed_trade=proposal)
        if risk["status"] != "APPROVED_RISK":
            raise RuntimeError("Fixture risk manager tidak lolos.")
        save("examples/proposed_trade.json", proposal)
        duplicate = agent.analyze(snapshot, mode="signal")
    with Journal() as journal:
        news = ForexCoordinator(journal).analyze(make_snapshot(scenario="news"), mode="signal")
    with Journal() as journal:
        stale = ForexCoordinator(journal).analyze(make_snapshot(scenario="stale"), mode="signal")
    trade = {"id": "demo-001", "pair": "EUR/USD", "side": "BUY", "opened_at": snapshot["as_of"],
             "units": proposal["units"], "entry": proposal["entry"], "stop": proposal["stop"],
             "target": proposal["target"], "initial_risk": signal["risk"]["estimated_loss"],
             "setup": signal["setup"], "notes": "Contoh sintetis; bukan hasil eksekusi broker.", "simulated": True}
    save("examples/journal_trade.json", trade)
    with Journal() as journal:
        journal.open_trade(trade)
        journal.close_trade("demo-001", 180, utc("2026-01-15T14:00:00Z"))
        summary = journal.summary(True)
    for name, report in (("analyst", analyst), ("signal", signal), ("risk", risk),
                         ("news_no_trade", news), ("stale_no_trade", stale), ("duplicate_no_trade", duplicate), ("journal", summary)):
        save(f"examples/{name}_output.json", report)
    text = """# Simulasi penggunaan multi-agent forex

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
""" + format_report(signal) + "\n```\n"
    text += """
Anggaran maksimum USD 100. Ukuran yang lolos juga dibatasi langkah units dan margin.
Risiko dihitung pada batas entry terburuk, termasuk estimasi biaya. Entry pada harga
berbeda membutuhkan perhitungan ulang. Skor 100 berarti lima pemeriksaan indikator
lolos pada data buatan; skor tersebut bukan probabilitas atau akurasi prediksi.

## 2. Signal Mode — berita penting

```bash
python -m forex_agent demo --scenario news
```

```text
""" + format_report(news) + "\n```\n"
    text += """
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
""" + format_report(risk) + "\n```\n"
    text += """
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
""" + json.dumps(summary, indent=2, ensure_ascii=False) + "\n```\n"
    text += """
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
"""
    Path("docs/SIMULATION.md").write_text(text, encoding="utf-8")
    print("Contoh dan docs/SIMULATION.md berhasil diregenerasi.")


if __name__ == "__main__":
    main()
