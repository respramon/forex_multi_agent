# Keamanan

Jangan mengirim API key atau rincian akun ke issue publik. Cabut kunci yang bocor
melalui penyedia terkait. Semua secret dibaca dari environment; `.env` diabaikan Git.

Adapter OANDA hanya GET. Modul order/eksekusi tidak disediakan. Token broker sendiri
mungkin tetap mempunyai izin trading di luar aplikasi ini; simpan sebagai secret.
HTTP API membutuhkan bearer token acak minimal 32 karakter. `/health` dan `/ready`
terbuka; `/ready` hanya memeriksa kesiapan database dan tidak mengandung informasi
akun. Body dibatasi 4 MiB, batas 60 request per menit per IP, timeout koneksi 15
detik; tidak ada CORS permisif atau akses path dari request. Journal-open mendukung
`Idempotency-Key`/`client_id` agar retry tidak membuat catatan ganda.

Server HTTP bawaan ditujukan untuk pemakaian lokal/integrasi internal kecil.
Untuk akses jaringan, gunakan reverse proxy TLS, pembatasan jaringan, pengelolaan
secret, monitoring, dan proses review deployment. Paket ini tidak mengklaim server
bawaan sebagai layanan publik yang telah diaudit atau tahan seluruh serangan DoS.

`--explain` mengirim ringkasan pair, status, alasan, risiko, waktu, dan mode simulasi
ke OpenAI. Saldo, ukuran posisi, data jurnal, dan token dikeluarkan dari payload.
Narasi model ditandai belum diverifikasi dan tidak ditulis kembali ke field resmi.
Jangan memasukkan data pribadi ke teks sumber berita/alasan custom.

Cadangkan SQLite dan simpan satu database per akun. File snapshot/report yang ditulis
CLI memakai file sementara, penggantian atomik, dan permission owner-only (`0600`),
tetapi backup tetap harus dienkripsi dan restore-nya diuji. Jangan mereset atau
menghapus jurnal untuk menghindari batas risiko. Catatan manual harus cocok dengan
broker; aplikasi membandingkan tiket dan SL dari snapshot, tetapi belum menerima
update posisi real-time atau merekonsiliasi perubahan yang terjadi setelah snapshot.
