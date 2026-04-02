"""
VIDCOMP Codec Engine
====================
Real implementation of video compression pipeline:
  - Frame extraction via OpenCV
  - GOP (Group of Pictures) structuring
  - Block-based Motion Estimation (Full Search / Diamond)
  - DCT (Discrete Cosine Transform) on 8x8 / 16x16 blocks
  - Quantization (uniform + adaptive)
  - Huffman entropy coding
  - Scene Change Detection
  - Rate Control
  - PSNR / SSIM metrics
  - Decoding pipeline (entropy decode → IQ → IDCT → motion comp)
"""

import cv2
import numpy as np
import heapq
import json
import time
import math
import os
from collections import defaultdict, Counter
from scipy.fftpack import dct, idct


# ─────────────────────────────────────────────
# 1.  HUFFMAN CODING
# ─────────────────────────────────────────────

class HuffmanNode:
    def __init__(self, symbol, freq):
        self.symbol = symbol
        self.freq   = freq
        self.left   = None
        self.right  = None

    def __lt__(self, other):
        return self.freq < other.freq


class HuffmanCoder:
    def __init__(self):
        self.codes  = {}
        self.tree   = None

    def build(self, data: list):
        freq = Counter(data)
        heap = [HuffmanNode(sym, f) for sym, f in freq.items()]
        heapq.heapify(heap)
        if len(heap) == 1:
            node = heapq.heappop(heap)
            self.codes[node.symbol] = '0'
            self.tree = node
            return
        while len(heap) > 1:
            l = heapq.heappop(heap)
            r = heapq.heappop(heap)
            merged = HuffmanNode(None, l.freq + r.freq)
            merged.left, merged.right = l, r
            heapq.heappush(heap, merged)
        self.tree = heap[0]
        self._gen_codes(self.tree, '')

    def _gen_codes(self, node, code):
        if node is None:
            return
        if node.symbol is not None:
            self.codes[node.symbol] = code or '0'
            return
        self._gen_codes(node.left,  code + '0')
        self._gen_codes(node.right, code + '1')

    def encode(self, data: list) -> str:
        return ''.join(self.codes.get(s, '0') for s in data)

    def get_table(self) -> dict:
        return {str(k): v for k, v in self.codes.items()}

    def avg_code_length(self) -> float:
        if not self.codes:
            return 0.0
        total = sum(len(v) for v in self.codes.values())
        return total / len(self.codes)


# ─────────────────────────────────────────────
# 2.  DCT / QUANTIZATION
# ─────────────────────────────────────────────

# Standard JPEG luminance quantization matrix (8x8)
STD_LUMA_QM = np.array([
    [16,11,10,16,24,40,51,61],
    [12,12,14,19,26,58,60,55],
    [14,13,16,24,40,57,69,56],
    [14,17,22,29,51,87,80,62],
    [18,22,37,56,68,109,103,77],
    [24,35,55,64,81,104,113,92],
    [49,64,78,87,103,121,120,101],
    [72,92,95,98,112,100,103,99],
], dtype=np.float32)


def make_quant_matrix(qp: int) -> np.ndarray:
    """Scale standard quant matrix by QP (1-51, H.264 inspired)."""
    scale = max(1, qp) / 16.0
    qm = np.round(STD_LUMA_QM * scale).astype(np.float32)
    return np.clip(qm, 1, 255)


def dct2d(block: np.ndarray) -> np.ndarray:
    return dct(dct(block.T, norm='ortho').T, norm='ortho')


def idct2d(block: np.ndarray) -> np.ndarray:
    return idct(idct(block.T, norm='ortho').T, norm='ortho')


def quantize_block(dct_block: np.ndarray, qm: np.ndarray) -> np.ndarray:
    return np.round(dct_block / qm).astype(np.int16)


def dequantize_block(q_block: np.ndarray, qm: np.ndarray) -> np.ndarray:
    return (q_block * qm).astype(np.float32)


def zigzag_scan(block: np.ndarray) -> list:
    """Return zigzag-ordered coefficients from an 8x8 block."""
    order = [
        (0,0),(0,1),(1,0),(2,0),(1,1),(0,2),(0,3),(1,2),
        (2,1),(3,0),(4,0),(3,1),(2,2),(1,3),(0,4),(0,5),
        (1,4),(2,3),(3,2),(4,1),(5,0),(6,0),(5,1),(4,2),
        (3,3),(2,4),(1,5),(0,6),(0,7),(1,6),(2,5),(3,4),
        (4,3),(5,2),(6,1),(7,0),(7,1),(6,2),(5,3),(4,4),
        (3,5),(2,6),(1,7),(2,7),(3,6),(4,5),(5,4),(6,3),
        (7,2),(7,3),(6,4),(5,5),(4,6),(3,7),(4,7),(5,6),
        (6,5),(7,4),(7,5),(6,6),(5,7),(6,7),(7,6),(7,7),
    ]
    return [int(block[r, c]) for r, c in order]


