"""
Smart Video Cutter — AI-verified scene detection
===============================================
Logic:
1. Extract frames at 20fps
2. Compute combined pixel/histogram/edge/color diffs between consecutive frames
3. Pre-filter candidates: diff > 2x average, spaced >= 0.5s apart
4. AI evaluates: send 0.15s before vs 0.15s after frames → confirm/reject
5. Only cut when AI confirms (confidence > 0.5)
6. Output: each clip gets its own folder with video + description.txt + images/

Usage:
    python smart_cut.py --input video.mp4 --output folder_name
"""
import argparse
import subprocess
import os
import glob
import json
import base64
import time
import shutil
from PIL import Image, ImageFilter, ImageStat
import requests

# ── Config ──────────────────────────────────────────────────────────
NINE_ROUTER_KEY = "sk-45f29444341a436f-auc9eh-5c5abfbb"
NINE_ROUTER_BASE = "https://9router.ginstudio.asia"
VISION_MODEL = "main"

FPS = 20
FRAME_INTERVAL = 1.0 / FPS
WINDOW_SEC = 0.15  # compare 0.15s before vs after
WINDOW_FRAMES = int(WINDOW_SEC / FRAME_INTERVAL)  # 3 frames


# ── Helpers ─────────────────────────────────────────────────────────
def clean_dir(path):
    """Remove all files in a directory."""
    if os.path.exists(path):
        for f in os.listdir(path):
            fp = os.path.join(path, f)
            if os.path.isfile(fp):
                os.remove(fp)
    else:
        os.makedirs(path, exist_ok=True)


def get_duration(video):
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", video]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return float(json.loads(result.stdout)["format"]["duration"])


def extract_frames(video, temp_dir, fps=20):
    """Extract frames at given fps, return sorted list of paths."""
    pattern = os.path.join(temp_dir, "raw_%05d.jpg")
    cmd = ["ffmpeg", "-i", video, "-vf", f"fps={fps},scale=320:-1", "-q:v", "3", "-y", pattern]
    subprocess.run(cmd, capture_output=True)
    return sorted(glob.glob(os.path.join(temp_dir, "raw_*.jpg")))


def compute_diff(img1_path, img2_path):
    """Combined pixel/histogram/edge/color diff between two images."""
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
                f"Image 1 = frames BEFORE {timestamp:.2f}s | Image 2 = frames AFTER {timestamp:.2f}s\n"
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


def find_candidates(all_diffs, fps=20):
    """
    Find candidate cut points by diff spikes.
    Returns top 20 candidates sorted by score.
    """
    overall_avg = sum(all_diffs) / len(all_diffs)
    candidates = []

    for idx, score in enumerate(all_diffs):
        if score > overall_avg * 2.0 and score > 0.10:
            t = (idx + 1) / fps
            if not candidates or t - candidates[-1][0] >= 0.5:
                candidates.append((t, idx, score))

    candidates.sort(key=lambda x: x[2], reverse=True)
    return candidates[:20]


def cut_video(video, cut_points, duration, output_dir):
    """Cut video at specified timestamps, return list of (name, start, end, dur, kb)."""
    boundaries = [0.0] + sorted(set(cut_points)) + [duration]
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


def organize_clips(confirmed_cuts, duration, frames_list, output_dir, clips, fps=20):
    """
    Each clip gets its own folder with:
      - clip_XXX_start-end.mp4
      - description.txt
      - images/  (representative frames spread across the clip)
    """
    boundaries = [0.0] + sorted(set(confirmed_cuts)) + [duration]

    clip_idx = 0
    for i in range(len(boundaries) - 1):
        start = boundaries[i]
        end = boundaries[i + 1]
        clip_dur = end - start
        if clip_dur < 0.15:
            continue

        clip_idx += 1
        folder_name = f"clip_{clip_idx:03d}_{start:.2f}s-{end:.2f}s"
        clip_folder = os.path.join(output_dir, folder_name)

        # Clean old clip folder from previous runs
        if os.path.exists(clip_folder):
            for f in os.listdir(clip_folder):
                fp = os.path.join(clip_folder, f)
                if os.path.isfile(fp):
                    os.remove(fp)
                elif os.path.isdir(fp):
                    clean_dir(fp)
        os.makedirs(clip_folder, exist_ok=True)

        # Move video into folder
        clip_filename = f"{folder_name}.mp4"
        src = os.path.join(output_dir, clip_filename)
        if os.path.exists(src):
            shutil.move(src, os.path.join(clip_folder, clip_filename))

        # Create images/ subfolder (clean if exists from previous run)
        images_dir = os.path.join(clip_folder, "images")
        if os.path.exists(images_dir):
            for f in os.listdir(images_dir):
                fp = os.path.join(images_dir, f)
                if os.path.isfile(fp):
                    os.remove(fp)
        os.makedirs(images_dir, exist_ok=True)

        # Copy representative frames spread across the clip
        start_frame = int(start * fps)
        end_frame = int(end * fps)

        if clip_dur > 3.0:
            num_frames = min(5, max(3, int(clip_dur / 1.0)))
            for j in range(num_frames):
                frac = (j + 0.5) / num_frames
                frame_pos = int(start_frame + frac * (end_frame - start_frame))
                frame_pos = max(0, min(frame_pos, len(frames_list) - 1))
                img_name = os.path.join(images_dir, f"frame_{j+1:02d}.jpg")
                shutil.copy(frames_list[frame_pos], img_name)
        else:
            # Short clip: just 1 mid frame
            mid = (start_frame + end_frame) // 2
            mid = max(0, min(mid, len(frames_list) - 1))
            shutil.copy(frames_list[mid], os.path.join(images_dir, "frame_mid.jpg"))

        # Write description.txt
        clip_path = os.path.join(clip_folder, clip_filename)
        kb = os.path.getsize(clip_path) / 1024 if os.path.exists(clip_path) else 0
        num_imgs = len(os.listdir(images_dir))

        reason = ""
        if clip_idx <= len(clips):
            c = clips[clip_idx - 1]
            if len(c) > 5:
                reason = c[5]

        with open(os.path.join(clip_folder, "description.txt"), "w", encoding="utf-8") as f:
            f.write(f"=== Clip {clip_idx:03d} ===\n")
            f.write(f"Time range: {start:.2f}s - {end:.2f}s\n")
            f.write(f"Duration: {clip_dur:.2f}s\n")
            f.write(f"Video file: {clip_filename}\n")
            f.write(f"File size: {kb:.0f}KB\n")
            f.write(f"Images: {num_imgs} representative frames in images/\n")
            if reason:
                f.write(f"\nScene change reason: {reason}\n")


