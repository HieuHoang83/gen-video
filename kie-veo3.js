/**
 * Kie.ai Veo 3 Video Generation
 *
 * Setup:
 *   1. npm init -y
 *   2. npm install node-fetch
 *   3. Lay API key tu https://kie.ai/ → Account Settings → API Keys
 *   4. Chay: node kie-veo3.js
 *
 * API Key: set qua bien moi truong KIE_API_KEY
 *          hoac sua truc tiep trong file
 */

import fetch from 'node-fetch';
import fs from 'fs';
import https from 'https';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// ──────────────────────────────────────────────
// CAU HINH
// ──────────────────────────────────────────────

const KIE_API_KEY = process.env.KIE_API_KEY || '8005b6eae6861726bdad2093eb2642bd';
const BASE_URL = 'https://api.kie.ai';
const OUTPUT_DIR = path.join(__dirname, 'generated-videos');

// Tao thu muc output
if (!fs.existsSync(OUTPUT_DIR)) {
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });
}

// ──────────────────────────────────────────────
// THAM SO GEN VIDEO
// ──────────────────────────────────────────────

const CONFIG = {
  // Prompt mo ta video (tieng Anh cang chi tiet cang tot)
  prompt: 'A cinematic drone shot flying over a misty mountain landscape at golden hour, clouds rolling between peaks, warm sunlight breaking through, photorealistic, 4K quality',

  // Model: 'veo3_fast' | 'veo3' | 'veo3_pro'
  model: 'veo3_fast',

  // Ti le khung hinh: '16:9' | '9:16'
  aspect_ratio: '16:9',

  // Thoi luong (giay): 5 hoac 8
  duration: 8,

  // Quality: '720p' | '1080p' | '4K' (4K ton 2x credits)
  quality: '1080p',

  // Optional: URL anh dau vao (image-to-video)
  imageUrls: null,

  // Optional: Callback URL (webhook)
  callBackUrl: null,
};

// ──────────────────────────────────────────────
// HAM CHINH
// ──────────────────────────────────────────────

