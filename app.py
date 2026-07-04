import os
import re
import shutil
import subprocess
import time
import uuid
import unicodedata

import cv2
from flask import Flask, jsonify, render_template, request, send_from_directory

# ---------------------------------------------------------------------------
# KONFIGURASI
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")

# Lokasi binary realesrgan-ncnn-vulkan
EXE_CANDIDATES = ["realesrgan.exe", "realesrgan-ncnn-vulkan"]
MODELS_DIR = os.path.join(BASE_DIR, "models")

ALLOWED_EXT = {"png", "jpg", "jpeg", "webp", "bmp"}
MAX_DIMENSION = 2048  # Batas maksimum lebar/tinggi dalam piksel

# Model yang tersedia
MODEL_CHOICES = {
    "realesrgan-x4plus": {
        "label": "RealESRGAN — General",
        "desc": "Model serbaguna. Cocok untuk foto, render produk, aset game/UI.",
    },
    "realesrgan-x4plus-anime": {
        "label": "RealESRGAN — Anime",
        "desc": "Dioptimalkan untuk ilustrasi & line-art bergaya anime/kartun.",
    },
    "realesr-animevideov3-x4": {
        "label": "RealESRGAN — Anime Video",
        "desc": "Versi ringan, dibuat untuk frame video anime, lebih cepat.",
    },
}

NATIVE_SCALE = 4   # Semua model di atas adalah x4
TILE_SIZE    = 0   # 0 = auto; naikkan ke 512/256 jika VRAM < 4 GB
UPSCALE_TIMEOUT = 600  # detik

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------
def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def find_exe() -> str | None:
    for name in EXE_CANDIDATES:
        path = os.path.join(BASE_DIR, name)
        if os.path.isfile(path):
            return path
    return None


def check_dimensions(image_path: str) -> tuple[int, int]:
    """Cek dimensi gambar, raise ValueError jika melebihi MAX_DIMENSION."""
    img = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError("Gagal membaca file gambar.")
    h, w = img.shape[:2]
    if w > MAX_DIMENSION or h > MAX_DIMENSION:
        raise ValueError(
            f"Dimensi gambar terlalu besar ({w}×{h}px). "
            f"Maksimum yang diizinkan adalah {MAX_DIMENSION}×{MAX_DIMENSION}px."
        )
    return h, w


def sanitize_filename(filename: str) -> str:
    """
    Membersihkan nama file:
    - Menghapus karakter khusus dan aneh
    - Mengganti spasi dan karakter non-alphanumeric dengan underscore
    - Menghapus multiple underscore
    - Mengubah ke lowercase
    - Menghapus leading/trailing underscore
    
    Contoh:
    "Mamat Ganteng 123.png" -> "mamat_ganteng_123.png"
    "Foto!@#Liburan (1).jpg" -> "foto_liburan_1.jpg"
    "Héllo Wörld™.png" -> "hello_world.png"
    """
    # Pisahkan nama file dan ekstensi
    name, ext = os.path.splitext(filename)
    
    # Normalisasi karakter unicode (é -> e, ü -> u, dll)
    name = unicodedata.normalize('NFKD', name)
    name = name.encode('ascii', 'ignore').decode('ascii')
    
    # Ganti semua karakter non-alphanumeric (kecuali underscore dan strip) dengan spasi
    name = re.sub(r'[^\w\s-]', ' ', name)
    
    # Ganti spasi dan strip dengan underscore
    name = re.sub(r'[\s-]+', '_', name)
    
    # Hapus multiple underscore
    name = re.sub(r'_+', '_', name)
    
    # Ubah ke lowercase
    name = name.lower()
    
    # Hapus leading/trailing underscore
    name = name.strip('_')
    
    # Jika nama kosong setelah dibersihkan, gunakan default
    if not name:
        name = "image"
    
    return f"{name}{ext}"


def generate_output_filename(original_filename: str, scale: float, mode: str = "upscale") -> str:
    """
    Generate nama file output berdasarkan nama file asli.
    
    Args:
        original_filename: Nama file asli (contoh: "Mamat Ganteng 123.png")
        scale: Faktor scale (contoh: 2.0, 0.5)
        mode: Mode operasi ("upscale", "downscale", "noop")
    
    Returns:
        Nama file output (contoh: "mamat_ganteng_123_upscaled_2x.png")
    """
    # Bersihkan nama file
    clean_name = sanitize_filename(original_filename)
    name, ext = os.path.splitext(clean_name)
    
    # Buat suffix berdasarkan mode dan scale
    if mode == "noop":
        suffix = "_original"
    elif mode == "downscale":
        # Untuk downscale, tampilkan scale sebagai desimal (0.5, 0.25)
        scale_str = str(scale).replace('.', '_')
        suffix = f"_downscaled_{scale_str}x"
    else:  # upscale
        # Untuk upscale, tampilkan scale (2x, 3x, 4x)
        if scale == int(scale):
            scale_str = f"{int(scale)}x"
        else:
            scale_str = f"{scale}x"
        suffix = f"_upscaled_{scale_str}"
    
    # Generate nama akhir
    final_name = f"{name}{suffix}.png"  # Selalu PNG untuk output
    
    return final_name


