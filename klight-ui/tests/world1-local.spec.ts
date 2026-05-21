/**
 * World 1 — Solo dev, local code, no CI pipeline.
 *
 * Prerequisites:
 *   klight local build-load inventory-api --path ./klight-demo-inventory-api
 *   klight local build-load store-api     --path ./klight-demo-store-api
 *   klight local build-load store-web     --path ./klight-demo-store-web
 *   klight from-repos ./klight-demo-inventory-api \
 *                     ./klight-demo-store-api \
 *                     ./klight-demo-store-web \
 *                     --env dev
 *   KUBECONFIG=/tmp/klight-demo-kubeconfig.yaml uvicorn server:app --port 7700
 *
 * Run:
 *   cd klight-ui && npm run screenshots:w1
 */

import { test, expect } from '@playwright/test';
import { screenshotStep, waitForServer } from './helpers';

const W = 'world1-local';
const ENV = 'dev';
const SERVER = process.env.KLIGHT_URL || 'http://localhost:7700';

test.beforeAll(async ({ browser }) => {
  const page = await browser.newPage();
  await waitForServer(page, SERVER, 10);
  await page.close();
});

async function waitForEnvList(page: any) {
  // Wait until "Loading..." disappears from the env list
  await page.waitForFunction(
    () => {
      const el = document.querySelector('#env-list');
      return el && !el.textContent?.includes('Loading');
    },
    { timeout: 15000 }
  );
}

test('01 — Environments tab shows dev environment', async ({ page }) => {
  await page.goto('/');
  await waitForEnvList(page);
  await screenshotStep(page, W, '01-environments-tab');
});

test('02 — Cluster status bar visible', async ({ page }) => {
  await page.goto('/');
  // Wait for cluster bar to show actual data (not "Loading...")
  await page.waitForFunction(
    () => {
      const el = document.querySelector('#cb-name');
      return el && el.textContent && !el.textContent.includes('—');
    },
    { timeout: 12000 }
  ).catch(() => null);
  const barText = await page.locator('#cluster-bar').textContent().catch(() => '');
  const hasClusterInfo = barText && (barText.includes('CPU') || barText.includes('klight-demo') || barText.includes('MB'));
  if (!hasClusterInfo) {
    test.skip(true, 'Cluster bar not populated — is minikube running?');
    return;
  }
  await screenshotStep(page, W, '02-cluster-status-bar');
});

test('03 — env-dev running with local builds', async ({ page }) => {
  await page.goto('/');
  await waitForEnvList(page);
  const envLink = page.locator('#env-list').getByText(ENV);
  const visible = await envLink.isVisible().catch(() => false);
  if (!visible) {
    test.skip(true, `env-${ENV} not found — run: klight from-repos ... --env dev`);
    return;
  }
  await envLink.click();
  // Wait for the services panel to populate with service cards
  await page.waitForFunction(
    () => {
      const panel = document.getElementById('services-panel');
      return panel && panel.querySelectorAll('[onclick^="showLogs"]').length > 0;
    },
    { timeout: 15000 }
  );
  await page.waitForTimeout(600);
  await screenshotStep(page, W, '03-env-dev-running-local');
});

test('04 — Service detail: inventory-api (local build)', async ({ page }) => {
  await page.goto('/');
  await waitForEnvList(page);
  const envLink = page.locator('#env-list').getByText(ENV);
  const visible = await envLink.isVisible().catch(() => false);
  if (!visible) {
    test.skip(true, `env-${ENV} not found`);
    return;
  }
  await envLink.click();
  await page.waitForFunction(
    () => document.getElementById('services-panel')?.querySelectorAll('[onclick^="showLogs"]').length ?? 0 > 0,
    { timeout: 15000 }
  );
  const card = page.locator('[onclick*="inventory-api"]').first();
  const cardVisible = await card.isVisible().catch(() => false);
  if (!cardVisible) {
    test.skip(true, 'inventory-api card not visible');
    return;
  }
  await card.click();
  await page.waitForTimeout(600);
  await screenshotStep(page, W, '04-service-detail-inventory-api');
});

test('05 — Logs panel: inventory-api', async ({ page }) => {
  await page.goto('/');
  await waitForEnvList(page);
  const envLink = page.locator('#env-list').getByText(ENV);
  const visible = await envLink.isVisible().catch(() => false);
  if (!visible) {
    test.skip(true, `env-${ENV} not found`);
    return;
  }
  await envLink.click();
  await page.waitForFunction(
    () => document.getElementById('services-panel')?.querySelectorAll('[onclick^="showLogs"]').length ?? 0 > 0,
    { timeout: 15000 }
  );
  const card = page.locator('[onclick*="inventory-api"]').first();
  const cardVisible = await card.isVisible().catch(() => false);
  if (!cardVisible) {
    test.skip(true, 'inventory-api card not found');
    return;
  }
  await card.click();
  const logsBtn = page.locator('button', { hasText: /[Ll]og/ });
  const logsBtnVisible = await logsBtn.first().isVisible().catch(() => false);
  if (logsBtnVisible) {
    await logsBtn.first().click();
    await page.waitForTimeout(1500);
  }
  await screenshotStep(page, W, '05-logs-inventory-api');
});

test('06 — New environment form with sizing banner (local)', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('#env-list', { timeout: 10000 });
  const newEnvBtn = page.locator('button', { hasText: /New environment/i });
  const btnVisible = await newEnvBtn.isVisible().catch(() => false);
  if (!btnVisible) {
    test.skip(true, '+ New environment button not found');
    return;
  }
  await newEnvBtn.click();
  await page.waitForTimeout(800);
  const profileSelect = page.locator('#new-env-profile');
  const selectVisible = await profileSelect.isVisible().catch(() => false);
  if (selectVisible) {
    await profileSelect.selectOption({ index: 0 });
    await page.waitForTimeout(1200);
  }
  await screenshotStep(page, W, '06-new-env-sizing-banner');
});
