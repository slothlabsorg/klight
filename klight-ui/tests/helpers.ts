import { Page } from '@playwright/test';
import * as path from 'path';
import * as fs from 'fs';

export async function waitForServer(page: Page, url = 'http://localhost:7700', retries = 20): Promise<void> {
  for (let i = 0; i < retries; i++) {
    try {
      const r = await fetch(url);
      if (r.ok) return;
    } catch {}
    await new Promise(r => setTimeout(r, 500));
  }
  throw new Error(`Server not reachable at ${url} after ${retries} retries`);
}

export async function screenshotStep(
  page: Page,
  world: string,
  step: string,
): Promise<void> {
  const dir = path.join(__dirname, 'screenshots', world);
  fs.mkdirSync(dir, { recursive: true });
  await page.screenshot({ path: path.join(dir, `${step}.png`), fullPage: false });
}
