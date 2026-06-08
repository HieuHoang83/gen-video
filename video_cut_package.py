"""
Video Cutter + Image Extractor + Packager
1. Cut video into 2-6s clips (re-encode to avoid keyframe issues)
2. Extract images from each clip
3. Package each clip into its own folder with images + description
"""
import subprocess, os, json, base64, glob, time, shutil
from PIL import Image, ImageFilter, ImageStat
import requests

# ─── CONFIG ───
INPUT_VIDEO = r"d:\genvideo\vn-11110105-6ke15-lwmo6fsmf5y3e6.16000081718613738.mp4"
OUTPUT_BASE = r"d:\genvideo\cut-scenes"
TEMP_DIR = r"d:\genvideo\cut-scenes\ai-temp"

NINE_ROUTER_KEY = "sk-45f29444341a436f-auc9eh-5c5abfbb"
NINE_ROUTER_BASE = "https://9router.ginstudio.asia"
VISION_MODEL = "main"

FPS = 20
TARGET_CLIP_SEC = 3.0
IMAGES_PER_CLIP = 5  # Number of images to extract per clip

os.makedirs(OUTPUT_BASE, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)


# ─── VIDEO INFO ───
def get_duration(input_video):
    cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', input_video]
    return float(json.loads(subprocess.run(cmd, capture_output=True, text=True).stdout)['format']['duration'])


# ─── FRAME EXTRACTION ───
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


# ─── DIFF CALCULATION ───
def compute_diffs(img1_path, img2_path):
    i1 = Image.open(img1_path).resize((40, 23)).convert('L')
    i2 = Image.open(img2_path).resize((40, 23)).convert('L')
    p1, p2 = list(i1.getdata()), list(i2.getdata())
    pixel_d = sum(abs(a - b) for a, b in zip(p1, p2)) / (len(p1) * 255)

    im1 = Image.open(img1_path).resize((40, 23))
    im2 = Image.open(img2_path).resize((40, 23))
    h1, h2 = im1.histogram(), im2.histogram()
    hist_d = sum(abs(a - b) for a, b in zip(h1, h2)) / (len(h1) * 255)

    e1 = Image.open(img1_path).resize((40, 23)).convert('L').filter(ImageFilter.FIND_EDGES)
    e2 = Image.open(img2_path).resize((40, 23)).convert('L').filter(ImageFilter.FIND_EDGES)
    ep1, ep2 = list(e1.getdata()), list(e2.getdata())
    edge_d = sum(abs(a - b) for a, b in zip(ep1, ep2)) / (len(ep1) * 255)

    s1, s2 = ImageStat.Stat(im1), ImageStat.Stat(im2)
    color_d = sum(abs(a - b) / 255 for a, b in zip(s1.mean, s2.mean)) / 3

    combined = pixel_d * 0.3 + hist_d * 0.2 + edge_d * 0.3 + color_d * 0.2
    return {'pixel': pixel_d, 'histogram': hist_d, 'edge': edge_d, 'color': color_d, 'combined': combined}


# ─── AI SCENE DETECTION ───
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
        if 'error' in data:
            return None
        text = data['choices'][0]['message']['content']
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        return json.loads(text)
    except:
        return None


def find_major_scene_changes(frames, all_diffs, duration, fps=FPS):
    print(f"\n[2a] Finding MAJOR scene changes...")
    sorted_by_score = sorted(enumerate(all_diffs), key=lambda x: x[1]['combined'], reverse=True)

    major_changes = []
    for idx, d in sorted_by_score[:15]:
        t = (idx + 1) / fps
        if d['combined'] > 0.15:
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
    print(f"\n[2b] Subdividing scenes into {target}s clips...")
    boundaries = [0.0] + major_changes + [duration]
    all_cuts = list(major_changes)

    for i in range(len(boundaries) - 1):
        scene_start = boundaries[i]
        scene_end = boundaries[i + 1]
        scene_dur = scene_end - scene_start

        if scene_dur <= target + 1:
            continue

        num_clips = max(2, int(scene_dur / target))
        clip_target = scene_dur / num_clips

        print(f"  Scene {i+1}: {scene_start:.2f}s - {scene_end:.2f}s ({scene_dur:.1f}s) -> {num_clips} clips")

        current = scene_start
        internal_cuts = []

        while current < scene_end - 2:
            window_start = int((current + 1.5) * fps)
            window_end = int(min((current + clip_target + 1.5) * fps, len(all_diffs) - 1))

            if window_start >= window_end:
                break

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


# ─── CUT VIDEO (RE-ENCODE, not copy!) ───
def cut_video(input_video, cut_timestamps, output_dir, duration):
    boundaries = [0.0] + sorted(cut_timestamps) + [duration]
    clips_info = []

    print(f"\n[3] Cutting {len(boundaries)-1} clips...")
    for i in range(len(boundaries) - 1):
        start = boundaries[i]
        end = boundaries[i + 1]
        clip_dur = end - start
        if clip_dur < 0.15:
            continue

        clip_name = f"clip_{i+1:03d}_{start:.2f}s-{end:.2f}s.mp4"
        clip_path = os.path.join(output_dir, clip_name)

        # Use -ss BEFORE -i + re-encode (libx264 + aac) → no keyframe issues
        cmd = ['ffmpeg', '-y',
               '-ss', str(start), '-i', input_video, '-to', str(end - start),
               '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
               '-c:a', 'aac', '-b:a', '128k',
               '-movflags', '+faststart',
               clip_path]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if os.path.exists(clip_path):
            kb = os.path.getsize(clip_path) / 1024
            print(f"  Clip {i+1:2d}: {start:.2f}s -> {end:.2f}s ({clip_dur:.2f}s, {kb:.0f}KB)")
            clips_info.append({
                'index': i + 1,
                'start': start,
                'end': end,
                'duration': clip_dur,
                'path': clip_path,
                'name': clip_name,
            })

    return clips_info


