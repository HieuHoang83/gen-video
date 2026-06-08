"""
Cat video theo canh (scene detection) - Tu dong phat hien chuyen canh va cat thanh clip rieng
"""
import subprocess
import os
import json
import sys

INPUT_VIDEO = r"d:\genvideo\vn-11110105-6ke15-lwmo6fsmf5y3e6.16000081718613738.mp4"
OUTPUT_DIR = r"d:\genvideo\cut-scenes"

os.makedirs(OUTPUT_DIR, exist_ok=True)

def detect_scenes(input_video, threshold=30):
    """
    Dung ffmpeg scene detection de tim cac diem chuyen canh.
    threshold: do nhay cao = it canh hon (default 30)
    """
    print(f"[1] Dang phat hien chuyen canh (threshold={threshold})...")

    cmd = [
        'ffmpeg', '-i', input_video,
        '-vf', f'scene=threshold={threshold}/100,metadata=mode=print:file=-',
        '-f', 'null', '-'
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    output = result.stderr  # ffmpeg outputs to stderr

    # Parse scene change timestamps
    scene_changes = []
    for line in output.split('\n'):
        if 'lavfi.scene_score' in line:
            # Format: frame:0, pts:0, pts_time:0.000000, tag:lavfi.scene_score=0.123456
            for part in line.split(','):
                part = part.strip()
                if part.startswith('pts_time:'):
                    timestamp = float(part.split(':')[1])
                    scene_changes.append(timestamp)

    # Loai bo timestamps trung lap gan nhau (< 1 giay)
    filtered = []
    for t in scene_changes:
        if not filtered or t - filtered[-1] >= 1.0:
            filtered.append(t)

    print(f"  -> Tim duoc {len(filtered)} diem chuyen canh")
    for t in filtered:
        print(f"     {t:.2f}s")

    return filtered


def get_video_duration(input_video):
    """Lay thoi luong video."""
    cmd = [
        'ffprobe', '-v', 'quiet',
        '-print_format', 'json',
        '-show_format',
        input_video
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    data = json.loads(result.stdout)
    return float(data['format']['duration'])


def cut_scenes(input_video, scene_timestamps, output_dir):
    """Cat video thanh cac clip theo canh."""
    duration = get_video_duration(input_video)
    print(f"\n[2] Video duration: {duration:.2f}s")
    print(f"  Dang cat {len(scene_timestamps) + 1} clip...")

    # Them thoi diem bat dau va ket thuc
    timestamps = [0.0] + scene_timestamps + [duration]

    clips = []
    for i in range(len(timestamps) - 1):
        start = timestamps[i]
        end = timestamps[i + 1]
        clip_duration = end - start

        # Bo qua clip qua ngan (< 1s)
        if clip_duration < 1.0:
            continue

        clip_name = f"scene_{i+1:03d}_{start:.1f}s-{end:.1f}s.mp4"
        clip_path = os.path.join(output_dir, clip_name)

        print(f"  -> Clip {i+1}: {start:.1f}s - {end:.1f}s ({clip_duration:.1f}s)")

        cmd = [
            'ffmpeg', '-i', input_video,
            '-ss', str(start),
            '-to', str(end),
            '-c', 'copy',
            '-avoid_negative_ts', 'make_zero',
            '-y',
            clip_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            size_mb = os.path.getsize(clip_path) / (1024 * 1024)
            print(f"     Saved: {clip_name} ({size_mb:.2f} MB)")
            clips.append(clip_path)
        else:
            print(f"     ERROR: {result.stderr[:200]}")

    return clips


def crop_corner(input_video, output_dir, crop_type="center"):
    """Cat theo goc/crop khung hinh."""
    # Lay kich thuoc video
    cmd = [
        'ffprobe', '-v', 'quiet',
        '-print_format', 'json',
        '-show_streams',
        '-select_streams', 'v:0',
        input_video
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    data = json.loads(result.stdout)
    width = data['streams'][0]['width']
    height = data['streams'][0]['height']

    print(f"\n[3] Video size: {width}x{height}")

    crops = {
        "center": f"w={width//2}:h={height//2}:x={width//4}:y={height//4}",
        "left": f"w={width//2}:h={height}:x=0:y=0",
        "right": f"w={width//2}:h={height}:x={width//2}:y=0",
        "top": f"w={width}:h={height//2}:x=0:y=0",
        "bottom": f"w={width}:h={height//2}:x=0:y={height//2}",
    }

    for name, crop_filter in crops.items():
        if crop_type != "all" and crop_type != name:
            continue

        output_path = os.path.join(output_dir, f"crop_{name}.mp4")
        print(f"  -> Cropping: {name} ({crop_filter})")

        cmd = [
            'ffmpeg', '-i', input_video,
            '-vf', f"crop={crop_filter}",
            '-c:a', 'copy',
            '-y',
            output_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            print(f"     Saved: crop_{name}.mp4 ({size_mb:.2f} MB)")
        else:
            print(f"     ERROR: {result.stderr[:200]}")


if __name__ == "__main__":
    print("=" * 50)
    print("VIDEO SCENE CUTTER")
    print("=" * 50)

    # Tu dong phat hien chuyen canh va cat
    scenes = detect_scenes(INPUT_VIDEO, threshold=30)
    clips = cut_scenes(INPUT_VIDEO, scenes, OUTPUT_DIR)

    print(f"\n{'=' * 50}")
    print(f"HOAN TAT! Da cat {len(clips)} clip")
    print(f"Thu muc: {OUTPUT_DIR}")
    print(f"{'=' * 50}")