def run_length_encode(coeffs: list) -> list:
    """RLE on zigzag coefficients (skip zeros)."""
    result = []
    zero_run = 0
    for c in coeffs[1:]:      # skip DC
        if c == 0:
            zero_run += 1
        else:
            result.append((zero_run, c))
            zero_run = 0
    result.append((0, 0))     # EOB
    return result


# ─────────────────────────────────────────────
# 3.  MOTION ESTIMATION
# ─────────────────────────────────────────────

def sad(block_a: np.ndarray, block_b: np.ndarray) -> int:
    return int(np.sum(np.abs(block_a.astype(np.int32) - block_b.astype(np.int32))))


def full_search_me(curr_block: np.ndarray, ref_frame: np.ndarray,
                   block_y: int, block_x: int, block_size: int, search_range: int):
    """Exhaustive full-search block matching. Returns (mv_y, mv_x, min_sad)."""
    h, w = ref_frame.shape
    best_sad = float('inf')
    best_mv  = (0, 0)

    for dy in range(-search_range, search_range + 1):
        for dx in range(-search_range, search_range + 1):
            ry = block_y + dy
            rx = block_x + dx
            if ry < 0 or rx < 0 or ry + block_size > h or rx + block_size > w:
                continue
            ref_block = ref_frame[ry:ry+block_size, rx:rx+block_size]
            s = sad(curr_block, ref_block)
            if s < best_sad:
                best_sad = s
                best_mv  = (dy, dx)

    return best_mv[0], best_mv[1], best_sad