# ─── EXTRACT IMAGES FROM A SINGLE CLIP ───
def extract_clip_images(clip_path, output_folder, num_images=5):
    """Extract representative images from a clip into an images/ subfolder."""
    images_dir = os.path.join(output_folder, "images")
    os.makedirs(images_dir, exist_ok=True)

    # Get clip duration
    duration = get_duration(clip_path)

    # Extract frames evenly spaced across the clip
    if num_images == 1:
        timestamps = [duration / 2]
    else:
        timestamps = [duration / (num_images + 1) * (i + 1) for i in range(num_images)]

    image_files = []
    for idx, ts in enumerate(timestamps):
        img_name = f"frame_{idx+1:02d}_{ts:.2f}s.jpg"
        img_path = os.path.join(images_dir, img_name)

        cmd = ['ffmpeg', '-y', '-ss', str(ts), '-i', clip_path,
               '-vframes', '1', '-q:v', '2', img_path]
        subprocess.run(cmd, capture_output=True)

        if os.path.exists(img_path):
            image_files.append(img_name)

    return image_files


# ─── GENERATE CLIP DESCRIPTION ───
def generate_clip_description(clip_path, clip_index, start, end, duration, folder_path):
    """Generate a text description file for a clip."""
    desc_file = os.path.join(folder_path, "description.txt")

    desc = (
        f"=== Clip {clip_index:03d} ===\n"
        f"Time range: {start:.2f}s - {end:.2f}s\n"
        f"Duration: {duration:.2f}s\n"
        f"Video file: {os.path.basename(clip_path)}\n"
        f"\n"
        f"This is a short clip extracted from the original video.\n"
        f"It contains {len(glob.glob(os.path.join(folder_path, 'images', 'frame_*.jpg')))} representative frames in images/ folder.\n"
    )

    with open(desc_file, 'w', encoding='utf-8') as f:
        f.write(desc)

    return desc_file


# ─── PACKAGE EACH CLIP ───
def package_clips(clips_info, output_base, images_per_clip=5):
    """For each clip, create a folder with video + images + description."""
    print(f"\n[4] Packaging {len(clips_info)} clips...")

    for clip in clips_info:
        idx = clip['index']
        folder_name = f"clip_{idx:03d}_{clip['start']:.2f}s-{clip['end']:.2f}s"
        folder_path = os.path.join(output_base, folder_name)

        # Clean old folder if exists
        if os.path.exists(folder_path):
            shutil.rmtree(folder_path)

        os.makedirs(folder_path, exist_ok=True)

        # Copy video clip into folder
        clip_dest = os.path.join(folder_path, os.path.basename(clip['path']))
        shutil.copy2(clip['path'], clip_dest)

        # Extract images into folder
        images = extract_clip_images(clip['path'], folder_path, num_images=images_per_clip)
        print(f"  Clip {idx}: extracted {len(images)} images")

        # Generate description
        desc_file = generate_clip_description(
            clip['path'], idx,
            clip['start'], clip['end'], clip['duration'],
            folder_path
        )
        print(f"  Clip {idx}: description written")

    print(f"  -> All clips packaged in: {output_base}")


# ─── MAIN ───
if __name__ == "__main__":
    print("=" * 60)
    print("VIDEO CUTTER + IMAGE EXTRACTOR + PACKAGER")
    print("=" * 60)

    # Step 1: Extract frames + compute diffs
    frames, duration = extract_frames(INPUT_VIDEO, fps=FPS)

    print(f"\n[2] Computing diffs for {len(frames)-1} frame pairs...")
    all_diffs = []
    for i in range(len(frames) - 1):
        d = compute_diffs(frames[i], frames[i + 1])
        all_diffs.append(d)
    print(f"  Done.")

    # Step 2a: Find major scene changes
    major_changes = find_major_scene_changes(frames, all_diffs, duration)

    # Step 2b: Subdivide into clips
    all_cuts = subdivide_scenes(major_changes, all_diffs, duration, target=TARGET_CLIP_SEC)

    # Step 3: Cut video
    clips_info = cut_video(INPUT_VIDEO, all_cuts, OUTPUT_BASE, duration)

    # Step 4: Package each clip (video + images + description)
    package_clips(clips_info, OUTPUT_BASE, images_per_clip=IMAGES_PER_CLIP)

    # Summary
    print(f"\n{'=' * 60}")
    print(f"DONE!")
    print(f"  Total clips: {len(clips_info)}")
    for c in clips_info:
        dur = c['duration']
        print(f"  Clip {c['index']:03d}: {c['start']:.2f}s - {c['end']:.2f}s ({dur:.2f}s)")
    print(f"  Output: {OUTPUT_BASE}")
    print(f"{'=' * 60}")
