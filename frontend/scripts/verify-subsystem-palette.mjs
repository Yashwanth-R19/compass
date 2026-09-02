#!/usr/bin/env node
/**
 * Session 15, Part E: "the colourblind check is not optional... run a
 * simulator." This is that simulator, kept in the repo (not a one-off
 * throwaway) so a future session that touches the palette in
 * styles/tokens.css can re-run this exact check rather than re-deriving it.
 *
 * Simulates the 12-colour subsystem categorical palette
 * (styles/tokens.css's --subsystem-1..12) under protanopia, deuteranopia,
 * and tritanopia using the Machado/Oliveira/Fernandes (2009) linear-RGB
 * dichromacy matrices, then checks every pair's CIE76 Lab distance -- both
 * at normal vision AND under each simulated deficiency -- against a minimum
 * "comfortably distinguishable in a UI at a glance" threshold. Run with:
 *
 *   node scripts/verify-subsystem-palette.mjs
 *
 * Exits non-zero (and lists the offending pair) if any two colours in the
 * palette are too close under any simulated vision type, INCLUDING normal
 * vision -- two raw colours can be too similar to each other before CVD
 * simulation ever enters the picture, which is exactly the bug this script
 * caught in this session (slots 7 and 10 were both violet-family, deltaE
 * 6.1 apart even at normal vision -- see DESIGN.md's accessibility
 * section).
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const tokensPath = path.join(__dirname, "..", "src", "styles", "tokens.css");
const tokensSrc = readFileSync(tokensPath, "utf8");

function extractPalette(src) {
  const palette = [];
  for (let i = 1; i <= 12; i++) {
    const m = src.match(new RegExp(`--subsystem-${i}:\\s*(#[0-9a-fA-F]{6})`));
    if (!m) throw new Error(`--subsystem-${i} not found in ${tokensPath}`);
    palette.push(m[1]);
  }
  return palette;
}

const PALETTE = extractPalette(tokensSrc);

function hexToRgb(hex) {
  const n = parseInt(hex.replace("#", ""), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

const MATRICES = {
  protanopia: [
    [0.152286, 1.052583, -0.204868],
    [0.114503, 0.786281, 0.099216],
    [-0.003882, -0.048116, 1.051998],
  ],
  deuteranopia: [
    [0.367322, 0.860646, -0.227968],
    [0.280085, 0.672501, 0.047413],
    [-0.01182, 0.04294, 0.968881],
  ],
  tritanopia: [
    [1.255528, -0.076749, -0.178779],
    [-0.078411, 0.930809, 0.147602],
    [0.004733, 0.691367, 0.3039],
  ],
};

function srgbToLinear(c) {
  c /= 255;
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}
function linearToSrgb(c) {
  const v = c <= 0.0031308 ? c * 12.92 : 1.055 * Math.pow(c, 1 / 2.4) - 0.055;
  return Math.max(0, Math.min(255, Math.round(v * 255)));
}

function simulate(hex, kind) {
  const [r, g, b] = hexToRgb(hex).map(srgbToLinear);
  const M = MATRICES[kind];
  const rr = M[0][0] * r + M[0][1] * g + M[0][2] * b;
  const gg = M[1][0] * r + M[1][1] * g + M[1][2] * b;
  const bb = M[2][0] * r + M[2][1] * g + M[2][2] * b;
  return [linearToSrgb(rr), linearToSrgb(gg), linearToSrgb(bb)];
}

function rgbToLab([r, g, b]) {
  const [rl, gl, bl] = [r, g, b].map(srgbToLinear);
  const x = rl * 0.4124 + gl * 0.3576 + bl * 0.1805;
  const y = rl * 0.2126 + gl * 0.7152 + bl * 0.0722;
  const z = rl * 0.0193 + gl * 0.1192 + bl * 0.9505;
  const [xn, yn, zn] = [0.95047, 1.0, 1.08883];
  const f = (t) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
  const fx = f(x / xn);
  const fy = f(y / yn);
  const fz = f(z / zn);
  return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)];
}

function deltaE(a, b) {
  return Math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2);
}

const MIN_ACCEPTABLE_DELTA_E = 8;
const VISION_TYPES = ["normal", "protanopia", "deuteranopia", "tritanopia"];

let worstOverall = Infinity;
let failed = false;
for (const kind of VISION_TYPES) {
  const labs = PALETTE.map((hex) => rgbToLab(kind === "normal" ? hexToRgb(hex) : simulate(hex, kind)));
  let worst = Infinity;
  let worstPair = null;
  for (let i = 0; i < labs.length; i++) {
    for (let j = i + 1; j < labs.length; j++) {
      const d = deltaE(labs[i], labs[j]);
      if (d < worst) {
        worst = d;
        worstPair = [i, j];
      }
      if (d < MIN_ACCEPTABLE_DELTA_E) {
        failed = true;
        console.log(
          `FAIL  ${kind.padEnd(13)} [${i}]${PALETTE[i]} vs [${j}]${PALETTE[j]}  deltaE=${d.toFixed(1)} < ${MIN_ACCEPTABLE_DELTA_E}`,
        );
      }
    }
  }
  worstOverall = Math.min(worstOverall, worst);
  console.log(
    `${kind.padEnd(13)} worst pair: [${worstPair[0]}]${PALETTE[worstPair[0]]} vs [${worstPair[1]}]${PALETTE[worstPair[1]]}  deltaE=${worst.toFixed(1)}`,
  );
}

console.log(`\nWorst deltaE across all ${VISION_TYPES.length} vision types: ${worstOverall.toFixed(1)} (threshold ${MIN_ACCEPTABLE_DELTA_E})`);
process.exit(failed ? 1 : 0);