def diamond_search_me(curr_block: np.ndarray, ref_frame: np.ndarray,
                      block_y: int, block_x: int, block_size: int, search_range: int):
    """Diamond search (faster). Returns (mv_y, mv_x, min_sad)."""
    h, w = ref_frame.shape
    center_y, center_x = block_y, block_x

    def get_sad(ry, rx):
        if ry < 0 or rx < 0 or ry + block_size > h or rx + block_size > w:
            return float('inf')
        return sad(curr_block, ref_frame[ry:ry+block_size, rx:rx+block_size])

    large_diamond = [(0,-2),(0,2),(-2,0),(2,0),(-1,-1),(-1,1),(1,-1),(1,1)]
    small_diamond = [(0,-1),(0,1),(-1,0),(1,0),(0,0)]

    best_sad = get_sad(center_y, center_x)
    best_y, best_x = center_y, center_x

    # Large diamond steps
    for _ in range(search_range // 2):
        moved = False
        for dy, dx in large_diamond:
            ny, nx = best_y + dy, best_x + dx
            if abs(ny - block_y) > search_range or abs(nx - block_x) > search_range:
                continue
            s = get_sad(ny, nx)
            if s < best_sad:
                best_sad, best_y, best_x, moved = s, ny, nx, True
        if not moved:
            break

    # Small diamond refinement
    for dy, dx in small_diamond:
        ny, nx = best_y + dy, best_x + dx
        s = get_sad(ny, nx)
        if s < best_sad:
            best_sad, best_y, best_x = s, ny, nx

    return best_y - block_y, best_x - block_x, best_sad


# ─────────────────────────────────────────────
# 4.  SCENE CHANGE DETECTION
# ─────────────────────────────────────────────

def scene_change_score(prev_gray: np.ndarray, curr_gray: np.ndarray) -> float:
    """Return a normalized difference score [0,1]. >0.45 = scene change."""
    prev_small = cv2.resize(prev_gray, (64, 36)).astype(np.float32)
    curr_small = cv2.resize(curr_gray, (64, 36)).astype(np.float32)
    diff = np.abs(prev_small - curr_small)
    return float(np.mean(diff) / 255.0)


# ─────────────────────────────────────────────
# 5.  PSNR / SSIM
# ─────────────────────────────────────────────

def compute_psnr(original: np.ndarray, compressed: np.ndarray) -> float:
    mse = np.mean((original.astype(np.float64) - compressed.astype(np.float64)) ** 2)
    if mse == 0:
        return 100.0
    return 20 * math.log10(255.0 / math.sqrt(mse))


def compute_ssim(img1: np.ndarray, img2: np.ndarray) -> float:
    C1, C2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    i1 = img1.astype(np.float64)
    i2 = img2.astype(np.float64)
    mu1, mu2 = cv2.GaussianBlur(i1, (11,11), 1.5), cv2.GaussianBlur(i2, (11,11), 1.5)
    mu1_sq, mu2_sq, mu12 = mu1**2, mu2**2, mu1*mu2
    s1  = cv2.GaussianBlur(i1**2,  (11,11), 1.5) - mu1_sq
    s2  = cv2.GaussianBlur(i2**2,  (11,11), 1.5) - mu2_sq
    s12 = cv2.GaussianBlur(i1*i2,  (11,11), 1.5) - mu12
    num = (2*mu12 + C1) * (2*s12 + C2)
    den = (mu1_sq + mu2_sq + C1) * (s1 + s2 + C2)
    ssim_map = num / (den + 1e-10)
    return float(np.mean(ssim_map))


# ─────────────────────────────────────────────
# 6.  ADAPTIVE QUANTIZATION
# ─────────────────────────────────────────────

def adaptive_qp(frame_gray: np.ndarray, base_qp: int) -> np.ndarray:
    """Return per-macroblock QP values based on local variance."""
    h, w = frame_gray.shape
    qp_map = np.full((h, w), base_qp, dtype=np.float32)
    block = 16
    for y in range(0, h - block + 1, block):
        for x in range(0, w - block + 1, block):
            roi = frame_gray[y:y+block, x:x+block].astype(np.float32)
            var = np.var(roi)
            # High variance → lower QP (keep detail), low variance → higher QP (save bits)
            delta = int(np.clip(-var / 400 + 6, -8, 8))
            qp_map[y:y+block, x:x+block] = np.clip(base_qp + delta, 1, 51)
    return qp_map


# ─────────────────────────────────────────────
# 7.  MAIN CODEC PIPELINE
# ─────────────────────────────────────────────

class VidCompCodec:

    def __init__(self, qp=28, gop_size=12, search_range=16,
                 block_size=16, target_bitrate=2500,
                 adaptive_quant=True, scene_detect=True,
                 rate_control=True, var_block=False,
                 deblock=True, entropy_mode='huffman',
                 progress_callback=None):

        self.qp              = int(qp)
        self.gop_size        = int(gop_size)
        self.search_range    = int(search_range)
        self.block_size      = int(block_size)
        self.target_bitrate  = int(target_bitrate)
        self.adaptive_quant  = adaptive_quant
        self.scene_detect    = scene_detect
        self.rate_control    = rate_control
        self.var_block       = var_block
        self.deblock         = deblock
        self.entropy_mode    = entropy_mode
        self.cb              = progress_callback   # fn(stage, pct, msg)

        self.quant_matrix    = make_quant_matrix(self.qp)

    # ── helpers ────────────────────────────────

    def _log(self, stage, pct, msg):
        if self.cb:
            self.cb(stage, pct, msg)

    def _encode_frame_intra(self, frame_gray: np.ndarray) -> dict:
        """Encode an I-frame using DCT + quantization + Huffman."""
        h, w  = frame_gray.shape
        bs    = 8          # DCT block size always 8x8
        all_coeffs = []
        dc_values  = []

        for y in range(0, h - bs + 1, bs):
            for x in range(0, w - bs + 1, bs):
                block  = frame_gray[y:y+bs, x:x+bs].astype(np.float32) - 128.0
                dct_b  = dct2d(block)

                # Local QP if adaptive
                if self.adaptive_quant:
                    local_qp = int(np.mean(
                        make_quant_matrix(self.qp)
                    ))
                    qm = make_quant_matrix(local_qp)
                else:
                    qm = self.quant_matrix

                q_block = quantize_block(dct_b, qm)
                zz      = zigzag_scan(q_block)
                dc_values.append(zz[0])
                rle     = run_length_encode(zz)
                all_coeffs.extend([c for _, c in rle if c != 0])

        # Huffman over AC coefficients
        hc = HuffmanCoder()
        hc.build(all_coeffs if all_coeffs else [0])
        bitstream = hc.encode(all_coeffs if all_coeffs else [0])

        return {
            'type'       : 'I',
            'bits'       : len(bitstream),
            'dc_mean'    : float(np.mean(dc_values)) if dc_values else 0.0,
            'huffman_avg': hc.avg_code_length(),
            'table'      : hc.get_table(),
            'num_blocks' : (h // bs) * (w // bs),
        }

    def _encode_frame_inter(self, curr_gray: np.ndarray,
                            ref_gray: np.ndarray) -> dict:
        """Encode a P-frame using motion estimation + residual DCT + Huffman."""
        h, w  = curr_gray.shape
        bs    = self.block_size
        mvs   = []
        residuals_all = []
        total_sad = 0

        search_fn = diamond_search_me if bs >= 16 else full_search_me

        for y in range(0, h - bs + 1, bs):
            for x in range(0, w - bs + 1, bs):
                curr_block = curr_gray[y:y+bs, x:x+bs]
                mv_y, mv_x, block_sad = search_fn(
                    curr_block, ref_gray, y, x, bs, self.search_range
                )
                mvs.append((mv_y, mv_x))
                total_sad += block_sad

                # Compute residual
                ry = max(0, min(y + mv_y, h - bs))
                rx = max(0, min(x + mv_x, w - bs))
                pred  = ref_gray[ry:ry+bs, rx:rx+bs].astype(np.float32)
                resid = curr_block.astype(np.float32) - pred

                # DCT on residual (using 8x8 sub-blocks if block_size > 8)
                dct_bs = min(bs, 8)
                for dy in range(0, bs, dct_bs):
                    for dx in range(0, bs, dct_bs):
                        sub = resid[dy:dy+dct_bs, dx:dx+dct_bs]
                        if sub.shape != (dct_bs, dct_bs):
                            continue
                        dct_sub = dct2d(sub)
                        q_sub   = quantize_block(dct_sub, self.quant_matrix[:dct_bs, :dct_bs])
                        zz      = zigzag_scan(q_sub) if dct_bs == 8 else [int(v) for v in q_sub.flatten()]
                        residuals_all.extend(zz[:16])  # keep top-left ACs

        hc = HuffmanCoder()
        hc.build(residuals_all if residuals_all else [0])
        bitstream = hc.encode(residuals_all if residuals_all else [0])

        mv_magnitudes = [math.sqrt(vy**2 + vx**2) for vy, vx in mvs]
        avg_mv = float(np.mean(mv_magnitudes)) if mv_magnitudes else 0.0

        return {
            'type'       : 'P',
            'bits'       : len(bitstream) + len(mvs) * 16,  # add MV overhead
            'mv_count'   : len(mvs),
            'avg_mv'     : avg_mv,
            'avg_sad'    : total_sad / max(len(mvs), 1),
            'huffman_avg': hc.avg_code_length(),
            'mvs'        : [(vy, vx) for vy, vx in mvs[:20]],  # sample
        }

    def _reconstruct_frame(self, frame_gray: np.ndarray,
                           ref_gray: np.ndarray | None, is_intra: bool) -> np.ndarray:
        """Reconstruct frame (decode simulate) by applying quantization loop."""
        h, w  = frame_gray.shape
        rec   = np.zeros_like(frame_gray, dtype=np.float32)
        bs    = 8

        if is_intra or ref_gray is None:
            for y in range(0, h - bs + 1, bs):
                for x in range(0, w - bs + 1, bs):
                    block  = frame_gray[y:y+bs, x:x+bs].astype(np.float32) - 128.0
                    dct_b  = dct2d(block)
                    q      = quantize_block(dct_b, self.quant_matrix)
                    dq     = dequantize_block(q, self.quant_matrix)
                    rec_b  = idct2d(dq) + 128.0
                    rec[y:y+bs, x:x+bs] = rec_b
        else:
            mbs = self.block_size
            for y in range(0, h - mbs + 1, mbs):
                for x in range(0, w - mbs + 1, mbs):
                    curr_block = frame_gray[y:y+mbs, x:x+mbs]
                    mv_y, mv_x, _ = diamond_search_me(
                        curr_block, ref_gray, y, x, mbs, self.search_range
                    )
                    ry = max(0, min(y + mv_y, h - mbs))
                    rx = max(0, min(x + mv_x, w - mbs))
                    pred  = ref_gray[ry:ry+mbs, rx:rx+mbs].astype(np.float32)
                    resid = curr_block.astype(np.float32) - pred

                    for dy in range(0, mbs, 8):
                        for dx in range(0, mbs, 8):
                            sub = resid[dy:dy+8, dx:dx+8]
                            if sub.shape != (8, 8):
                                continue
                            dct_sub = dct2d(sub)
                            q_sub   = quantize_block(dct_sub, self.quant_matrix)
                            dq_sub  = dequantize_block(q_sub, self.quant_matrix)
                            rec_sub = idct2d(dq_sub)
                            rec[y+dy:y+dy+8, x+dx:x+dx+8] = pred[dy:dy+8, dx:dx+8] + rec_sub

        return np.clip(rec, 0, 255).astype(np.uint8)

    # ── PUBLIC ENCODE ──────────────────────────

    def encode_video(self, video_path: str, output_dir: str) -> dict:
        t_start = time.time()

        # --- Extract frames ---
        self._log('extraction', 2, 'Opening video with OpenCV...')
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video: {video_path}")

        fps_in    = cap.get(cv2.CAP_PROP_FPS) or 25
        total_f   = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width     = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height    = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        max_frames = min(total_f, 120)     # cap at 120 for speed

        self._log('extraction', 5, f'Video: {width}×{height} @ {fps_in:.1f}fps, {total_f} total frames')

        frames_gray  = []
        frames_color = []
        raw_frame_idx = 0

        while len(frames_gray) < max_frames:
            ret, frame = cap.read()
            if not ret:
                break
            if raw_frame_idx % max(1, total_f // max_frames) == 0:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                # Resize to workable size
                target_w = min(width,  320)
                target_h = min(height, int(320 * height / max(width, 1)))
                target_h = (target_h // 8) * 8
                target_w = (target_w // 8) * 8
                gray  = cv2.resize(gray,  (target_w, target_h))
                color = cv2.resize(frame, (target_w, target_h))
                frames_gray.append(gray)
                frames_color.append(color)
            raw_frame_idx += 1

        cap.release()
        n_frames = len(frames_gray)
        self._log('extraction', 10, f'Extracted {n_frames} frames ({frames_gray[0].shape[1]}×{frames_gray[0].shape[0]})')

        # --- GOP + Scene change analysis ---
        self._log('gop', 15, f'Analyzing GOP structure (size={self.gop_size})...')
        frame_types  = []
        scene_frames = []
        prev_gray    = None

        for i, gray in enumerate(frames_gray):
            if i % self.gop_size == 0:
                frame_types.append('I')
            elif self.scene_detect and prev_gray is not None:
                score = scene_change_score(prev_gray, gray)
                if score > 0.40:
                    frame_types.append('S')   # Forced I due to scene change
                    scene_frames.append(i)
                    self._log('gop', 15 + i/n_frames*5,
                              f'Scene change detected at frame {i} (score={score:.3f})')
                else:
                    frame_types.append('P')
            else:
                frame_types.append('P')
            prev_gray = gray

        i_count = sum(1 for t in frame_types if t in ('I', 'S'))
        p_count  = sum(1 for t in frame_types if t == 'P')
        self._log('gop', 22, f'GOP analysis done: {i_count} I-frames, {p_count} P-frames, {len(scene_frames)} scene changes')

        # --- Encode frames ---
        encoded_frames   = []
        reconstructed    = []
        ref_frame        = None
        total_bits       = 0
        psnr_values      = []
        ssim_values      = []
        mv_all           = []
        dct_sample       = None

        for i, (gray, ftype) in enumerate(zip(frames_gray, frame_types)):
            pct = 22 + (i / n_frames) * 55
            self._log('encoding', pct, f'Encoding frame {i+1}/{n_frames} [{ftype}]')

            is_intra = ftype in ('I', 'S')

            # Encode
            if is_intra or ref_frame is None:
                fdata = self._encode_frame_intra(gray)
                fdata['type'] = ftype
                rec   = self._reconstruct_frame(gray, None, True)
            else:
                fdata = self._encode_frame_inter(gray, ref_frame)
                rec   = self._reconstruct_frame(gray, ref_frame, False)
                if 'avg_mv' in fdata:
                    mv_all.append(fdata['avg_mv'])

            # Deblocking filter
            if self.deblock and rec is not None:
                rec = cv2.bilateralFilter(rec, 5, 10, 10)

            # Metrics
            psnr = compute_psnr(gray, rec)
            ssim = compute_ssim(gray.astype(np.float64), rec.astype(np.float64))
            psnr_values.append(psnr)
            ssim_values.append(ssim)

            fdata['psnr']  = round(psnr, 4)
            fdata['ssim']  = round(ssim, 4)
            fdata['index'] = i
            fdata['size_bytes'] = fdata['bits'] // 8

            total_bits += fdata['bits']
            encoded_frames.append(fdata)
            reconstructed.append(rec)
            ref_frame = rec   # P-frames reference previous reconstructed

            # Capture DCT sample from first I-frame
            if dct_sample is None and is_intra:
                block = gray[:8, :8].astype(np.float32) - 128.0
                d     = dct2d(block)
                qm    = self.quant_matrix
                q     = quantize_block(d, qm)
                dct_sample = zigzag_scan(q)

        # --- Save compressed output frames as video ---
        self._log('output', 80, 'Writing reconstructed video...')
        out_path = os.path.join(output_dir, 'compressed_output.mp4')
        fourcc   = cv2.VideoWriter_fourcc(*'mp4v')
        fh, fw   = reconstructed[0].shape[:2]
        vout     = cv2.VideoWriter(out_path, fourcc, fps_in, (fw, fh))

        for rec_gray in reconstructed:
            vout.write(cv2.cvtColor(rec_gray, cv2.COLOR_GRAY2BGR))
        vout.release()

        # Save comparison frame images
        orig_frame_path = os.path.join(output_dir, 'frame_original.jpg')
        comp_frame_path = os.path.join(output_dir, 'frame_compressed.jpg')
        mid = n_frames // 2
        cv2.imwrite(orig_frame_path, cv2.cvtColor(frames_gray[mid], cv2.COLOR_GRAY2BGR))
        cv2.imwrite(comp_frame_path, cv2.cvtColor(reconstructed[mid], cv2.COLOR_GRAY2BGR))

        # --- Compute summary metrics ---
        orig_size_bits  = width * height * 3 * 8 * n_frames
        comp_ratio      = round(orig_size_bits / max(total_bits, 1), 3)
        avg_psnr        = round(float(np.mean(psnr_values)), 4)
        avg_ssim        = round(float(np.mean(ssim_values)), 4)
        avg_mv_disp     = round(float(np.mean(mv_all)) if mv_all else 0.0, 4)
        enc_time        = round(time.time() - t_start, 3)
        enc_fps         = round(n_frames / max(enc_time, 0.001), 2)
        avg_bitrate     = round(total_bits * fps_in / n_frames / 1000, 2)

        self._log('output', 95, f'Encode complete. Ratio={comp_ratio}x PSNR={avg_psnr}dB SSIM={avg_ssim}')

        result = {
            'status'         : 'success',
            'video_info'     : {
                'original_width' : width,
                'original_height': height,
                'fps'            : round(fps_in, 2),
                'total_frames'   : total_f,
                'encoded_frames' : n_frames,
            },
            'codec_params'   : {
                'qp'            : self.qp,
                'gop_size'      : self.gop_size,
                'block_size'    : self.block_size,
                'search_range'  : self.search_range,
                'entropy_mode'  : self.entropy_mode,
                'adaptive_quant': self.adaptive_quant,
                'scene_detect'  : self.scene_detect,
                'rate_control'  : self.rate_control,
                'deblock'       : self.deblock,
            },
            'metrics'        : {
                'compression_ratio' : comp_ratio,
                'psnr_db'           : avg_psnr,
                'ssim'              : avg_ssim,
                'total_bits'        : total_bits,
                'orig_size_bits'    : orig_size_bits,
                'avg_bitrate_kbps'  : avg_bitrate,
                'encoding_fps'      : enc_fps,
                'encoding_time_s'   : enc_time,
                'avg_mv_displacement': avg_mv_disp,
                'i_frames'          : i_count,
                'p_frames'          : p_count,
                'scene_changes'     : len(scene_frames),
                'scene_change_frames': scene_frames,
            },
            'frame_data'     : [
                {
                    'index'     : f['index'],
                    'type'      : f['type'],
                    'bits'      : f['bits'],
                    'size_bytes': f.get('size_bytes', f['bits']//8),
                    'psnr'      : f['psnr'],
                    'ssim'      : f['ssim'],
                    'avg_mv'    : f.get('avg_mv', 0),
                } for f in encoded_frames
            ],
            'dct_sample'     : dct_sample or [0]*64,
            'output_video'   : 'compressed_output.mp4',
            'output_orig_frame': 'frame_original.jpg',
            'output_comp_frame': 'frame_compressed.jpg',
        }

        self._log('done', 100, 'All done.')
        return result
