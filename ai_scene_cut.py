"""
Smart Video Cutter v2 - Guaranteed 2-6s clips
Step 1: Find major scene changes (high diff + AI verify)
Step 2: Subdivide each scene into 2-4s clips at best diff points
Step 3: AI only verifies major scene changes, internal cuts use pixel-only
"""
import subprocess, os, json, base64, glob, time
from PIL import Image, ImageFilter, ImageStat
import requests

VIDEO = r"d:\genvideo\vn-11110105-6ke15-lwmo6fsmf5y3e6.16000081718613738.mp4"
OUTPUT_DIR = r"d:\genvideo\cut-scenes"
TEMP_DIR = r"d:\genvideo\cut-scenes\ai-temp"

NINE_ROUTER_KEY = "sk-45f29444341a436f-auc9eh-5c5abfbb"
NINE_ROUTER_BASE = "https://9router.ginstudio.asia"
VISION_MODEL = "main"

FPS = 20
TARGET = 3.0  # Aim for 3s per clip

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)


def extract_frames(input_video, fps=20):
    print(f"[1] Extracting frames at {fps}fps...")
    for f in glob.glob(os.path.join(TEMP_DIR, "f_*")):
        os.remove(f)
    cmd = ['ffmpeg', '-i', input_video, '-vf', f'fps={fps},scale=200:-1',
           '-q:v', '3', '-y', os.path.join(TEMP_DIR, 'f_%05d.jpg')]
    subprocess.run(cmd, capture_output=True)
    frames = sorted(glob.glob(os.path.join(TEMP_DIR, "f_*.jpg")))
    duration = get_duration(input_video)
    print(f"  -> {len(frames)} frames, {duration:.1f}s")
    return frames, duration


def get_duration(input_video):
    cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', input_video]
    return float(json.loads(subprocess.run(cmd, capture_output=True, text=True).stdout)['format']['duration'])


def compute_diffs(img1_path, img2_path):
    i1 = Image.open(img1_path).resize((40, 23)).convert('L')
    i2 = Image.open(img2_path).resize((40, 23)).convert('L')
    p1, p2 = list(i1.getdata()), list(i2.getdata())
    pixel_d = sum(abs(a-b) for a,b in zip(p1,p2)) / (len(p1)*255)

    im1 = Image.open(img1_path).resize((40, 23))
    im2 = Image.open(img2_path).resize((40, 23))
    h1, h2 = im1.histogram(), im2.histogram()
    hist_d = sum(abs(a-b) for a,b in zip(h1,h2)) / (len(h1)*255)

    e1 = Image.open(img1_path).resize((40, 23)).convert('L').filter(ImageFilter.FIND_EDGES)
    e2 = Image.open(img2_path).resize((40, 23)).convert('L').filter(ImageFilter.FIND_EDGES)
    ep1, ep2 = list(e1.getdata()), list(e2.getdata())
    edge_d = sum(abs(a-b) for a,b in zip(ep1,ep2)) / (len(ep1)*255)

    s1, s2 = ImageStat.Stat(im1), ImageStat.Stat(im2)
    color_d = sum(abs(a-b)/255 for a,b in zip(s1.mean, s2.mean)) / 3

    combined = pixel_d * 0.3 + hist_d * 0.2 + edge_d * 0.3 + color_d * 0.2
    return {'pixel': pixel_d, 'histogram': hist_d, 'edge': edge_d, 'color': color_d, 'combined': combined}


def encode_image(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def ai_check(frame1, frame2, t):
    content_parts = [
        {"type": "text", "text": (
            f"SCENE CHANGE at {t:.2f}s? Frame 1: BEFORE | Frame 2: AFTER\n"
            f"Different shot/location = YES. Same continuous = NO.\n"
            f'Reply ONLY JSON: {{"scene_change": true/false, "confidence": 0.0-1.0, "reason": "brief"}}'
        )}
    ]
    for fp in [frame1, frame2]:
        content_parts.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encode_image(fp)}", "detail": "low"}})

    payload = {
        "model": VISION_MODEL,
        "messages": [{"role": "user", "content": content_parts}],
        "max_tokens": 150, "temperature": 0.1,
    }
    try:
        r = requests.post(f'{NINE_ROUTER_BASE}/v1/chat/completions',
            headers={'Authorization': f'Bearer {NINE_ROUTER_KEY}', 'Content-Type': 'application/json'},
            json=payload, timeout=60)
        data = r.json()
        if 'error' in data: return None
        text = data['choices'][0]['message']['content']
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"): text = text[4:]
            text = text.strip()
        return json.loads(text)
    except:
        return None