async function generateVideo() {
  console.log('='.repeat(50));
  console.log('KIE.AI - VEO 3 VIDEO GENERATION');
  console.log('='.repeat(50));
  console.log(`Model: ${CONFIG.model}`);
  console.log(`Prompt: ${CONFIG.prompt}`);
  console.log(`Aspect: ${CONFIG.aspect_ratio}`);
  console.log(`Duration: ${CONFIG.duration}s`);
  console.log(`Quality: ${CONFIG.quality}`);
  console.log('-'.repeat(50));

  // Buoc 1: Submit job
  console.log('\n[1] Dang gui yeu cau sinh video...');

  const body = {
    prompt: CONFIG.prompt,
    model: CONFIG.model,
    aspect_ratio: CONFIG.aspect_ratio,
    duration: CONFIG.duration,
    ...(CONFIG.imageUrls && { imageUrls: CONFIG.imageUrls }),
    ...(CONFIG.callBackUrl && { callBackUrl: CONFIG.callBackUrl }),
  };

  const response = await fetch(`${BASE_URL}/api/v1/veo/generate`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${KIE_API_KEY}`,
    },
    body: JSON.stringify(body),
  });

  const data = await response.json();

  if (!response.ok) {
    console.error('\n[ERROR] Khong the submit job:');
    console.error(JSON.stringify(data, null, 2));
    process.exit(1);
  }

  const taskId = data.data?.taskId || data.taskId;
  console.log(`  Task ID: ${taskId}`);

  if (!taskId) {
    console.error('\n[ERROR] Khong lay duoc taskId:');
    console.error(JSON.stringify(data, null, 2));
    process.exit(1);
  }

  // Buoc 2: Polling ket qua
  console.log('\n[2] Dang cho video sinh xong (co the mat 1-5 phut)...');

  let status = 'pending';
  let videoUrl = null;
  let attempts = 0;
  const maxAttempts = 60;
  const pollInterval = 10_000; // 10 giay

  while (status !== 'success' && attempts < maxAttempts) {
    attempts++;
    const elapsed = ((attempts * pollInterval) / 1000).toFixed(0);
    console.log(`  [Poll #${attempts}] Checking status... (${elapsed}s)`);

    await new Promise(resolve => setTimeout(resolve, pollInterval));

    const statusRes = await fetch(`${BASE_URL}/api/v1/veo/record-info?taskId=${taskId}`, {
      headers: {
        'Authorization': `Bearer ${KIE_API_KEY}`,
      },
    });

    const statusData = await statusRes.json();
    const record = statusData.data || statusData;
    status = record.status || record.state || 'unknown';

    console.log(`  -> Status: ${status}`);

    if (status === 'success' || status === 'completed') {
      videoUrl = record.videoUrl || record.resultUrl || record.url;
      break;
    }

    if (status === 'failed' || status === 'error') {
      console.error('\n[ERROR] Video generation failed:');
      console.error(JSON.stringify(record, null, 2));
      process.exit(1);
    }
  }

  if (!videoUrl) {
    console.error('\n[ERROR] Het th gian cho! Khong lay duoc video URL.');
    process.exit(1);
  }

  // Buoc 3: Download video
  console.log(`\n[3] Dang download video: ${videoUrl}`);

  const timestamp = Date.now();
  const fileName = `kie_veo3_${timestamp}.mp4`;
  const filePath = path.join(OUTPUT_DIR, fileName);

  return new Promise((resolve, reject) => {
    const file = fs.createWriteStream(filePath);

    https.get(videoUrl, (res) => {
      if (res.statusCode === 302 || res.statusCode === 301) {
        https.get(res.headers.location, (redirectRes) => {
          redirectRes.pipe(file);
          file.on('finish', () => {
            file.close();
            const stats = fs.statSync(filePath);
            const sizeMB = (stats.size / (1024 * 1024)).toFixed(2);
            console.log(`\n  -> Saved: ${filePath}`);
            console.log(`  -> Size: ${sizeMB} MB`);
            console.log('\n' + '='.repeat(50));
            console.log('HOAN TAT! Video da duoc luu.');
            console.log('='.repeat(50));
            resolve(filePath);
          });
        }).on('error', reject);
      } else {
        res.pipe(file);
        file.on('finish', () => {
          file.close();
          const stats = fs.statSync(filePath);
          const sizeMB = (stats.size / (1024 * 1024)).toFixed(2);
          console.log(`\n  -> Saved: ${filePath}`);
          console.log(`  -> Size: ${sizeMB} MB`);
          console.log('\n' + '='.repeat(50));
          console.log('HOAN TAT! Video da duoc luu.');
          console.log('='.repeat(50));
          resolve(filePath);
        });
      }
    }).on('error', reject);
  });
}

// ──────────────────────────────────────────────
// HAM TIEN ICH: Quick generate
// ──────────────────────────────────────────────

export async function quickGenerate(prompt, options = {}) {
  const body = {
    prompt,
    model: options.model || CONFIG.model,
    aspect_ratio: options.aspect_ratio || CONFIG.aspect_ratio,
    duration: options.duration || CONFIG.duration,
    ...(options.imageUrls && { imageUrls: options.imageUrls }),
  };

  // Submit
  const res = await fetch(`${BASE_URL}/api/v1/veo/generate`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${KIE_API_KEY}`,
    },
    body: JSON.stringify(body),
  });

  const data = await res.json();
  const taskId = data.data?.taskId || data.taskId;
  if (!taskId) throw new Error('No taskId returned');

  // Poll
  let status = 'pending';
  let videoUrl = null;

  while (status !== 'success' && status !== 'completed') {
    await new Promise(r => setTimeout(r, 10000));
    const s = await fetch(`${BASE_URL}/api/v1/veo/record-info?taskId=${taskId}`, {
      headers: { Authorization: `Bearer ${KIE_API_KEY}` },
    });
    const sd = await s.json();
    const rec = sd.data || sd;
    status = rec.status || rec.state;
    if (status === 'success' || status === 'completed') {
      videoUrl = rec.videoUrl || rec.resultUrl || rec.url;
    }
    if (status === 'failed' || status === 'error') {
      throw new Error(`Generation failed: ${JSON.stringify(rec)}`);
    }
  }

  if (!videoUrl) throw new Error('No video URL returned');

  // Download
  const fileName = `kie_veo3_${Date.now()}.mp4`;
  const filePath = path.join(OUTPUT_DIR, fileName);

  return new Promise((resolve, reject) => {
    const file = fs.createWriteStream(filePath);
    https.get(videoUrl, (res) => {
      if (res.statusCode === 302 || res.statusCode === 301) {
        https.get(res.headers.location, (r) => {
          r.pipe(file);
          file.on('finish', () => { file.close(); resolve(filePath); });
        }).on('error', reject);
      } else {
        res.pipe(file);
        file.on('finish', () => { file.close(); resolve(filePath); });
      }
    }).on('error', reject);
  });
}

// ──────────────────────────────────────────────
// CHECK BALANCE
// ──────────────────────────────────────────────

async function checkBalance() {
  console.log('\nChecking Kie.ai balance...');
  const res = await fetch(`${BASE_URL}/api/v1/user/balance`, {
    headers: { Authorization: `Bearer ${KIE_API_KEY}` },
  });
  const data = await res.json();
  console.log('Balance:', JSON.stringify(data, null, 2));
}

// ──────────────────────────────────────────────
// RUN
// ──────────────────────────────────────────────

// Uncomment de check balance
// await checkBalance();

generateVideo().catch(err => {
  console.error('\n[FATAL ERROR]', err.message);
  process.exit(1);
});
