"""
Smart Video Cutter v3 - AI scene detection
- Extract frames at 20fps
- Pre-filter by pixel diff to find candidate cut points
- Send 0.15s before vs 0.15s after frames to AI for evaluation
- Only cut when AI confirms it's a real scene change
- Extract representative images per scene
"""
import subprocess, os, glob, json, base64, time
from PIL import Image, ImageFilter, ImageStat

INPUT_VIDEO = r"d:\genvideo\Instagram (4).mp4"
OUTPUT_DIR = r"d:\genvideo\Instagram (4)"
TEMP_DIR = r"d:\genvideo\Instagram (4)\ai-temp"

NINE_ROUTER_KEY = "sk-45f29444341a436f-auc9eh-5c5abfbb"
NINE_ROUTER_BASE = "https://9router.ginstudio.asia"
VISION_MODEL = "main"

FPS = 20
FRAME_INTERVAL = 1.0 / FPS  # 0.05s
WINDOW_SEC = 0.15  # compare 0.15s before vs after
WINDOW_FRAMES = int(WINDOW_SEC / FRAME_INTERVAL)  # 3 frames

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)


def clean_dirs():
    for d in [TEMP_DIR, OUTPUT_DIR]:
        if os.path.exists(d):
            for f in os.listdir(d):
                fp = os.path.join(d, f)
                if os.path.isfile(fp):
                    os.remove(fp)


def extract_frames(video, fps=20):
    """Extract frames at given fps, return list of file paths."""
    pattern = os.path.join(TEMP_DIR, "raw_%05d.jpg")
    cmd = ["ffmpeg", "-i", video, "-vf", f"fps={fps},scale=320:-1", "-q:v", "3", "-y", pattern]
    subprocess.run(cmd, capture_output=True)
    frames = sorted(glob.glob(os.path.join(TEMP_DIR, "raw_*.jpg")))
    return frames


def get_duration(video):
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", video]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return float(json.loads(result.stdout)["format"]["duration"])


def compute_pixel_diff(img1_path, img2_path):
    """Compute combined diff between two images."""
    i1 = Image.open(img1_path).resize((40, 23)).convert("L")
    i2 = Image.open(img2_path).resize((40, 23)).convert("L")
    p1, p2 = list(i1.getdata()), list(i2.getdata())
    pixel_d = sum(abs(a - b) for a, b in zip(p1, p2)) / (len(p1) * 255)

    im1 = Image.open(img1_path).resize((40, 23))
    im2 = Image.open(img2_path).resize((40, 23))
    h1, h2 = im1.histogram(), im2.histogram()
    hist_d = sum(abs(a - b) for a, b in zip(h1, h2)) / (len(h1) * 255)

    e1 = Image.open(img1_path).resize((40, 23)).convert("L").filter(ImageFilter.FIND_EDGES)
    e2 = Image.open(img2_path).resize((40, 23)).convert("L").filter(ImageFilter.FIND_EDGES)
    ep1, ep2 = list(e1.getdata()), list(e2.getdata())
    edge_d = sum(abs(a - b) for a, b in zip(ep1, ep2)) / (len(ep1) * 255)

    s1, s2 = ImageStat.Stat(im1), ImageStat.Stat(im2)
    color_d = sum(abs(a - b) / 255 for a, b in zip(s1.mean, s2.mean)) / 3

    return pixel_d * 0.3 + hist_d * 0.2 + edge_d * 0.3 + color_d * 0.2


def compute_window_diff(frames, center_idx):
    """
    Compare 0.15s BEFORE center_idx vs 0.15s AFTER center_idx.
    Returns combined diff score.
    """
    before_start = max(0, center_idx - WINDOW_FRAMES)
    before_end = center_idx
    after_start = center_idx
    after_end = min(len(frames) - 1, center_idx + WINDOW_FRAMES)

    if before_end <= before_start or after_end <= after_start:
        return 0.0

    # Average diff across window pairs
    total_diff = 0.0
    count = 0
    for bi in range(before_start, before_end):
        for ai in range(after_start, after_end):
            d = compute_pixel_diff(frames[bi], frames[ai])
            total_diff += d
            count += 1

    return total_diff / count if count > 0 else 0.0


