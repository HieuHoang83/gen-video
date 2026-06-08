"""
Cat video theo KEYFRAME + scene change - Chinh xac tung frame
Moi clip bat dau tu 1 keyframe (I-frame)
"""
import subprocess
import os
import json
import re

INPUT_VIDEO = r"d:\genvideo\vn-11110105-6ke15-lwmo6fsmf5y3e6.16000081718613738.mp4"
OUTPUT_DIR = r"d:\genvideo\cut-scenes"
TEMP_DIR = r"d:\genvideo\cut-scenes\temp"

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

def get_video_info(input_video):
    cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json',
           '-show_format', '-show_streams', '-select_streams', 'v:0', input_video]
    result = subprocess.run(cmd, capture_output=True, text=True)
    data = json.loads(result.stdout)
    return {
        'duration': float(data['format']['duration']),
        'width': int(data['streams'][0]['width']),
        'height': int(data['streams'][0]['height']),
        'fps': eval(data['streams'][0]['r_frame_rate']),
    }

def extract_keyframe_timestamps(input_video):
    """Lay timestamp cua TAT CA keyframes (I-frames)."""
    print("[1] Dang trich xuat keyframes...")
    cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json',
           '-show_frames', '-select_streams', 'v:0',
           '-show_entries', 'frame=key_frame,pict_type,pkt_pts_time',
           input_video]
    result = subprocess.run(cmd, capture_output=True, text=True)
    data = json.loads(result.stdout)

    keyframes = []
    for frame in data['frames']:
        if int(frame.get('key_frame', 0)) == 1:
            t = float(frame.get('pkt_pts_time', 0))
            keyframes.append(t)

    print(f"  -> Tim duoc {len(keyframes)} keyframes")
    return keyframes

def detect_scene_changes_at_keyframes(input_video, keyframes, threshold=0.15):
    """
    Tai moi keyframe, trich xuat frame va so sanh voi frame truoc do.
    Neu pixel difference > threshold => scene change.
    """
    print(f"[2] Dang phan tich scene changes (threshold={threshold})...")

    # Extract all keyframes as images
    for i, t in enumerate(keyframes):
        img_path = os.path.join(TEMP_DIR, f"key_{i:04d}.png")
        cmd = ['ffmpeg', '-i', input_video, '-ss', str(t),
               '-vframes', '1', '-vf', 'scale=160:-1',
               '-y', img_path]
        subprocess.run(cmd, capture_output=True)

    # So sanh cac frame lien kepp - dung ffmpeg pixel diff
    scene_changes = []

    for i in range(1, len(keyframes)):
        img1 = os.path.join(TEMP_DIR, f"key_{i-1:04d}.png")
        img2 = os.path.join(TEMP_DIR, f"key_{i:04d}.png")

        if not os.path.exists(img1) or not os.path.exists(img2):
            continue

        # Dung ffmpeg blended diff de tinh pixel difference
        cmd = ['ffmpeg', '-i', img2, '-i', img1,
               '-filter_complex', 'blend=all_mode=difference',
               '-vframes', '1', '-f', 'null', '-']
        result = subprocess.run(cmd, capture_output=True, text=True)

        # Parse PSNR/SSIM tu output
        output = result.stderr
        # Tim mean value tu diff
        diff_score = 0.0
        for line in output.split('\n'):
            if 'mean:' in line:
                match = re.search(r'mean:\s*([\d.]+)', line)
                if match:
                    diff_score = float(match.group(1)) / 255.0
                    break

        # Neu diff > threshold => scene change
        if diff_score > threshold:
            scene_changes.append(keyframes[i])
            print(f"  -> SCENE CHANGE at {keyframes[i]:.3f}s (diff={diff_score:.4f})")

    print(f"  -> Tong cong: {len(scene_changes)} scene changes")
    return scene_changes

def cut_at_scenes(input_video, scene_times, output_dir, info):
    """Cat video tai cac diem scene change."""
    duration = info['duration']
    boundaries = [0.0] + scene_times + [duration]
    clips = []

    print(f"\n[3] Dang cat {len(boundaries)-1} clips...")

    for i in range(len(boundaries) - 1):
        start = boundaries[i]
        end = boundaries[i + 1]
        clip_dur = end - start

        # Bo qua clip qua ngan
        if clip_dur < 0.5:
            continue

        clip_name = f"scene_{i+1:03d}_{start:.2f}s-{end:.2f}s.mp4"
        clip_path = os.path.join(output_dir, clip_name)

        cmd = ['ffmpeg', '-i', input_video,
               '-ss', str(start),
               '-to', str(end),
               '-c', 'copy',
               '-avoid_negative_ts', 'make_zero',
               '-y', clip_path]
        subprocess.run(cmd, capture_output=True)

        if os.path.exists(clip_path):
            size_kb = os.path.getsize(clip_path) / 1024
            print(f"  -> Clip {i+1}: {start:.2f}s - {end:.2f}s ({clip_dur:.2f}s, {size_kb:.0f}KB)")
            clips.append(clip_path)

    return clips

if __name__ == "__main__":
    print("=" * 50)
    print("KEYFRAME SCENE CUTTER")
    print("=" * 50)

    info = get_video_info(INPUT_VIDEO)
    print(f"Video: {info['width']}x{info['height']}, {info['fps']}fps, {info['duration']:.1f}s")

    # Buoc 1: Lay keyframes
    keyframes = extract_keyframe_timestamps(INPUT_VIDEO)

    if len(keyframes) < 2:
        print("Khong du keyframe de phan tich!")
        exit(1)

    # Buoc 2: Detect scene changes
    # Neu it keyframe (<50), dung threshold thap hon
    threshold = 0.15 if len(keyframes) < 100 else 0.25
    scene_changes = detect_scene_changes_at_keyframes(INPUT_VIDEO, keyframes, threshold)

    # Neu khong phat hien duoc scene change, dung threshold thap hon
    if len(scene_changes) < 2:
        print(f"\n  Threshold {threshold} qua cao, thu thap hon...")
        scene_changes = detect_scene_changes_at_keyframes(INPUT_VIDEO, keyframes, 0.08)

    # Neu van khong co, chia deu theo keyframe groups
    if len(scene_changes) < 2:
        print("\n  Khong phat hien duoc scene change, chia theo keyframe groups...")
        # Chia keyframes thanh groups ~5-8 frames/group
        group_size = max(3, len(keyframes) // 10)
        scene_changes = [keyframes[i] for i in range(group_size, len(keyframes), group_size)]
        print(f"  -> Chia thanh {len(scene_changes)+1} doan")

    # Buoc 3: Cat video
    clips = cut_at_scenes(INPUT_VIDEO, scene_changes, OUTPUT_DIR, info)

    # Clean up
    import shutil
    if os.path.exists(TEMP_DIR):
        shutil.rmtree(TEMP_DIR)

    print(f"\n{'=' * 50}")
    print(f"HOAN TAT! Da cat {len(clips)} clips")
    print(f"Thu muc: {OUTPUT_DIR}")
    print(f"{'=' * 50}")
