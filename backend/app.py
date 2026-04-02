import os
import uuid
import json
import time
import threading
import traceback
from flask import (Flask, request, jsonify, send_file,
                   Response, stream_with_context, send_from_directory)
from flask_cors import CORS
from werkzeug.utils import secure_filename

from codec_engine import VidCompCodec

# ─────────────────────────────────────────────
# Initialize Flask with custom paths to serve frontend correctly
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
FRONTEND_DIR = os.path.join(PROJECT_ROOT, 'frontend')

app = Flask(__name__, 
            static_folder=os.path.join(FRONTEND_DIR, 'static'),
            template_folder=FRONTEND_DIR)
CORS(app)

UPLOAD_DIR  = os.path.join(PROJECT_ROOT, 'uploads')
OUTPUT_DIR  = os.path.join(PROJECT_ROOT, 'outputs')

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

ALLOWED_EXT = {'mp4', 'avi', 'mov', 'mkv', 'webm', 'flv', 'wmv', 'm4v'}

# In-memory job store  {job_id: {status, events, result, ...}}
jobs: dict = {}
jobs_lock = threading.Lock()

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXT


def push_event(job_id: str, event_type: str, data: dict):
    with jobs_lock:
        if job_id in jobs:
            ts = time.strftime("%H:%M:%S")
            msg = data.get('message', '')
            if event_type == 'progress':
                msg = f"{data.get('stage', '').capitalize()}: {data.get('message', '')}"
            
            jobs[job_id]['events'].append({
                'event': event_type,
                'data' : json.dumps(data),
                'log_entry': {'ts': ts, 'msg': msg, 'type': event_type}
            })
            # Also update job-level progress for easy polling
            if event_type == 'progress':
                jobs[job_id]['progress'] = data.get('percent', 0)
                jobs[job_id]['stage'] = data.get('stage', 'Processing')


def run_encode_job(job_id: str, video_path: str, params: dict):
    """Runs in a background thread. Pushes SSE events via push_event()."""
    output_job_dir = os.path.join(OUTPUT_DIR, job_id)
    os.makedirs(output_job_dir, exist_ok=True)

    def progress_cb(stage: str, pct: float, msg: str):
        push_event(job_id, 'progress', {
            'stage'  : stage,
            'percent': round(pct, 1),
            'message': msg,
        })

    try:
        with jobs_lock:
            jobs[job_id]['status'] = 'running'

        push_event(job_id, 'started', {'message': 'Codec pipeline started'})

        codec = VidCompCodec(
            qp              = params.get('qp', 28),
            gop_size        = params.get('gop_size', 12),
            search_range    = params.get('search_range', 16),
            block_size      = params.get('block_size', 16),
            target_bitrate  = params.get('target_bitrate', 2500),
            adaptive_quant  = params.get('adaptive_quant', True),
            scene_detect    = params.get('scene_detect', True),
            rate_control    = params.get('rate_control', True),
            var_block       = params.get('var_block', False),
            deblock         = params.get('deblock', True),
            entropy_mode    = params.get('entropy_mode', 'huffman'),
            progress_callback = progress_cb,
        )

        result = codec.encode_video(video_path, output_job_dir)

        with jobs_lock:
            jobs[job_id]['status'] = 'done'
            jobs[job_id]['result'] = result
            jobs[job_id]['progress'] = 100

        push_event(job_id, 'done', result)

    except Exception as e:
        tb = traceback.format_exc()
        print(tb)
        with jobs_lock:
            jobs[job_id]['status'] = 'error'
            jobs[job_id]['error']  = str(e)
        push_event(job_id, 'error', {'message': str(e), 'traceback': tb})


# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────

@app.route('/')
def home():
    return send_file(os.path.join(FRONTEND_DIR, 'index.html'))


@app.route('/static/<path:path>')
def send_static(path):
    return send_from_directory(app.static_folder, path)


@app.route('/api/health')
def health():
    return jsonify({
        'status' : 'ok',
        'service': 'DataComp Codec API',
        'version': '2.5.0',
        'algorithms': ['DCT', 'Huffman', 'CABAC', 'Diamond-ME', 'Full-Search-ME'],
        'metrics'   : ['PSNR', 'SSIM', 'Compression Ratio', 'Encoding FPS'],
    })


