// Copies the pdf.js worker from the installed pdfjs-dist package into public/ so the evidence viewer can load it from the same origin.
// Runs after `npm ci` / `npm install`. The copied file is git-ignored (it is a build artifact of an Apache-2.0 dependency).
import { copyFileSync, existsSync, mkdirSync } from 'node:fs';
const src = 'node_modules/pdfjs-dist/build/pdf.worker.min.mjs';
if (!existsSync(src)) { console.error(`copy-pdf-worker: ${src} not found; run npm ci first`); process.exit(1); }
mkdirSync('public', { recursive: true });
copyFileSync(src, 'public/pdf.worker.min.mjs');
