import { chromium } from '@playwright/test';
import { readFile } from 'node:fs/promises';

const base = process.env.RUNNRR_TEST_URL || 'http://127.0.0.1:8765';
const browser = await chromium.launch({ headless: true });
try {
  for (const name of ['workstation', 'usage', 'projects', 'persistence', 'support', 'sidebars', 'sidebars-reduced']) {
    const page = await browser.newPage({ viewport: { width: 1440, height: 960 }, reducedMotion: name.endsWith('-reduced') ? 'reduce' : 'no-preference' });
    // Any chat escaping the fixture mocks must fail before it can reach a provider.
    await page.route('**/api/chat', route => route.abort('blockedbyclient'));
    await page.goto(base);
    await page.waitForFunction(() => document.querySelector('#model-select')?.options.length
      && !document.querySelector('#composer-input')?.disabled);
    const source = await readFile(new URL(`./${name.replace('-reduced', '')}-browser.mjs`, import.meta.url), 'utf8');
    const result = await page.evaluate(source);
    console.log(`${name}: ${JSON.stringify(result)}`);
    await page.close();
  }
} finally {
  await browser.close();
}