def run_upscale(input_path: str, output_path: str, model: str, target_scale: float) -> None:
    """
    Upscale dengan realesrgan-ncnn-vulkan.

    Strategi yang benar:
    ─────────────────────────────────────────────────────────────────────────
    1.  Selalu jalankan realesrgan dengan -s 4 (native scale model x4).
        Jangan pernah pakai -s 1 / -s 2 / -s 3 pada model x4 — hasilnya
        tile artifacts karena padding antar tile tidak match.
    2.  Gunakan -t 0 (auto tile) agar library yang tentukan ukuran tile
        yang aman. Kalau VRAM < 4 GB, ganti TILE_SIZE = 512 di atas.
    3.  Setelah realesrgan selesai (output selalu 4× dari input), resize
        hasil ke dimensi target yang sebenarnya memakai OpenCV.
    ─────────────────────────────────────────────────────────────────────────
    """
    exe = find_exe()
    if exe is None:
        raise FileNotFoundError(
            "realesrgan.exe tidak ditemukan. "
            "Taruh file itu sejajar dengan app.py."
        )

    # Dimensi asli
    img_original = cv2.imread(input_path, cv2.IMREAD_UNCHANGED)
    if img_original is None:
        raise ValueError("Gagal membaca gambar input.")

    original_h, original_w = img_original.shape[:2]

    # Dimensi target akhir
    target_w = max(1, round(original_w * target_scale))
    target_h = max(1, round(original_h * target_scale))

    # File sementara untuk output realesrgan (selalu 4×)
    temp_output = os.path.join(OUTPUT_DIR, f"temp_{uuid.uuid4().hex[:10]}.png")

    cmd = [
        exe,
        "-i", input_path,
        "-o", temp_output,
        "-n", model,
        "-s", str(NATIVE_SCALE),   # ← SELALU 4; bukan target_scale
        "-m", MODELS_DIR,
        "-t", str(TILE_SIZE),      # ← 0 = auto (aman untuk semua GPU)
        "-f", "png",
    ]

    print(f"CMD : {' '.join(cmd)}")
    print(f"Goal: {original_w}×{original_h} → realesrgan 4× → resize ke {target_w}×{target_h}")

    try:
        result = subprocess.run(
            cmd,
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=UPSCALE_TIMEOUT,
        )
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)
        print("RC    :", result.returncode)
    except subprocess.TimeoutExpired:
        if os.path.exists(temp_output):
            os.remove(temp_output)
        raise RuntimeError(f"realesrgan tidak merespons dalam {UPSCALE_TIMEOUT} detik.")

    if result.returncode != 0:
        if os.path.exists(temp_output):
            os.remove(temp_output)
        raise RuntimeError(f"realesrgan gagal (code {result.returncode}): {result.stderr}")

    # Baca hasil 4× dari realesrgan
    img_4x = cv2.imread(temp_output, cv2.IMREAD_UNCHANGED)
    if img_4x is None:
        if os.path.exists(temp_output):
            os.remove(temp_output)
        raise RuntimeError("Gagal membaca hasil upscale dari realesrgan.")

    h4, w4 = img_4x.shape[:2]
    print(f"Hasil realesrgan: {w4}×{h4}")

    # Resize ke dimensi target jika perlu
    if w4 != target_w or h4 != target_h:
        # Memperkecil dari 4× → pakai INTER_AREA (kualitas terbaik untuk downscale)
        # Memperbesar dari 4× → jarang terjadi, tapi pakai INTER_LANCZOS4
        interp = cv2.INTER_AREA if (target_w <= w4 and target_h <= h4) else cv2.INTER_LANCZOS4
        img_final = cv2.resize(img_4x, (target_w, target_h), interpolation=interp)
        cv2.imwrite(output_path, img_final)
        print(f"Resize selesai → {target_w}×{target_h}")
    else:
        shutil.copy2(temp_output, output_path)
        print("Dimensi sudah pas, langsung copy.")

    # Bersihkan temp
    if os.path.exists(temp_output):
        os.remove(temp_output)