def encode_image(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def ai_evaluate(frame_before, frame_after, timestamp, diff_score):
    """
    Send representative frames to AI to decide if this is a real scene change.
    Returns (is_scene_change, confidence, reason)
    """
    content_parts = [
        {
            "type": "text",
            "text": (
                f"Is there a SCENE CHANGE at timestamp {timestamp:.2f}s in this video?\n"
                f"Left image = frames BEFORE {timestamp:.2f}s | Right image = frames AFTER {timestamp:.2f}s\n"
                f"Pixel difference score: {diff_score:.4f}\n\n"
                "Answer YES if: different location, different shot angle, different subject, hard cut, or fade transition.\n"
                "Answer NO if: same continuous shot, minor motion/camera movement, same scene continuing.\n\n"
                'Reply ONLY with JSON: {"scene_change": true/false, "confidence": 0.0-1.0, "reason": "short explanation"}'
            )
        }
    ]
    for fp in [frame_before, frame_after]:
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{encode_image(fp)}", "detail": "low"}
        })

    payload = {
        "model": VISION_MODEL,
        "messages": [{"role": "user", "content": content_parts}],
        "max_tokens": 150,
        "temperature": 0.1,
    }

    try:
        import requests
        r = requests.post(
            f"{NINE_ROUTER_BASE}/v1/chat/completions",
            headers={"Authorization": f"Bearer {NINE_ROUTER_KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=60,
        )
        data = r.json()
        if "error" in data:
            return False, 0.0, f"API error: {data['error']}"

        text = data["choices"][0]["message"]["content"]
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        result = json.loads(text)
        return result.get("scene_change", False), result.get("confidence", 0), result.get("reason", "")
    except Exception as e:
        return False, 0.0, f"Exception: {str(e)}"


def find_candidate_cuts(frames, all_diffs):
    """
    Find candidate cut points by looking for diff spikes.
    Only return top candidates to minimize API calls.
    """
    # Compute rolling average diff
    window_size = 3
    avg_diffs = []
    for i in range(len(all_diffs)):
        start = max(0, i - window_size)
        end = min(len(all_diffs), i + window_size + 1)
        avg = sum(all_diffs[start:end]) / (end - start)
        avg_diffs.append(avg)

    # Overall average
    overall_avg = sum(all_diffs) / len(all_diffs)

    # Candidates: diff > 2x overall average, spaced at least 0.5s apart
    candidates = []
    for idx, score in enumerate(all_diffs):
        if score > overall_avg * 2.0 and score > 0.10:
            t = (idx + 1) / FPS
            if not candidates or t - candidates[-1][0] >= 0.5:
                candidates.append((t, idx, score))

    # Sort by score, take top 20 for AI evaluation
    candidates.sort(key=lambda x: x[2], reverse=True)
    return candidates[:20]


def create_representative_frame(frames_dir, center_idx, frames_list, output_path):
    """Create a representative frame by averaging frames in a window."""
    # Take center frame as representative
    frame_path = frames_list[center_idx]
    import shutil
    shutil.copy(frame_path, output_path)


def cut_video(video, cut_points, duration, output_dir):
    """Cut video at specified timestamps."""
    boundaries = [0.0] + sorted(cut_points) + [duration]
    # Remove duplicates
    boundaries = sorted(set(boundaries))

    clips = []
    for i in range(len(boundaries) - 1):
        start = boundaries[i]
        end = boundaries[i + 1]
        clip_dur = end - start

        if clip_dur < 0.15:
            continue

        clip_name = f"clip_{i+1:03d}_{start:.2f}s-{end:.2f}s.mp4"
        clip_path = os.path.join(output_dir, clip_name)

        cmd = ["ffmpeg", "-i", video, "-ss", str(start), "-to", str(end),
               "-c", "copy", "-avoid_negative_ts", "make_zero", "-y", clip_path]
        subprocess.run(cmd, capture_output=True)

        if os.path.exists(clip_path):
            kb = os.path.getsize(clip_path) / 1024
            clips.append((clip_name, start, end, clip_dur, kb))

    return clips


def extract_scene_images(frames_list, cut_points, duration, output_dir, fps=20):
    """Extract 1-3 representative images per scene."""
    boundaries = [0.0] + sorted(cut_points) + [duration]
    boundaries = sorted(set(boundaries))

    images = []
    for i in range(len(boundaries) - 1):
        start = boundaries[i]
        end = boundaries[i + 1]
        clip_dur = end - start
        if clip_dur < 0.15:
            continue

        # Extract middle frame(s) of this scene
        start_frame = int(start * fps)
        end_frame = int(end * fps)
        mid_frame = (start_frame + end_frame) // 2

        # Clamp
        mid_frame = max(0, min(mid_frame, len(frames_list) - 1))

        scene_img = os.path.join(output_dir, f"scene_{i+1:03d}_{start:.1f}s.jpg")
        import shutil
        shutil.copy(frames_list[mid_frame], scene_img)
        images.append(scene_img)

        # For longer scenes (>3s), add a second representative image
        if clip_dur > 3.0:
            quarter = start_frame + (end_frame - start_frame) // 4
            three_quarter = start_frame + 3 * (end_frame - start_frame) // 4
            quarter = max(0, min(quarter, len(frames_list) - 1))
            three_quarter = max(0, min(three_quarter, len(frames_list) - 1))

            img_q = os.path.join(output_dir, f"scene_{i+1:03d}_a_{start + clip_dur * 0.25:.1f}s.jpg")
            img_tq = os.path.join(output_dir, f"scene_{i+1:03d}_b_{start + clip_dur * 0.75:.1f}s.jpg")
            shutil.copy(frames_list[quarter], img_q)
            shutil.copy(frames_list[three_quarter], img_tq)
            images.extend([img_q, img_tq])

    return images


def organize_into_clip_folders(confirmed_cuts, duration, frames_list, output_dir, clip_results, fps=20):
    """
    Organize output: each clip gets its own folder with:
      - clip_XXX_start-end.mp4
      - description.txt
      - images/  (representative frames)
    """
    import shutil

    boundaries = [0.0] + sorted(confirmed_cuts) + [duration]
    boundaries = sorted(set(boundaries))

    clip_idx = 0
    folders_created = []

    for i in range(len(boundaries) - 1):
        start = boundaries[i]
        end = boundaries[i + 1]
        clip_dur = end - start
        if clip_dur < 0.15:
            continue

        clip_idx += 1
        clip_folder_name = f"clip_{clip_idx:03d}_{start:.2f}s-{end:.2f}s"
        clip_folder = os.path.join(output_dir, clip_folder_name)
        os.makedirs(clip_folder, exist_ok=True)

        # Move video clip into folder
        clip_filename = f"{clip_folder_name}.mp4"
        src = os.path.join(output_dir, clip_filename)
        if os.path.exists(src):
            shutil.move(src, os.path.join(clip_folder, clip_filename))

        # Create images/ subfolder
        images_dir = os.path.join(clip_folder, "images")
        os.makedirs(images_dir, exist_ok=True)

        # Copy representative frames from output_dir
        start_frame = int(start * fps)
        end_frame = int(end * fps)
        mid_frame = (start_frame + end_frame) // 2
        mid_frame = max(0, min(mid_frame, len(frames_list) - 1))

        # Copy middle frame
        mid_img = os.path.join(images_dir, f"frame_{clip_idx:03d}_mid.jpg")
        shutil.copy(frames_list[mid_frame], mid_img)

        # For longer clips, add more frames spread across the clip
        if clip_dur > 3.0:
            num_frames = min(5, max(3, int(clip_dur / 1.0)))
            for j in range(num_frames):
                frac = (j + 0.5) / num_frames
                frame_pos = int(start_frame + frac * (end_frame - start_frame))
                frame_pos = max(0, min(frame_pos, len(frames_list) - 1))
                img_name = os.path.join(images_dir, f"frame_{clip_idx:03d}_{j+1:02d}.jpg")
                shutil.copy(frames_list[frame_pos], img_name)

        # Write description.txt
        desc_path = os.path.join(clip_folder, "description.txt")
        kb = os.path.getsize(os.path.join(clip_folder, clip_filename)) / 1024 if os.path.exists(os.path.join(clip_folder, clip_filename)) else 0
        with open(desc_path, "w", encoding="utf-8") as f:
            f.write(f"=== Clip {clip_idx:03d} ===\n")
            f.write(f"Time range: {start:.2f}s - {end:.2f}s\n")
            f.write(f"Duration: {clip_dur:.2f}s\n")
            f.write(f"Video file: {clip_filename}\n")
            f.write(f"File size: {kb:.0f}KB\n")
            f.write(f"Images: {len(os.listdir(images_dir))} representative frames in images/\n")
            f.write(f"\nThis is a short clip extracted from the original video.\n")
            f.write(f"It contains {len(os.listdir(images_dir))} representative frames in images/ folder.\n")

        # AI reason if available
        if clip_idx <= len(clip_results):
            reason = clip_results[clip_idx - 1] if clip_idx <= len(clip_results) else ""
            if reason:
                with open(desc_path, "a", encoding="utf-8") as f:
                    f.write(f"\nScene change: {reason}\n")

        folders_created.append(clip_folder_name)
        print(f"  -> {clip_folder_name}/ ({clip_dur:.2f}s, {kb:.0f}KB)")

    return folders_created


if __name__ == "__main__":
    print("=" * 60)
    print("SMART VIDEO CUTTER v3 (AI-verified scene changes)")
    print("=" * 60)

    clean_dirs()

    video = INPUT_VIDEO
    duration = get_duration(video)
    print(f"\nVideo: {duration:.2f}s")

    # Step 1: Extract frames
    print(f"\n[1] Extracting frames at {FPS}fps...")
    frames = extract_frames(video, FPS)
    print(f"  -> {len(frames)} frames extracted")

    # Step 2: Compute diffs between consecutive frames
    print(f"\n[2] Computing diffs for {len(frames)-1} frame pairs...")
    all_diffs = []
    for i in range(len(frames) - 1):
        d = compute_pixel_diff(frames[i], frames[i + 1])
        all_diffs.append(d)
    print(f"  -> Average diff: {sum(all_diffs)/len(all_diffs):.4f}")
    print(f"  -> Max diff: {max(all_diffs):.4f}")

    # Step 3: Find candidate cuts and evaluate with window comparison
    print(f"\n[3] Finding candidate cut points...")
    candidates = find_candidate_cuts(frames, all_diffs)
    print(f"  -> {len(candidates)} candidates to AI-evaluate")

    # Step 4: AI evaluate each candidate
    print(f"\n[4] AI evaluating scene changes (0.15s before vs after)...")
    confirmed_cuts = []
    clip_results = []  # store AI reasons per clip

    for t, idx, diff_score in candidates:
        before_idx = max(0, idx - WINDOW_FRAMES)
        after_idx = min(len(frames) - 1, idx + WINDOW_FRAMES)

        before_img = os.path.join(TEMP_DIR, f"eval_before_{idx:05d}.jpg")
        after_img = os.path.join(TEMP_DIR, f"eval_after_{idx:05d}.jpg")
        create_representative_frame(TEMP_DIR, before_idx, frames, before_img)
        create_representative_frame(TEMP_DIR, after_idx, frames, after_img)

        print(f"  Evaluating t={t:.2f}s (diff={diff_score:.4f})... ", end="", flush=True)

        is_change, confidence, reason = ai_evaluate(before_img, after_img, t, diff_score)

        if is_change and confidence > 0.5:
            print(f"CUT (conf={confidence:.2f}, {reason})")
            confirmed_cuts.append(t)
            clip_results.append(reason)
        else:
            print(f"SKIP (conf={confidence:.2f}, {reason})")

        time.sleep(0.5)

    confirmed_cuts = sorted(set(confirmed_cuts))
    print(f"\n  -> {len(confirmed_cuts)} scene changes confirmed")
    for t in confirmed_cuts:
        print(f"     {t:.2f}s")

    # Step 5: Cut videos
    print(f"\n[5] Cutting video at confirmed scene changes...")
    clips = cut_video(video, confirmed_cuts, duration, OUTPUT_DIR)

    for name, start, end, dur, kb in clips:
        print(f"  {name} ({dur:.2f}s, {kb:.0f}KB)")

    # Step 6: Extract representative images (keep for reference)
    print(f"\n[6] Organizing each clip into its own folder...")
    folders = organize_into_clip_folders(confirmed_cuts, duration, frames, OUTPUT_DIR, clips)

    # Print folder tree
    print(f"\n{'='*60}")
    print(f"DONE! Output: {OUTPUT_DIR}")
    print(f"\nFolder structure:")
    for root, dirs, files in os.walk(OUTPUT_DIR):
        # Skip ai-temp
        if "ai-temp" in root:
            continue
        level = root.replace(OUTPUT_DIR, "").count(os.sep)
        indent = "  " * level
        folder_name = os.path.basename(root)
        if folder_name:
            print(f"{indent}{folder_name}/")
        sub_indent = "  " * (level + 1)
        for f in sorted(files):
            fp = os.path.join(root, f)
            size = os.path.getsize(fp)
            if size < 1024:
                size_str = f"{size}B"
            elif size < 1024 * 1024:
                size_str = f"{size/1024:.1f}KB"
            else:
                size_str = f"{size/(1024*1024):.2f}MB"
            print(f"{sub_indent}{f} ({size_str})")
    print(f"{'='*60}")
