"""Cut video into scenes + extract all frames as images"""
import subprocess, os, glob, json, shutil
from PIL import Image, ImageFilter, ImageStat

INPUT_VIDEO = r"d:\genvideo\Instagram (4).mp4"
OUTPUT_DIR = r"d:\genvideo\Instagram (4)"
TEMP_DIR = r"d:\genvideo\Instagram (4)\ai-temp"

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

# Clean
for f in os.listdir(TEMP_DIR):
    os.remove(os.path.join(TEMP_DIR, f))
for f in os.listdir(OUTPUT_DIR):
    fp = os.path.join(OUTPUT_DIR, f)
    if os.path.isfile(fp):
        os.remove(fp)

# Duration
cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", INPUT_VIDEO]
result = subprocess.run(cmd, capture_output=True, text=True)
data = json.loads(result.stdout)
duration = float(data["format"]["duration"])

FPS = 20
print(f"Duration: {duration:.2f}s")

# Step 1: Extract frames at 20fps
print(f"\n[1] Extracting frames at {FPS}fps...")
pattern = os.path.join(TEMP_DIR, "f_%05d.jpg")
cmd = ["ffmpeg", "-i", INPUT_VIDEO, "-vf", f"fps={FPS},scale=200:-1", "-q:v", "3", "-y", pattern]
subprocess.run(cmd, capture_output=True)
frames = sorted(glob.glob(os.path.join(TEMP_DIR, "f_*.jpg")))
print(f"  -> {len(frames)} frames extracted")

# Step 2: Copy all frames to output dir as images
print(f"\n[2] Copying {len(frames)} frame images to output...")
for f in frames:
    shutil.copy(f, os.path.join(OUTPUT_DIR, os.path.basename(f)))
print("  -> Done")

# Step 3: Compute diffs
print(f"\n[3] Computing diffs for {len(frames)-1} frame pairs...")
diffs = []
for i in range(len(frames) - 1):
    i1 = Image.open(frames[i]).resize((40, 23)).convert("L")
    i2 = Image.open(frames[i+1]).resize((40, 23)).convert("L")
    p1, p2 = list(i1.getdata()), list(i2.getdata())
    pixel_d = sum(abs(a-b) for a,b in zip(p1,p2)) / (len(p1)*255)

    im1 = Image.open(frames[i]).resize((40, 23))
    im2 = Image.open(frames[i+1]).resize((40, 23))
    h1, h2 = im1.histogram(), im2.histogram()
    hist_d = sum(abs(a-b) for a,b in zip(h1,h2)) / (len(h1)*255)

    e1 = Image.open(frames[i]).resize((40, 23)).convert("L").filter(ImageFilter.FIND_EDGES)
    e2 = Image.open(frames[i+1]).resize((40, 23)).convert("L").filter(ImageFilter.FIND_EDGES)
    ep1, ep2 = list(e1.getdata()), list(e2.getdata())
    edge_d = sum(abs(a-b) for a,b in zip(ep1,ep2)) / (len(ep1)*255)

    s1, s2 = ImageStat.Stat(im1), ImageStat.Stat(im2)
    color_d = sum(abs(a-b)/255 for a,b in zip(s1.mean, s2.mean)) / 3

    combined = pixel_d * 0.3 + hist_d * 0.2 + edge_d * 0.3 + color_d * 0.2
    diffs.append(combined)

# Step 4: Find scene changes
sorted_diffs = sorted(enumerate(diffs), key=lambda x: x[1], reverse=True)
scene_changes = []
for idx, score in sorted_diffs:
    if score > 0.12:
        t = (idx + 1) / FPS
        if not scene_changes or t - scene_changes[-1] >= 0.5:
            scene_changes.append(t)
            print(f"  Scene change at {t:.2f}s (score={score:.4f})")

scene_changes.sort()
print(f"\nFound {len(scene_changes)} scene changes")

# Step 5: Cut videos at scene changes
cut_points = [0.0] + scene_changes + [duration]
cut_points = sorted(set(cut_points))

print(f"\n[4] Cutting {len(cut_points)-1} video clips...")
clips = []
for i in range(len(cut_points) - 1):
    start = cut_points[i]
    end = cut_points[i + 1]
    clip_dur = end - start
    if clip_dur < 0.15:
        continue

    clip_name = f"clip_{i+1:03d}_{start:.2f}s-{end:.2f}s.mp4"
    clip_path = os.path.join(OUTPUT_DIR, clip_name)

    cmd = ["ffmpeg", "-i", INPUT_VIDEO, "-ss", str(start), "-to", str(end),
           "-c", "copy", "-avoid_negative_ts", "make_zero", "-y", clip_path]
    subprocess.run(cmd, capture_output=True)

    if os.path.exists(clip_path):
        kb = os.path.getsize(clip_path) / 1024
        print(f"  Clip {i+1:2d}: {start:.2f}s -> {end:.2f}s ({clip_dur:.2f}s, {kb:.0f}KB)")
        clips.append(clip_path)

print(f"\n{'='*50}")
print(f"DONE!")
print(f"  -> {len(clips)} video clips")
print(f"  -> {len(frames)} frame images (in {OUTPUT_DIR})")
print(f"{'='*50}")
