# 🖼️ RESOLV — Image Resolution Lab

> Atur ulang resolusi gambar lokal, dari **0.25×** sampai **4×**, tanpa kehilangan detail.

RESOLV adalah aplikasi web berbasis Flask yang memungkinkan kamu melakukan **upscaling** gambar menggunakan model AI **Real-ESRGAN (ncnn-vulkan)** dan **downscaling** menggunakan interpolasi presisi tinggi — semua berjalan **100% lokal di mesin Anda**, tanpa server eksternal, tanpa upload ke cloud.

Dibuat untuk **UAS Grafika Komputer** — tema _Teknologi Grafika Komputer pada Aplikasi Industri_ (image super-resolution / pemrosesan citra digital).

---

## ✨ Fitur

- 🔍 **Upscale** hingga 4× menggunakan model neural Real-ESRGAN
- 🔎 **Downscale** cepat dengan interpolasi OpenCV (INTER\_AREA / Lanczos)
- 🎚️ Kontrol resolusi lewat **satu slider** (0.25× — 4.00×)
- 🧠 Pilihan 3 model AI: General, Anime, dan Anime Video
- 🔒 **Privasi terjaga** — semua proses di lokal, tidak ada data yang dikirim ke server manapun
- ⚡ Validasi dimensi otomatis (maks. 2048px) agar tidak hang di GPU biasa
- 🖥️ UI modern dark-mode dengan preview hasil langsung di browser

---

## 📁 Struktur Folder

```
resizer-tool/
├── app.py
├── requirements.txt
├── realesrgan.exe
├── models/
│   ├── realesrgan-x4plus.bin
│   ├── realesrgan-x4plus.param
│   ├── realesrgan-x4plus-anime.bin
│   ├── realesrgan-x4plus-anime.param
│   ├── realesr-animevideov3-x4.bin
│   └── realesr-animevideov3-x4.param
├── templates/
│   └── index.html   ←   Frontend (landing page + tool)
├── uploads/         ←   Otomatis dibuat, tempat file yang diupload
└── outputs/         ←   Otomatis dibuat, tempat hasil proses
```

---

## 🚀 Langkah Setup

### 1. Clone Repository

```bash
git clone https://github.com/angslhn/RESOLV.git
cd RESOLV
```

### 2. Install Dependency Python

```bash
pip install -r requirements.txt
```

Isi `requirements.txt`:

```
flask
opencv-python
```

### 3. Jalankan Aplikasi

```bash
python app.py
```

### 4. Buka di Browser

```
http://localhost:5000
```

---

## ⚙️ Cara Kerja Logic Scale

| Slider | Aksi |
|---|---|
| `0.25× – 0.99×` | Downscale langsung dari gambar asli pakai OpenCV (`INTER_AREA`) |
| `= 1.00×` | Tidak diproses, file asli dikembalikan apa adanya |
| `1.01× – 4.00×` | Upscale menggunakan Real-ESRGAN (ncnn-vulkan) |

### Batas Resolusi Input untuk Upscale: **maks. 2048px**

1. Versi yang sudah dibatasi (≤2048px) dirender native **4×** oleh exe
2. Hasilnya disesuaikan ke skala target yang diminta, dihitung dari **dimensi asli** — jadi dimensi akhir tetap tepat sesuai slider

> ⚠️ Konsekuensi: detail yang direkonstruksi AI berasal dari versi 2048px, bukan resolusi asli yang lebih tinggi. Pengguna akan melihat peringatan di halaman web saat ini terjadi.

---

## 🛠️ Troubleshooting

**`realesrgan.exe tidak ditemukan`**
→ Pastikan file exe ada tepat di root folder (bukan subfolder), namanya persis `realesrgan.exe`

**Model error / gagal load**
→ Pastikan nama file di `models/` persis sama dengan yang dipilih di dropdown
(contoh: `-n realesrgan-x4plus` butuh `realesrgan-x4plus.bin` + `realesrgan-x4plus.param`)

**Proses upscale hang / timeout**
→ Sudah otomatis diatasi dengan pembatasan 2048px dan tile processing (`-t 200`). Jika masih hang:
- Update driver GPU ke versi terbaru
- Turunkan `TILE_SIZE` di `app.py` (misal dari `200` ke `100`)
- Turunkan `MAX_INPUT_DIM` di `app.py` (misal ke `1280`)
- Tes manual dulu di CMD:
  ```bash
  realesrgan.exe -i test.jpg -o out.png -n realesrgan-x4plus -s 4 -t 100 -m models -f png
  ```
  Kalau ini juga hang, masalahnya di GPU/driver, bukan di kode Python.

---

## 👥 Tim Pengembang

| Nama | NIM |
|---|---|
| Aang Solihin | 240160121001 |
| Ilham Septian | 240160121049 |
| Muzayin Jamil | 240160121090 |
| Wisnu Rifki Wijaya | 240160121115 |

Program Studi Informatika — Fakultas Teknologi Informasi — Universitas Sebelas April

---
