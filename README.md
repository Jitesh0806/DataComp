# VIDCOMP — Custom Video Compression Codec

> A full-stack H.264-inspired video compression system with a Python backend and a dark, technical web frontend.

---

## 📁 Project Structure

```
vidcomp/
├── backend/
│   ├── app.py              # Flask REST API server
│   └── codec_engine.py     # Core compression algorithms
├── frontend/
│   ├── index.html          # Main UI
│   └── static/
│       ├── css/style.css   # Styling
│       └── js/main.js      # Frontend logic
├── uploads/                # Temp video uploads (auto-created)
├── outputs/                # Encoded outputs (auto-created)
├── requirements.txt        # Python dependencies
└── README.md
```

---

## 🚀 Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

> Requires Python 3.9+ and `ffmpeg` installed on your system.

### 2. Start the Backend

```bash
cd backend
python app.py
```

The server starts at **http://localhost:5000**

### 3. Open the Frontend

Navigate to **http://localhost:5000** in your browser.

The Flask server serves the frontend automatically.

---

## ⚙️ How It Works

### Encoding Pipeline

```
Video Input
    │
    ▼
Frame Extraction (OpenCV)
    │
    ▼
GOP Structuring + Scene Change Detection
    │
    ├─── I-Frame ──► DCT → Quantize → Huffman
    │
    └─── P-Frame ──► Motion Estimation → Residual DCT → Huffman
    │
    ▼
Bitstream Output + Quality Metrics
```

### Algorithms Implemented

| Component | Algorithm |
|-----------|-----------|
| Frame Coding | I-Frame (Intra), P-Frame (Inter) |
| Motion Estimation | Full Search + Hierarchical 3-Level |
| Spatial Transform | 8×8 DCT (via SciPy) |
| Quantization | Scaled JPEG Luma/Chroma Matrix |
| Entropy Coding | Huffman over zigzag-scanned RLE |
| Scene Detection | Histogram difference threshold |
| Adaptive QP | Laplacian variance complexity |
| Rate Control | QP feedback loop |
| Post-processing | Deblocking at 8×8 boundaries |

---

## 📡 REST API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET  | `/api/health` | System health check |
| POST | `/api/upload` | Upload video + start encode job |
| GET  | `/api/jobs/<id>` | Poll job status & results |
| GET  | `/api/jobs` | List all jobs |
| POST | `/api/jobs/<id>/cancel` | Cancel queued job |
| GET  | `/api/formats` | Supported formats & limits |

### Upload Parameters (form-data)

| Parameter | Default | Range | Description |
|-----------|---------|-------|-------------|
| `video` | — | — | Video file (required) |
| `qp` | 28 | 1–51 | Quantization parameter |
| `gop_size` | 12 | 1–60 | Frames per GOP |
| `block_size` | 16 | 4/8/16 | Macroblock size |
| `search_range` | 16 | 4–64 | ME search radius (px) |
| `entropy_mode` | huffman | huffman/rle/cabac/cavlc | Entropy coder |
| `adaptive_quantization` | true | bool | Adaptive QP |
| `scene_change_detection` | true | bool | Auto I-frame on scene cut |
| `rate_control` | true | bool | Bitrate feedback |
| `deblocking` | true | bool | Post-processing filter |
| `target_bitrate_kbps` | 2500 | 500–10000 | Rate control target |

---

## 📊 Output Metrics

- **Compression Ratio** — original / encoded bits
- **PSNR** — Peak Signal-to-Noise Ratio (dB)
- **SSIM** — Structural Similarity Index
- **Encoding FPS** — frames per second throughput
- **Per-frame** — type, QP, bits, PSNR, SSIM, motion vectors
- **Scene changes** — auto-detected transitions

---

## 🛠 Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.11, Flask, Flask-CORS |
| Video I/O | OpenCV (`opencv-python-headless`) |
| DSP / Math | NumPy, SciPy (DCT/IDCT) |
| Frontend | Vanilla HTML5, CSS3, JavaScript |
| Rendering | Canvas 2D API |
| Fonts | Orbitron, Share Tech Mono, Rajdhani |

---

## 📝 Codec Reference

Inspired by:
- **H.264 / MPEG-4 AVC** (ISO/IEC 14496-10)
- **JPEG DCT** quantization matrix structure
- **Huffman entropy coding** (RFC 1951)

---

## 👤 Author

Built as a full-stack academic project demonstrating video compression fundamentals.
