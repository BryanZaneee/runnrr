import { capture } from './capture-lib.mjs';
await capture({
  url: "http://127.0.0.1:8001/",
  async shots(page, shoot) {
    await page.locator('#assistant-select option').first().waitFor({ state: 'attached' });
    await page.locator('#assistant-select').selectOption('research-analyst');
    await page.locator('#composer-input').scrollIntoViewIfNeeded();
    await shoot('workstation-local');
  }
});