@app.route('/api/info')
def codec_info():
    """Returns a description of each codec parameter — useful for documentation/UI."""
    return jsonify({
        'parameters': {
            'qp': {
                'name'       : 'Quantization Parameter',
                'range'      : [1, 51],
                'default'    : 28,
                'description': (
                    'Controls coarseness of DCT coefficient quantization. '
                    'Lower QP = more detail, more bits. '
                    'Higher QP = fewer bits, more loss. H.264-inspired scale.'
                ),
            },
            'gop_size': {
                'name'       : 'Group of Pictures Size',
                'range'      : [1, 60],
                'default'    : 12,
                'description': (
                    'Number of frames between I-frames (keyframes). '
                    'Smaller GOP = better seeking, more bits. '
                    'Larger GOP = better compression, less seekability.'
                ),
            },
            'search_range': {
                'name'       : 'Motion Estimation Search Range',
                'range'      : [4, 64],
                'default'    : 16,
                'description': (
                    'Pixel radius for motion vector search in P-frames. '
                    'Larger range catches fast motion but increases encode time.'
                ),
            },
            'block_size': {
                'name'       : 'Macroblock Size',
                'options'    : [4, 8, 16],
                'default'    : 16,
                'description': (
                    'Block size for motion estimation. '
                    '4x4 = highest quality, slowest. 16x16 = fastest.'
                ),
            },
            'entropy_mode': {
                'name'       : 'Entropy Coding Mode',
                'options'    : ['huffman', 'cabac'],
                'default'    : 'huffman',
                'description': (
                    'Huffman: fast, deterministic. '
                    'CABAC: ~10-15% better compression at higher CPU cost.'
                ),
            },
        },
        'features': {
            'adaptive_quant': 'Adjusts QP per-block based on local variance.',
            'scene_detect'  : 'Forces I-frame at scene cuts to prevent artifacts.',
            'rate_control'  : 'Dynamically adjusts QP to hit the target bitrate.',
            'deblock'       : 'Bilateral filter to suppress block boundary artifacts.',
        },
        'pipeline': [
            'Frame extraction & resize',
            'GOP structuring + scene change detection',
            'I-frame: DCT -> Quantization -> Zigzag -> RLE -> Huffman',
            'P-frame: Motion Est -> Residual DCT -> Quantization -> Huffman',
            'Decode loop: IDCT + motion compensation',
            'Deblocking filter',
            'PSNR / SSIM quality metrics',
            'MP4 mux via OpenCV VideoWriter',
        ],
    })


@app.route('/api/upload', methods=['POST'])
def upload():
    # Correctly parse form-data
    if 'video' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    file = request.files['video']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    if not allowed_file(file.filename):
        return jsonify({'error': f'Unsupported format. Allowed: {", ".join(ALLOWED_EXT)}'}), 400

    job_id   = str(uuid.uuid4())
    filename = secure_filename(file.filename)
    ext      = filename.rsplit('.', 1)[-1].lower()
    saved_as = f"{job_id}.{ext}"
    save_path = os.path.join(UPLOAD_DIR, saved_as)
    file.save(save_path)

    size_mb = os.path.getsize(save_path) / (1024 * 1024)

    with jobs_lock:
        jobs[job_id] = {
            'status'    : 'uploaded',
            'filename'  : filename,
            'saved_as'  : saved_as,
            'video_path': save_path,
            'size_mb'   : round(size_mb, 3),
            'events'    : [],
            'result'    : None,
            'error'     : None,
            'progress'  : 0,
            'stage'     : 'Uploaded',
        }

    # If parameters are provided in the same request, we can start encoding automatically.
    # The frontend main.js sends them with upload.
    params = {
        'qp'            : int(request.form.get('qp', 28)),
        'gop_size'      : int(request.form.get('gop_size', 12)),
        'search_range'  : int(request.form.get('search_range', 16)),
        'block_size'    : int(request.form.get('block_size', 16)),
        'target_bitrate': int(request.form.get('target_bitrate_kbps', 2500)),
        'adaptive_quant': request.form.get('adaptive_quantization', 'true').lower() == 'true',
        'scene_detect'  : request.form.get('scene_change_detection', 'true').lower() == 'true',
        'rate_control'  : request.form.get('rate_control', 'true').lower() == 'true',
        'var_block'     : request.form.get('var_block', 'false').lower() == 'true',
        'deblock'       : request.form.get('deblocking', 'true').lower() == 'true',
        'entropy_mode'  : request.form.get('entropy_mode', 'huffman'),
    }

    t = threading.Thread(target=run_encode_job, args=(job_id, save_path, params), daemon=True)
    t.start()
    
    return jsonify({
        'job_id'  : job_id,
        'filename': filename,
        'size_mb' : round(size_mb, 3),
        'message' : 'Upload successful. Encoding started.',
    })