def downscale(input_path: str, output_path: str, target_scale: float) -> None:
    """Downscale langsung dari gambar asli pakai interpolasi Area (tanpa AI)."""
    img = cv2.imread(input_path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError("Gagal membaca gambar.")
    h, w = img.shape[:2]
    new_w = max(1, round(w * target_scale))
    new_h = max(1, round(h * target_scale))
    print(f"Downscale: {w}×{h} → {new_w}×{new_h}")
    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
    cv2.imwrite(output_path, resized)


# ---------------------------------------------------------------------------
# ROUTES
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html", models=MODEL_CHOICES)


@app.route("/api/process", methods=["POST"])
def process():
    if "image" not in request.files:
        return jsonify({"error": "Tidak ada file gambar yang dikirim."}), 400

    file = request.files["image"]
    if file.filename == "" or not allowed_file(file.filename):
        return jsonify({"error": "Format file tidak didukung."}), 400

    # Simpan original filename untuk generate nama output
    original_filename = file.filename
    print(f"Original filename: {original_filename}")

    try:
        scale = float(request.form.get("scale", "1"))
    except ValueError:
        return jsonify({"error": "Nilai scale tidak valid."}), 400

    if scale < 0.25 or scale > 4.0:
        return jsonify({"error": "Scale harus antara 0.25 dan 4.0."}), 400

    model = request.form.get("model", "realesrgan-x4plus")
    if model not in MODEL_CHOICES:
        return jsonify({"error": "Model tidak dikenali."}), 400

    job_id = uuid.uuid4().hex[:10]
    ext = file.filename.rsplit(".", 1)[1].lower()
    input_path = os.path.join(UPLOAD_DIR, f"{job_id}_in.{ext}")

    file.save(input_path)
    print(f"File disimpan: {input_path} ({os.path.getsize(input_path)} bytes)")

    if not os.path.exists(input_path) or os.path.getsize(input_path) == 0:
        return jsonify({"error": "Gagal menyimpan file."}), 500

    # Cek dimensi
    try:
        in_h, in_w = check_dimensions(input_path)
        print(f"Dimensi input: {in_w}×{in_h}")
    except ValueError as e:
        if os.path.exists(input_path):
            os.remove(input_path)
        return jsonify({"error": str(e)}), 400

    # Tentukan mode operasi
    if abs(scale - 1.0) < 1e-9:
        mode = "noop"
    elif scale < 1.0:
        mode = "downscale"
    else:
        mode = "upscale"

    # Generate nama file output yang bersih
    output_filename = generate_output_filename(original_filename, scale, mode)
    output_path = os.path.join(OUTPUT_DIR, output_filename)
    
    print(f"Mode: {mode}")
    print(f"Output filename: {output_filename}")

    started = time.time()

    try:
        if mode == "noop":
            shutil.copy2(input_path, output_path)
            print("Noop — file disalin tanpa perubahan.")

        elif mode == "downscale":
            downscale(input_path, output_path, scale)

        else:  # upscale
            run_upscale(input_path, output_path, model, scale)

    except Exception as exc:
        print(f"ERROR: {exc}")
        if os.path.exists(output_path):
            os.remove(output_path)
        return jsonify({"error": str(exc)}), 500

    elapsed = round(time.time() - started, 2)

    # Baca dimensi output
    out_w, out_h = 0, 0
    try:
        img_out = cv2.imread(output_path, cv2.IMREAD_UNCHANGED)
        if img_out is not None:
            out_h, out_w = img_out.shape[:2]
            print(f"Dimensi output: {out_w}×{out_h}")
        else:
            print("WARN: Gagal membaca output image!")
    except Exception as e:
        print(f"Error membaca output: {e}")

    # Bersihkan input
    try:
        if os.path.exists(input_path):
            os.remove(input_path)
    except Exception:
        pass

    return jsonify(
        {
            "ok": True,
            "mode": mode,
            "scale": scale,
            "model": model if mode == "upscale" else None,
            "elapsed": elapsed,
            "input_dim": {"w": in_w, "h": in_h},
            "output_dim": {"w": out_w, "h": out_h},
            "output_url": f"/outputs/{output_filename}",
            "output_filename": output_filename,
        }
    )


@app.route("/outputs/<path:filename>")
def serve_output(filename):
    return send_from_directory(OUTPUT_DIR, filename)


if __name__ == "__main__":
    if find_exe() is None:
        print("=" * 60)
        print(" PERINGATAN: realesrgan.exe belum ditemukan di folder ini.")
        print(" Mode upscale (scale > 1) tidak akan berfungsi sampai")
        print(" file itu ditaruh sejajar dengan app.py.")
        print("=" * 60)
    app.run(debug=True, port=5000)