# ── Main ────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="AI-verified scene cutter")
    parser.add_argument("--input", required=True, help="Input video file")
    parser.add_argument("--output", required=True, help="Output directory (each clip gets its own folder)")
    args = parser.parse_args()

    video = args.input
    output_dir = args.output
    temp_dir = os.path.join(output_dir, ".ai-temp")

    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(temp_dir, exist_ok=True)
    clean_dir(temp_dir)

    # Clean old clip folders and stray files from previous runs
    for f in os.listdir(output_dir):
        fp = os.path.join(output_dir, f)
        if f.startswith("clip_") and os.path.isdir(fp):
            shutil.rmtree(fp)
        elif os.path.isfile(fp) and (f.endswith(".mp4") or f.endswith(".jpg")):
            os.remove(fp)

    print("=" * 60)
    print("SMART VIDEO CUTTER — AI-verified scene detection")
    print("=" * 60)

    duration = get_duration(video)
    print(f"\nVideo: {duration:.2f}s")

    # Step 1: Extract frames
    print(f"\n[1] Extracting frames at {FPS}fps...")
    frames = extract_frames(video, temp_dir, FPS)
    print(f"  -> {len(frames)} frames extracted")

    # Step 2: Compute diffs
    print(f"\n[2] Computing diffs for {len(frames)-1} frame pairs...")
    all_diffs = []
    for i in range(len(frames) - 1):
        all_diffs.append(compute_diff(frames[i], frames[i + 1]))

    avg_diff = sum(all_diffs) / len(all_diffs)
    max_diff = max(all_diffs)
    print(f"  -> Average: {avg_diff:.4f} | Max: {max_diff:.4f}")

    # Step 3: Find candidates
    print(f"\n[3] Finding candidate cut points...")
    candidates = find_candidates(all_diffs, FPS)
    print(f"  -> {len(candidates)} candidates (top by diff score)")

    # Step 4: AI evaluate each candidate
    print(f"\n[4] AI evaluating scene changes (0.15s before vs after)...")
    confirmed_cuts = []
    clip_reasons = []

    for t, idx, diff_score in candidates:
        before_idx = max(0, idx - WINDOW_FRAMES)
        after_idx = min(len(frames) - 1, idx + WINDOW_FRAMES)

        before_img = os.path.join(temp_dir, f"eval_before_{idx:05d}.jpg")
        after_img = os.path.join(temp_dir, f"eval_after_{idx:05d}.jpg")
        shutil.copy(frames[before_idx], before_img)
        shutil.copy(frames[after_idx], after_img)

        print(f"  t={t:.2f}s (diff={diff_score:.4f})... ", end="", flush=True)

        is_change, confidence, reason = ai_evaluate(before_img, after_img, t, diff_score)

        if is_change and confidence > 0.5:
            print(f"CUT (conf={confidence:.2f})")
            confirmed_cuts.append(t)
            clip_reasons.append(reason)
        else:
            print(f"SKIP (conf={confidence:.2f})")

        time.sleep(0.5)

    confirmed_cuts = sorted(set(confirmed_cuts))
    print(f"\n  -> {len(confirmed_cuts)} scene changes confirmed: {[f'{t:.2f}s' for t in confirmed_cuts]}")

    # Step 5: Cut videos
    print(f"\n[5] Cutting videos...")
    clips = cut_video(video, confirmed_cuts, duration, output_dir)
    for name, start, end, dur, kb in clips:
        print(f"  {name} ({dur:.2f}s, {kb:.0f}KB)")

    # Attach reasons to clips
    clips_with_reasons = []
    for i, c in enumerate(clips):
        reason = clip_reasons[i] if i < len(clip_reasons) else ""
        clips_with_reasons.append(c + (reason,))

    # Step 6: Organize into per-clip folders
    print(f"\n[6] Organizing into clip folders...")
    organize_clips(confirmed_cuts, duration, frames, output_dir, clips_with_reasons, FPS)

    # Print folder tree
    print(f"\n{'='*60}")
    print(f"DONE! Output: {output_dir}")
    print(f"\nFolder structure:")
    for root, dirs, files in os.walk(output_dir):
        if ".ai-temp" in root:
            continue
        level = root.replace(output_dir, "").count(os.sep)
        indent = "  " * level
        folder_name = os.path.basename(root)
        if folder_name:
            print(f"{indent}{folder_name}/")
        sub_indent = "  " * (level + 1)
        for f_name in sorted(files):
            fp = os.path.join(root, f_name)
            size = os.path.getsize(fp)
            if size < 1024:
                size_str = f"{size}B"
            elif size < 1024 * 1024:
                size_str = f"{size/1024:.1f}KB"
            else:
                size_str = f"{size/(1024*1024):.2f}MB"
            print(f"{sub_indent}{f_name} ({size_str})")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
