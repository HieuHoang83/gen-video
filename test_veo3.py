"""Test sinh video bang Veo 3 - Google Gemini API"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import time
import os
from pathlib import Path
from datetime import datetime
from google import genai
from google.genai import types as genai_types

API_KEY = os.environ.get("GOOGLE_API_KEY", "")  # Đặt API key qua biến môi trường
OUTPUT_DIR = Path("D:/genvideo/generated-videos")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

client = genai.Client(api_key=API_KEY)

PROMPT = "A cinematic drone shot flying over a misty mountain landscape at golden hour, clouds rolling between peaks, warm sunlight breaking through, photorealistic"
MODEL = "veo-3.1-generate-preview"

print(f"Model: {MODEL}")
print(f"Prompt: {PROMPT}")
print("-" * 50)

# Bắt đầu generate
print("\n[Đang yêu cầu sinh video...]")
operation = client.models.generate_videos(
    model=MODEL,
    prompt=PROMPT,
)
print(f"Operation: {operation.operation_name}")
print(f"Done: {operation.done}")

# Polling
start = time.time()
max_time = 600
poll_interval = 10

while not operation.done:
    elapsed = time.time() - start
    if elapsed > max_time:
        print("\n[ERROR] Timeout!")
        break
    print(f"  Đang chờ... ({elapsed:.0f}s đã qua)")
    time.sleep(poll_interval)
    operation = client.operations.get(operation)

if operation.done:
    if not hasattr(operation.response, 'generated_videos') or not operation.response.generated_videos:
        print("\n[ERROR] Sinh video thất bại - không có video trong response")
        exit(1)

    video = operation.response.generated_videos[0]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"veo3_{timestamp}.mp4"
    output_path = OUTPUT_DIR / filename

    print(f"\n[OK] Video sinh xong! Đang download...")

    # Download
    video.video.save(str(output_path))

    file_size = output_path.stat().st_size / (1024 * 1024)
    gen_time = time.time() - start
    print(f"  -> Saved: {output_path}")
    print(f"  -> Size: {file_size:.2f} MB")
    print(f"  -> Time: {gen_time:.0f}s")
    print("\nHOÀN TAT!")