@app.route('/api/encode', methods=['POST'])
def encode():
    data   = request.get_json(silent=True) or {}
    job_id = data.get('job_id')

    # If called via fetch with FormData, data will be empty.
    # The frontend main.js uses FormData for upload, and then presumably expects to call encode.
    # But wait, main.js startEncode() sends everything in the upload POST.
    
    with jobs_lock:
        if not job_id or job_id not in jobs:
            return jsonify({'error': 'Invalid or missing job_id'}), 400
        job = jobs[job_id]
        if job['status'] in ('running', 'done'):
            return jsonify({'error': 'Job already processed or running'}), 409

    params = {
        'qp'            : int(data.get('qp', 28)),
        'gop_size'      : int(data.get('gop_size', 12)),
        'search_range'  : int(data.get('search_range', 16)),
        'block_size'    : int(data.get('block_size', 16)),
        'target_bitrate': int(data.get('target_bitrate', 2500)),
        'adaptive_quant': str(data.get('adaptive_quant', 'true')).lower() == 'true',
        'scene_detect'  : str(data.get('scene_detect', 'true')).lower() == 'true',
        'rate_control'  : str(data.get('rate_control', 'true')).lower() == 'true',
        'var_block'     : str(data.get('var_block', 'false')).lower() == 'true',
        'deblock'       : str(data.get('deblock', 'true')).lower() == 'true',
        'entropy_mode'  : str(data.get('entropy_mode', 'huffman')),
    }

    video_path = job['video_path']
    t = threading.Thread(target=run_encode_job, args=(job_id, video_path, params), daemon=True)
    t.start()

    return jsonify({'job_id': job_id, 'message': 'Encoding started', 'params': params})


@app.route('/api/jobs/<job_id>')
def get_job_status(job_id):
    """Polling endpoint for job status & logs."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    # Format for main.js polling
    return jsonify({
        'status'  : job['status'],
        'progress': job.get('progress', 0),
        'stage'   : job.get('stage', 'Processing'),
        'log'     : [e['log_entry'] for e in job['events'] if 'log_entry' in e],
        'result'  : job['result'],
        'error'   : job['error']
    })


@app.route('/api/progress/<job_id>')
def progress_stream(job_id):
    """Server-Sent Events stream for job progress."""
    with jobs_lock:
        if job_id not in jobs:
            return jsonify({'error': 'Job not found'}), 404

    def generate():
        seen = 0
        yield f"data: {json.dumps({'event': 'connected', 'job_id': job_id})}\n\n"

        timeout = 600   # 10 minutes max
        start   = time.time()

        while time.time() - start < timeout:
            with jobs_lock:
                job    = jobs.get(job_id, {})
                events = job.get('events', [])
                status = job.get('status', 'unknown')

            while seen < len(events):
                ev = events[seen]
                yield f"event: {ev['event']}\ndata: {ev['data']}\n\n"
                seen += 1

            if status in ('done', 'error'):
                break

            time.sleep(0.15)

        yield f"data: {json.dumps({'event': 'stream_end'})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control' : 'no-cache',
            'X-Accel-Buffering': 'no',
        }
    )


@app.route('/api/result/<job_id>')
def get_result(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    if job['status'] == 'error':
        return jsonify({'error': job.get('error', 'Unknown error')}), 500
    if job['status'] != 'done':
        return jsonify({'status': job['status'], 'message': 'Not finished yet'}), 202
    return jsonify(job['result'])


@app.route('/api/frame/<job_id>/<frame_type>')
def get_frame(job_id, frame_type):
    """Return original or compressed frame JPEG."""
    if frame_type not in ('original', 'compressed'):
        return jsonify({'error': 'Invalid frame type'}), 400

    fname  = 'frame_original.jpg' if frame_type == 'original' else 'frame_compressed.jpg'
    fpath  = os.path.join(OUTPUT_DIR, job_id, fname)

    if not os.path.exists(fpath):
        return jsonify({'error': 'Frame not found'}), 404

    return send_file(fpath, mimetype='image/jpeg')


@app.route('/api/download/<job_id>')
def download_video(job_id):
    vpath = os.path.join(OUTPUT_DIR, job_id, 'compressed_output.mp4')
    if not os.path.exists(vpath):
        return jsonify({'error': 'Output video not found'}), 404
    return send_file(vpath, as_attachment=True, download_name='vidcomp_output.mp4')


@app.route('/api/jobs')
def list_jobs():
    with jobs_lock:
        summary = {
            jid: {
                'status'  : j['status'],
                'filename': j.get('filename'),
                'size_mb' : j.get('size_mb'),
            }
            for jid, j in jobs.items()
        }
    return jsonify(summary)


# ─────────────────────────────────────────────
# Start Server
if __name__ == '__main__':
    print("=" * 46)
    print("  DataComp Codec API  — v2.5.0")
    print("  http://localhost:5000")
    print("  Endpoints: /api/health  /api/info  /api/upload")
    print("=" * 46)
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host='0.0.0.0', port=port, threaded=True)
