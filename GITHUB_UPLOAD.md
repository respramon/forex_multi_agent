# Unggah proyek lengkap ke GitHub

Paket ZIP mengekstrak satu folder `forex_ai_agent`. Folder itu berisi source,
README, panduan, konfigurasi contoh, schema, data sintetis, tests, dan workflow CI.
Jalankan perintah dari dalam folder tersebut dengan Python 3.11 atau lebih baru.

## Periksa sebelum unggah

```bash
python -m forex_agent agents
python -m forex_agent demo
python -m forex_agent demo --scenario news
python -m unittest discover -s tests -v
```

Demo pertama menghasilkan sinyal dari data sintetis; skenario news menampilkan
veto fundamental. Baca `README.md` dan `PANDUAN_PENGGUNAAN.md` untuk konfigurasi data
dan API. Kredensial diisi melalui environment pada komputer pengguna.

## Repository baru

Ekstrak ZIP, buat repository GitHub Anda, lalu unggah **isi folder** `forex_ai_agent`
ke root repository agar `README.md` dan `pyproject.toml` langsung berada di root.
Unggah seluruh subfolder proyek, termasuk konfigurasi workflow CI. Setelah commit,
workflow Python menjalankan pengujian pada Python 3.11, 3.12, dan 3.13.

Jika menggunakan Git, ganti URL contoh dengan repository Anda:

```bash
cd forex_ai_agent
git init -b main
git add .
git commit -m "Add forex multi-agent system"
git remote add origin https://github.com/USERNAME/REPOSITORY.git
git push -u origin main
```

## Memperbarui repository yang sudah ada

Gunakan checkout repository yang sudah ada. Salin isi folder paket ke root checkout,
pertahankan riwayat Git dan kredensial lokal, lalu tinjau `git diff`. Hapus berkas
source lama hanya bila sudah dipastikan tidak digunakan. Commit perubahan sebagai
versi 0.2.0 dan push melalui alur kerja repository Anda.

Paket hanya berisi kode dan fixture sintetis; database jurnal, data akun, environment
pribadi, serta artefak build bukan bagian dari source yang perlu diunggah.
