"""
Analyze each clip and generate AI prompts for video regeneration.
- Extract 5 frames from each clip (beginning, middle, end)
- Send to 9Router vision model for detailed description
- Output structured JSON with prompts for regeneration
"""
import subprocess, os, json, base64, glob, re
from pathlib import Path
import requests

VIDEO = r"d:\genvideo\vn-11110105-6ke15-lwmo6fsmf5y3e6.16000081718613738.mp4"
OUTPUT_DIR = r"d:\genvideo\cut-scenes"
TEMP_DIR = r"d:\genvideo\cut-scenes\analyze-temp"

NINE_ROUTER_KEY = "sk-45f29444341a436f-auc9eh-5c5abfbb"
NINE_ROUTER_BASE = "https://9router.ginstudio.asia"
VISION_MODEL = "main"

os.makedirs(TEMP_DIR, exist_ok=True)


def encode_image(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def analyze_clip(clip_path, clip_num):
    """
    Extract 5 key frames from clip and analyze with AI.
    Returns structured description + regeneration prompts.
    """
    clip_name = Path(clip_path).stem

    # Step 1: Extract 5 evenly spaced frames
    frames_dir = os.path.join(TEMP_DIR, f"clip_{clip_num:03d}")
    os.makedirs(frames_dir, exist_ok=True)

    # Get clip duration
    cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', clip_path]
    duration = float(json.loads(subprocess.run(cmd, capture_output=True, text=True).stdout)['format']['duration'])

    print(f"  Clip {clip_num}: {clip_name} ({duration:.2f}s)")

    # Extract 5 frames: at 10%, 30%, 50%, 70%, 90% of clip
    frame_times = [duration * pct for pct in [0.1, 0.3, 0.5, 0.7, 0.9]]
    frame_paths = []

    for i, t in enumerate(frame_times):
        frame_path = os.path.join(frames_dir, f"frame_{i}.jpg")
        cmd = ['ffmpeg', '-i', clip_path, '-ss', str(t), '-vframes', '1',
               '-vf', 'scale=640:-1', '-q:v', '2', '-y', frame_path]
        subprocess.run(cmd, capture_output=True)
        if os.path.exists(frame_path):
            frame_paths.append(frame_path)

    if len(frame_paths) < 2:
        return None

    # Step 2: AI analysis with 5 frames
    print(f"    -> Extracted {len(frame_paths)} frames, sending to AI...")

    content_parts = [
        {"type": "text", "text": (
            f"Analyze this video clip ({duration:.1f}s) from 5 key frames:\n"
            f"Frame 1: beginning (10%) | Frame 2: early (30%) | Frame 3: middle (50%)\n"
            f"Frame 4: late (70%) | Frame 5: end (90%)\n\n"
            f"Describe in detail:\n"
            f"1. SUBJECT: What/who is shown? (objects, people, products)\n"
            f"2. ACTION: What is happening? (motion, interaction, transformation)\n"
            f"3. SETTING: Where is it? (background, environment, lighting)\n"
            f"4. CAMERA: Angle, movement, shot type (close-up, wide, etc)\n"
            f"5. STYLE: Visual style, mood, color palette\n\n"
            f"Then write TWO prompts:\n"
            f"a) 'short_prompt': 1-2 sentence summary for AI video generation\n"
            f"b) 'detailed_prompt': Full detailed prompt (3-4 sentences) with all visual details\n\n"
            f"Reply ONLY JSON:\n"
            f'{{"subject": "...", "action": "...", "setting": "...", '
            f'"camera": "...", "style": "...", '
            f'"short_prompt": "...", "detailed_prompt": "..."}}'
        )}
    ]

    for fp in frame_paths:
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{encode_image(fp)}", "detail": "high"}
        })

    payload = {
        "model": VISION_MODEL,
        "messages": [{"role": "user", "content": content_parts}],
        "max_tokens": 500,
        "temperature": 0.3,
    }

    try:
        r = requests.post(f'{NINE_ROUTER_BASE}/v1/chat/completions',
            headers={'Authorization': f'Bearer {NINE_ROUTER_KEY}', 'Content-Type': 'application/json'},
            json=payload, timeout=90)
        data = r.json()

        if 'error' in data:
            print(f"    ERROR: {data['error']['message'][:200]}")
            return None

        text = data['choices'][0]['message']['content']
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"): text = text[4:]
            text = text.strip()

        result = json.loads(text)
        result['duration'] = round(duration, 2)
        result['clip_file'] = Path(clip_path).name
        result['time_range'] = clip_name  # e.g. "0.00s-3.85s"

        print(f"    OK: {result['short_prompt'][:80]}...")
        return result

    except Exception as e:
        print(f"    ERROR: {e}")
        return None


def generate_script(analyses):
    """Generate a video regeneration script from all analyses."""
    script = []

    script.append("=" * 70)
    script.append("VIDEO REGENERATION SCRIPT")
    script.append(f"Total clips: {len(analyses)}")
    script.append("=" * 70)
    script.append("")

    for i, a in enumerate(analyses):
        script.append(f"{'─' * 70}")
        script.append(f"CLIP {i+1} [{a['time_range']}] ({a['duration']}s)")
        script.append(f"File: {a['clip_file']}")
        script.append(f"{'─' * 70}")
        script.append(f"")
        script.append(f"Subject:  {a['subject']}")
        script.append(f"Action:   {a['action']}")
        script.append(f"Setting:  {a['setting']}")
        script.append(f"Camera:   {a['camera']}")
        script.append(f"Style:    {a['style']}")
        script.append(f"")
        script.append(f"📝 SHORT PROMPT (for Veo/Kie/Runway):")
        script.append(f"  {a['short_prompt']}")
        script.append(f"")
        script.append(f"📝 DETAILED PROMPT (for maximum quality):")
        script.append(f"  {a['detailed_prompt']}")
        script.append(f"")

    return "\n".join(script)


def main():
    print("=" * 60)
    print("VIDEO CLIP ANALYZER")
    print("Generating AI prompts for each clip")
    print("=" * 60)

    # Find all clip files
    clips = sorted(glob.glob(os.path.join(OUTPUT_DIR, "clip_*.mp4")))

    if not clips:
        print("No clips found! Run ai_scene_cut.py first.")
        return

    print(f"\nFound {len(clips)} clips to analyze\n")

    analyses = []
    for i, clip in enumerate(clips):
        result = analyze_clip(clip, i + 1)
        if result:
            analyses.append(result)

        # Rate limit
        if i < len(clips) - 1:
            import time
            time.sleep(2)

    # Save results
    if analyses:
        # JSON output
        json_path = os.path.join(OUTPUT_DIR, "clip_analyses.json")
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(analyses, f, indent=2, ensure_ascii=False)
        print(f"\nSaved JSON: {json_path}")

        # Script output
        script = generate_script(analyses)
        script_path = os.path.join(OUTPUT_DIR, "video_script.txt")
        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(script)
        print(f"Saved script: {script_path}")

        # Print summary
        print(f"\n{'=' * 70}")
        print("SUMMARY")
        print(f"{'=' * 70}")
        for i, a in enumerate(analyses):
            print(f"Clip {i+1:2d} [{a['time_range']:12s}] ({a['duration']:.1f}s): {a['short_prompt'][:90]}")


if __name__ == "__main__":
    main()
