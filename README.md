# DataComp — Video Compression Engine

> A full-stack H.264-inspired video compression system.

**Live Demo → [https://vidcomp-2yw4.onrender.com](https://vidcomp-2yw4.onrender.com)**

---

## What it does

DataComp implements a real video compression pipeline — not a wrapper around ffmpeg. It encodes video frame-by-frame using DCT, motion estimation, Huffman entropy coding, and quantization, then reports quality metrics (PSNR, SSIM, compression ratio) alongside a visual comparison of the original vs compressed output.

---

## Project Structure

```
DataComp/
├── backend/
│   ├── app.py              # Flask REST API
│   └── codec_engine.py     # Compression algorithms
├── frontend/
│   ├── index.html          # UI
│   └── static/
│       ├── css/style.css
│       └── js/main.js
├── uploads/                # Auto-created
├── outputs/                # Auto-created
├── requirements.txt
└── render.yaml             # Render deployment config
```

---

## Running Locally

**Requirements:** Python 3.9+

```bash
# Install dependencies
pip install -r requirements.txt

# Start the server
python backend/app.py
```

Open **http://localhost:5000** in your browser.

---

## Encoding Pipeline

```
Video Input
    │
    ▼
Frame Extraction  (OpenCV)
    │
    ▼
GOP Structuring + Scene Change Detection
    │
    ├── I-Frame ──► DCT → Quantize → Zigzag → RLE → Huffman
    │
    └── P-Frame ──► Motion Estimation → Residual DCT → Quantize → Huffman
    │
    ▼
Reconstruct (IDCT + Motion Compensation) → Deblocking Filter
    │
    ▼
PSNR / SSIM Metrics + MP4 Output
```

---

## Algorithms

| Component | Implementation |
|-----------|----------------|
| Spatial Transform | 8×8 DCT via SciPy |
| Quantization | Scaled JPEG luma matrix (QP 1–51) |
| Entropy Coding | Huffman over zigzag-scanned RLE coefficients |
| Motion Estimation | Diamond search + Full search |
| Scene Detection | Normalized frame difference threshold |
| Adaptive QP | Per-macroblock variance-based QP adjustment |
| Rate Control | QP feedback loop targeting bitrate |
| Post-processing | Bilateral deblocking filter |

---

## API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Health check + version |
| GET | `/api/info` | Codec parameter documentation |
| POST | `/api/upload` | Upload video and start encode job |
| GET | `/api/jobs/<id>` | Poll job status and results |
| GET | `/api/jobs` | List all jobs |
| GET | `/api/frame/<id>/<type>` | Get original or compressed frame |
| GET | `/api/download/<id>` | Download compressed video |

### Upload Parameters

| Parameter | Default | Range |
|-----------|---------|-------|
| `qp` | 28 | 1–51 |
| `gop_size` | 12 | 1–60 |
| `block_size` | 16 | 4 / 8 / 16 |
| `search_range` | 16 | 4–64 |
| `entropy_mode` | huffman | huffman / cabac |
| `target_bitrate_kbps` | 2500 | 500–10000 |
| `adaptive_quantization` | true | bool |
| `scene_change_detection` | true | bool |
| `rate_control` | true | bool |
| `deblocking` | true | bool |

---

## Output Metrics

- **Compression Ratio** — original bits / encoded bits
- **PSNR** — Peak Signal-to-Noise Ratio (dB)
- **SSIM** — Structural Similarity Index [0–1]
- **Encoding FPS** — throughput in frames per second
- **Per-frame data** — type, bits, PSNR, SSIM, motion vectors
- **Bitstream composition** — I-frame / P-frame / scene cut breakdown

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.11, Flask, Flask-CORS |
| Video I/O | OpenCV (headless) |
| DSP / Math | NumPy, SciPy |
| Frontend | HTML5, CSS3, Vanilla JS, Canvas API |
| Fonts | Syne, DM Mono, Space Grotesk |
| Deployment | Render (free tier) |

---

## References

- H.264 / MPEG-4 AVC — ISO/IEC 14496-10
- JPEG DCT quantization matrix structure
- Huffman entropy coding — RFC 1951

---

*Built as an academic project demonstrating video compression fundamentals from scratch.*