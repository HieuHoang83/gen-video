"""
Cat video theo canh - Version 2: Dung scene detection chinh xac hon
"""
import subprocess
import os
import json

INPUT_VIDEO = r"d:\genvideo\vn-11110105-6ke15-lwmo6fsmf5y3e6.16000081718613738.mp4"
OUTPUT_DIR = r"d:\genvideo\cut-scenes"

os.makedirs(OUTPUT_DIR, exist_ok=True)

def detect_scenes_v2(input_video, threshold=0.3):
    """Detect scenes bang cach phan tich keyframes va scene score."""
    print(f"[1] Dang phat hien chuyen canh (threshold={threshold})...")

    # Dung select filter de lay tat ca scene changes
    cmd = [
        'ffmpeg', '-i', input_video,
        '-vf', f"select=gt(scene\\,{threshold})",
        '-vsync', 'vfr',
        '-frame_pts', 'true',
        '-f', 'null', '-'
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    output = result.stderr

    # Parse timestamps
    scene_times = []
    for line in output.split('\n'):
        if 'pts_time:' in line and 'iskey:1' in line:
            for part in line.split():
                if part.startswith('pts_time:'):
                    t = float(part.split(':')[1])
                    if not scene_times or t - scene_times[-1] >= 2.0:
                        scene_times.append(t)

    print(f"  -> Tim duoc {len(scene_times)} diem chuyen canh:")
    for t in scene_times:
        print(f"     {t:.2f}s")

    return scene_times


def extract_thumbnails(input_video, timestamps, output_dir):
    """Trich xuat thumbnail cho moi canh de xem truoc."""
    print(f"\n[2] Dang trich xuat thumbnails...")
    thumb_dir = os.path.join(output_dir, "thumbnails")
    os.makedirs(thumb_dir, exist_ok=True)

    # Extract 1 frame at each scene point
    for i, t in enumerate(timestamps):
        thumb_path = os.path.join(thumb_dir, f"scene_{i+1:03d}.jpg")
        cmd = [
            'ffmpeg', '-i', input_video,
            '-ss', str(t),
            '-vframes', '1',
            '-vf', 'scale=320:-1',
            '-y',
            thumb_path
        ]
        subprocess.run(cmd, capture_output=True)
        if os.path.exists(thumb_path):
            print(f"  -> Thumbnail {i+1}: {t:.1f}s")

    return thumb_dir


def cut_scenes_v2(input_video, scene_times, output_dir):
    """Cat video theo cac diem chuyen canh."""
    # Get duration
    cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', input_video]
    result = subprocess.run(cmd, capture_output=True, text=True)
    duration = float(json.loads(result.stdout)['format']['duration'])

    print(f"\n[3] Video duration: {duration:.1f}s")

    # Build clip boundaries
    boundaries = [0.0] + scene_times + [duration]
    clips = []

    for i in range(len(boundaries) - 1):
        start = boundaries[i]
        end = boundaries[i + 1]
        clip_dur = end - start

        if clip_dur < 1.0:
            continue

        clip_name = f"clip_{i+1:03d}_{start:.1f}s-{end:.1f}s.mp4"
        clip_path = os.path.join(output_dir, clip_name)

        print(f"  -> Clip {i+1}: {start:.1f}s - {end:.1f}s ({clip_dur:.1f}s)")

        cmd = [
            'ffmpeg', '-i', input_video,
            '-ss', str(start),
            '-to', str(end),
            '-c', 'copy',
            '-avoid_negative_ts', 'make_zero',
            '-y',
            clip_path
        ]
        subprocess.run(cmd, capture_output=True)

        if os.path.exists(clip_path):
            size_mb = os.path.getsize(clip_path) / (1024 * 1024)
            print(f"     OK ({size_mb:.2f} MB)")
            clips.append(clip_path)

    return clips


if __name__ == "__main__":
    print("=" * 50)
    print("VIDEO SCENE CUTTER v2")
    print("=" * 50)

    # Thu nhieu threshold de tim tot nhat
    for threshold in [0.1, 0.2, 0.3]:
        scenes = detect_scenes_v2(INPUT_VIDEO, threshold)
        if len(scenes) > 1:
            break

    if len(scenes) <= 1:
        print("\n  Khong phat hien duoc nhieu canh. Co the video la 1 canh lien mach.")
        print("  Se cat thanh 4 doan deu nhau...")
        scenes = [10.7, 21.4, 32.1]  # Chia deu 43s / 4

    clips = cut_scenes_v2(INPUT_VIDEO, scenes, OUTPUT_DIR)
    extract_thumbnails(INPUT_VIDEO, [0] + scenes[:3], OUTPUT_DIR)

    print(f"\n{'=' * 50}")
    print(f"HOAN TAT! Da cat {len(clips)} clips")
    print(f"Thu muc: {OUTPUT_DIR}")
    print(f"{'=' * 50}")
