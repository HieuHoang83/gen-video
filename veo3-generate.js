/**
 * Veo 3.1 Video Generation - Google Gemini API
 *
 * Setup:
 *   1. npm init -y
 *   2. npm install @google/genai
 *   3. Lay API key tu https://aistudio.google.com/app/apikey
 *   4. Chay: node veo3-generate.js
 *
 * API Key co the set qua bien moi truong GOOGLE_API_KEY
 * hoac truyen truc tiep vao script.
 */

import { GoogleGenAI } from "@google/genai";
import fs from "fs";
import path from "path";

// ──────────────────────────────────────────────
// CAU HINH
// ──────────────────────────────────────────────

const API_KEY = process.env.GOOGLE_API_KEY || "YOUR_API_KEY";

// Model Veo 3.1 (moi nhat hien tai)
const MODEL = "veo-3.1-generate-preview";

// Thu muc luu video ket qua
const OUTPUT_DIR = "./generated-videos";

// ──────────────────────────────────────────────
// THAM SO GENERATE (tuy chinh o day)
// ──────────────────────────────────────────────

const CONFIG = {
  // Prompt mo ta video muon tao (tieng Anh cang chi tiet cang tot)
  prompt: "A cinematic drone shot flying over a misty mountain landscape at golden hour, clouds rolling between peaks, warm sunlight breaking through, photorealistic, 4K quality",

  // So video sinh ra (1-4)
  numberOfVideos: 1,

  // Ti le khung hinh: "16:9" | "9:16" | "1:1" | "4:3"
  aspectRatio: "16:9",

  // Thoi luong video (giay)
  durationSeconds: 8,

  // Cho phep sinh hinh anh con nguoi
  // "allow_all" | "allow_adult" | "disallow"
  personGeneration: "allow_adult",

  // Negative prompt - nhung thu KHONG muon xuat hien
  negativePrompt: "",

  // Seed de co ket qua lap lai (bo qua hoac set 0 de random)
  seed: 0,
};

// ──────────────────────────────────────────────
// HAM CHINH
// ──────────────────────────────────────────────

async function generateVideo() {
  console.log("=".repeat(50));
  console.log("VEO 3.1 - VIDEO GENERATION");
  console.log("=".repeat(50));
  console.log(`Model: ${MODEL}`);
  console.log(`Prompt: ${CONFIG.prompt}`);
  console.log(`Aspect Ratio: ${CONFIG.aspectRatio}`);
  console.log(`Duration: ${CONFIG.durationSeconds}s`);
  console.log(`Videos: ${CONFIG.numberOfVideos}`);
  console.log("-".repeat(50));

  // Khoi tao client
  const ai = new GoogleGenAI({ apiKey: API_KEY });

  // Bat dau generate video
  console.log("\n[Dang yeu cau sinh video...]");
  let operation = await ai.models.generateVideos({
    model: MODEL,
    prompt: CONFIG.prompt,
    config: {
      numberOfVideos: CONFIG.numberOfVideos,
      aspectRatio: CONFIG.aspectRatio,
      durationSeconds: CONFIG.durationSeconds,
      personGeneration: CONFIG.personGeneration,
      ...(CONFIG.negativePrompt && { negativePrompt: CONFIG.negativePrompt }),
      ...(CONFIG.seed > 0 && { seed: CONFIG.seed }),
    },
  });

  console.log(`Operation ID: ${operation.operationName}`);
  console.log(`Done: ${operation.done}`);

  // Poll cho den khi hoan thanh
  let attempts = 0;
  const maxAttempts = 60; // toi da 60 lan poll (10 phut neu moi lan 10s)
  const pollInterval = 10_000; // 10 giay

  while (!operation.done && attempts < maxAttempts) {
    attempts++;
    const elapsed = ((attempts * pollInterval) / 1000).toFixed(0);
    console.log(`  [Poll #${attempts}] Dang doi... (${elapsed}s da qua)`);

    await new Promise((resolve) => setTimeout(resolve, pollInterval));

    operation = await ai.operations.getVideosOperation({
      operation: operation,
    });
  }

  // Kiem tra ket qua
  if (!operation.done) {
    console.error("\n[ERROR] Het th gian chờ! Video van dang xu ly.");
    process.exit(1);
  }

  if (operation.error) {
    console.error("\n[ERROR] Video generation that bai:");
    console.error(JSON.stringify(operation.error, null, 2));
    process.exit(1);
  }

  // ────────────────────────────────────────────
  // DOWNLOAD VIDEO
  // ────────────────────────────────────────────

  // Tao thu muc output
  if (!fs.existsSync(OUTPUT_DIR)) {
    fs.mkdirSync(OUTPUT_DIR, { recursive: true });
  }

  const generatedVideos = operation.response?.generatedVideos || [];
  console.log(`\n[SUCCESS] Da sinh ${generatedVideos.length} video!`);

  for (let i = 0; i < generatedVideos.length; i++) {
    const video = generatedVideos[i];
    const fileName = `veo3_${Date.now()}_${i + 1}.mp4`;
    const filePath = path.join(OUTPUT_DIR, fileName);

    console.log(`\n  [${i + 1}/${generatedVideos.length}] Downloading: ${fileName}`);

    try {
      // Download video
      await ai.files.download({
        file: video.video,
        downloadPath: filePath,
      });

      // Kiem tra file size
      const stats = fs.statSync(filePath);
      const sizeMB = (stats.size / (1024 * 1024)).toFixed(2);
      console.log(`  -> Saved: ${filePath} (${sizeMB} MB)`);
    } catch (err) {
      console.error(`  -> Loi khi download video #${i + 1}:`, err.message);
    }
  }

  console.log("\n" + "=".repeat(50));
  console.log("HOAN TAT! Video da duoc luu vao thu muc:", OUTPUT_DIR);
  console.log("=".repeat(50));
}

