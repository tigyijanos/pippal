#!/usr/bin/env node
/**
 * Promo banner smoke test — structural guard for the Settings promotional
 * banner added to the top of the Settings view in settings.js.
 *
 * Run: node tests/ui_smokes/promo_banner.test.mjs
 *
 * Asserts:
 *  - URL constants (STORE_URL, REDDIT_URL) are defined in settings.js
 *  - The banner element is created with data-testid="settings-promo"
 *  - The Pro upsell button carries its testid (promo-get-pro)
 *  - The promo banner does NOT include a promo-reddit button (the Reddit
 *    community link lives in the About card, not the promo banner, to
 *    avoid showing it twice — fix/reddit-dedup-and-diag-cap)
 *  - The correct Store URL is associated with the Pro button
 *  - The promo banner is appended BEFORE the Voice card
 *    (view.appendChild(promoCard) appears before view.appendChild(voiceCard))
 *  - CSS classes for the promo banner exist in surfaces.css
 */

import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const root = join(__dirname, '../..');

function read(rel) {
  const p = join(root, rel);
  try { return readFileSync(p, 'utf8'); }
  catch (err) {
    console.error(`FATAL: cannot read ${p}: ${err.message}`);
    process.exit(2);
  }
}

const settingsSrc  = read('webui/js/settings.js');
const surfacesCss  = read('webui/css/surfaces.css');

let passed = 0, failed = 0;
function assert(condition, label) {
  if (condition) { console.log(`PASS: ${label}`); passed++; }
  else           { console.error(`FAIL: ${label}`); failed++; }
}

// (1) URL constants defined
assert(settingsSrc.includes('STORE_URL'),  '(1) STORE_URL constant defined');
assert(settingsSrc.includes('REDDIT_URL'), '(1) REDDIT_URL constant defined (kept as reference, not rendered in banner)');
assert(settingsSrc.includes('https://apps.microsoft.com/detail/9p0jx4n42nsl'),
  '(1) STORE_URL has correct Microsoft Store value');
assert(settingsSrc.includes('https://www.reddit.com/r/PipPalApp/'),
  '(1) REDDIT_URL constant has correct Reddit value');

// (2) Banner element testid
assert(
  settingsSrc.includes('settings-promo'),
  '(2) settings-promo testid present'
);

// (3) Pro button testid is present; Reddit button is absent (de-duplicated to About card)
assert(
  settingsSrc.includes('promo-get-pro'),
  '(3) promo-get-pro button testid present'
);
assert(
  !settingsSrc.includes('promo-reddit'),
  '(3) promo-reddit button NOT in promo banner (Reddit link lives in About card instead)'
);

// (4) open_url call referencing Store URL constant
const storeCallIdx = settingsSrc.indexOf('STORE_URL');
assert(storeCallIdx !== -1, '(4) STORE_URL referenced in settings.js');

// (5) Promo banner appended BEFORE voice card (order check by string position)
const promoAppendIdx = settingsSrc.indexOf('appendChild(promoCard)');
const voiceAppendIdx = settingsSrc.indexOf('appendChild(voiceCard)');
assert(
  promoAppendIdx !== -1 && voiceAppendIdx !== -1 && promoAppendIdx < voiceAppendIdx,
  '(5) promoCard appended before voiceCard in renderSettings'
);

// (6) CSS classes for promo banner in surfaces.css
assert(surfacesCss.includes('.settings-promo'), '(6) .settings-promo CSS class in surfaces.css');
assert(surfacesCss.includes('.promo-pro-cta'),  '(6) .promo-pro-cta CSS class in surfaces.css');

if (failed > 0) {
  console.error(`\n${failed} of ${passed + failed} test(s) FAILED.`);
  process.exit(1);
} else {
  console.log(`\nAll ${passed} tests passed.`);
  process.exit(0);
}