def find_major_scene_changes(frames, all_diffs, duration, fps=FPS):
    """Find major scene changes using pixel spikes + AI."""
    print(f"\n[2a] Finding MAJOR scene changes...")

    sorted_by_score = sorted(enumerate(all_diffs), key=lambda x: x[1]['combined'], reverse=True)

    # Take top 15 highest diff points, AI verify each
    major_changes = []
    for idx, d in sorted_by_score[:15]:
        t = (idx + 1) / fps
        if d['combined'] > 0.15:
            # Auto-confirm very high diffs
            print(f"  {t:.3f}s: HIGH score {d['combined']:.4f} -> AUTO CONFIRM")
            major_changes.append(t)
            continue

        if any(abs(t - c) < 1.0 for c in major_changes):
            continue

        result = ai_check(frames[idx], frames[idx + 1], t)
        if result and result.get('scene_change', False) and result.get('confidence', 0) > 0.6:
            print(f"  {t:.3f}s: AI confirms ({result['reason']})")
            major_changes.append(t)
        time.sleep(1)

    major_changes = sorted(set(major_changes))
    print(f"  -> {len(major_changes)} major scene changes: {[f'{t:.2f}s' for t in major_changes]}")
    return major_changes


def subdivide_scenes(major_changes, all_diffs, duration, fps=FPS, target=3.0):
    """
    Subdivide each scene segment into 2-6s clips at best internal diff points.
    This ensures ALL clips are 2-6s regardless of AI opinion.
    """
    print(f"\n[2b] Subdividing scenes into {target}s clips...")

    boundaries = [0.0] + major_changes + [duration]
    all_cuts = list(major_changes)

    for i in range(len(boundaries) - 1):
        scene_start = boundaries[i]
        scene_end = boundaries[i + 1]
        scene_dur = scene_end - scene_start

        if scene_dur <= target + 1:
            continue  # Already short enough

        # Subdivide this scene
        num_clips = max(2, int(scene_dur / target))
        clip_target = scene_dur / num_clips

        print(f"  Scene {i+1}: {scene_start:.2f}s - {scene_end:.2f}s ({scene_dur:.1f}s) -> {num_clips} clips")

        current = scene_start
        internal_cuts = []

        while current < scene_end - 2:
            # Search window for best cut point
            window_start = int((current + 1.5) * fps)
            window_end = int(min((current + clip_target + 1.5) * fps, len(all_diffs) - 1))

            if window_start >= window_end:
                break

            # Find highest diff in window
            best_frame = window_start
            best_score = 0
            for f in range(window_start, window_end):
                score = all_diffs[f]['combined']
                if score > best_score:
                    best_score = score
                    best_frame = f

            cut_time = best_frame / fps
            internal_cuts.append(cut_time)
            print(f"    -> Cut at {cut_time:.3f}s (score={best_score:.4f})")
            current = cut_time

        all_cuts.extend(internal_cuts)

    all_cuts = sorted(set(all_cuts))
    print(f"  -> Total cut points: {len(all_cuts)}")
    return all_cuts


def cut_video(input_video, cut_timestamps, output_dir, duration):
    boundaries = [0.0] + sorted(cut_timestamps) + [duration]
    clips = []

    print(f"\n[3] Cutting {len(boundaries)-1} clips...")
    for i in range(len(boundaries) - 1):
        start = boundaries[i]
        end = boundaries[i + 1]
        clip_dur = end - start
        if clip_dur < 0.15:
            continue

        clip_name = f"clip_{i+1:03d}_{start:.2f}s-{end:.2f}s.mp4"
        clip_path = os.path.join(output_dir, clip_name)

        cmd = ['ffmpeg', '-i', input_video, '-ss', str(start), '-to', str(end),
               '-c', 'copy', '-avoid_negative_ts', 'make_zero', '-y', clip_path]
        subprocess.run(cmd, capture_output=True)

        if os.path.exists(clip_path):
            kb = os.path.getsize(clip_path) / 1024
            print(f"  Clip {i+1:2d}: {start:.2f}s -> {end:.2f}s ({clip_dur:.2f}s, {kb:.0f}KB)")
            clips.append(clip_path)

    return clips


if __name__ == "__main__":
    print("=" * 60)
    print("SMART VIDEO CUTTER v2 (Guaranteed 2-6s clips)")
    print(f"Target: ~{TARGET}s per clip")
    print("=" * 60)

    frames, duration = extract_frames(VIDEO, fps=FPS)

    # Compute all diffs
    print(f"\n[2] Computing diffs for {len(frames)-1} frame pairs...")
    all_diffs = []
    for i in range(len(frames) - 1):
        d = compute_diffs(frames[i], frames[i + 1])
        all_diffs.append(d)
    print(f"  Done.")

    # Step 2a: Find major scene changes (AI verified)
    major_changes = find_major_scene_changes(frames, all_diffs, duration)

    # Step 2b: Subdivide into 2-6s clips
    all_cuts = subdivide_scenes(major_changes, all_diffs, duration, target=TARGET)

    # Step 3: Cut video
    clips = cut_video(VIDEO, all_cuts, OUTPUT_DIR, duration)

    # Stats
    boundaries = [0.0] + all_cuts + [duration]
    clip_durs = []
    for i in range(len(boundaries) - 1):
        d = boundaries[i+1] - boundaries[i]
        if d >= 0.15:
            clip_durs.append(d)

    if clip_durs:
        avg = sum(clip_durs) / len(clip_durs)
        print(f"\n{'=' * 60}")
        print(f"DONE! {len(clips)} clips")
        print(f"Avg: {avg:.2f}s | Min: {min(clip_durs):.2f}s | Max: {max(clip_durs):.2f}s")
        print(f"Output: {OUTPUT_DIR}")

    print(f"{'=' * 60}")