// ──────────────────────────────────────────────
// HAM TIEN ICH: Generate voi custom prompt
// ──────────────────────────────────────────────

/**
 * Ham nhanh de generate video voi prompt tuy chinh
 * @param {string} customPrompt - Mo ta video
 * @param {Object} options - Tuy chon bo sung
 * @returns {Promise<string>} - Duong dan file video
 */
export async function quickGenerate(customPrompt, options = {}) {
  const ai = new GoogleGenAI({ apiKey: API_KEY });

  const operation = await ai.models.generateVideos({
    model: MODEL,
    prompt: customPrompt,
    config: {
      numberOfVideos: options.numberOfVideos || 1,
      aspectRatio: options.aspectRatio || "16:9",
      durationSeconds: options.durationSeconds || 8,
      personGeneration: options.personGeneration || "allow_adult",
      ...options,
    },
  });

  // Poll until done
  while (!operation.done) {
    await new Promise((resolve) => setTimeout(resolve, 10_000));
    const updated = await ai.operations.getVideosOperation({ operation });
    Object.assign(operation, updated);
  }

  if (operation.error) {
    throw new Error(`Generation failed: ${JSON.stringify(operation.error)}`);
  }

  // Download
  if (!fs.existsSync(OUTPUT_DIR)) {
    fs.mkdirSync(OUTPUT_DIR, { recursive: true });
  }

  const video = operation.response.generatedVideos[0];
  const fileName = `veo3_${Date.now()}.mp4`;
  const filePath = path.join(OUTPUT_DIR, fileName);

  await ai.files.download({ file: video.video, downloadPath: filePath });
  return filePath;
}

// ──────────────────────────────────────────────
// RUN
// ──────────────────────────────────────────────

generateVideo().catch((err) => {
  console.error("\n[FATAL ERROR]", err.message);
  if (err.message.includes("401") || err.message.includes("403")) {
    console.error(
      "\n-> Loi xac thuc! Kiem tra lai API key."
    );
    console.error(
      "-> Lay API key tai: https://aistudio.google.com/app/apikey"
    );
  }
  process.exit(1);
});
