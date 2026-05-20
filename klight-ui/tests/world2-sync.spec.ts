/**
 * World 2 — Startup scenario: sync + up without local repo clones.
 *
 * Prerequisites:
 *   KUBECONFIG=/tmp/klight-demo-kubeconfig.yaml uvicorn server:app --port 7700
 *
 * Run:
 *   cd klight-ui && npm run screenshots:w2
 *   open tests/screenshots/world2-sync/
 */

import { test, expect } from '@playwright/test';
import { waitForServer, screenshotStep } from './helpers';

const W = 'world2-sync';

test.beforeAll(async () => {
  await waitForServer({ page: null } as any, 'http://localhost:7700').catch(() => {});
});

test('01 — Environments tab (initial state)', async ({ page }) => {
  await page.goto('/');
  await page.waitForLoadState('networkidle');
  await screenshotStep(page, W, '01-environments-tab');
});

test('02 — Cluster status bar visible', async ({ page }) => {
  await page.goto('/');
  await page.waitForSelector('#cluster-bar');
  // Give the cluster-info API a moment to respond
  await page.waitForTimeout(1500);
  await screenshotStep(page, W, '02-cluster-status-bar');
});

test('03 — env-tienda running (if up)', async ({ page }) => {
  await page.goto('/');
  await page.waitForLoadState('networkidle');
  const envItem = page.locator('#env-list').getByText('tienda');
  const visible = await envItem.isVisible().catch(() => false);
  test.skip(!visible, 'env-tienda not running — run: klight up store --env tienda');
  await envItem.click();
  await page.waitForTimeout(1000);
  await screenshotStep(page, W, '03-tienda-running');
});

test('04 — Service detail (inventory-api)', async ({ page }) => {
  await page.goto('/');
  await page.waitForLoadState('networkidle');
  const envItem = page.locator('#env-list').getByText('tienda');
  const visible = await envItem.isVisible().catch(() => false);
  test.skip(!visible, 'env-tienda not running');
  await envItem.click();
  await page.waitForTimeout(1000);
  const svcCard = page.locator('text=inventory-api').first();
  const svcVisible = await svcCard.isVisible().catch(() => false);
  test.skip(!svcVisible, 'inventory-api card not found');
  await svcCard.click();
  await page.waitForTimeout(800);
  await screenshotStep(page, W, '04-service-detail-inventory-api');
});

test('05 — Logs panel (inventory-api)', async ({ page }) => {
  await page.goto('/');
  await page.waitForLoadState('networkidle');
  const envItem = page.locator('#env-list').getByText('tienda');
  const visible = await envItem.isVisible().catch(() => false);
  test.skip(!visible, 'env-tienda not running');
  await envItem.click();
  await page.waitForTimeout(800);
  const svcCard = page.locator('text=inventory-api').first();
  const svcVisible = await svcCard.isVisible().catch(() => false);
  test.skip(!svcVisible, 'inventory-api card not found');
  await svcCard.click();
  await page.waitForSelector('#logs-panel:not(.hidden)');
  await page.waitForTimeout(1000);
  await screenshotStep(page, W, '05-logs-inventory-api');
});

test('06 — New environment form + sizing banner', async ({ page }) => {
  await page.goto('/');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(1500);
  await page.click('button:has-text("+ New environment")');
  await page.waitForSelector('#new-env-form:not(.hidden)');
  await page.fill('#new-env-name', 'demo');
  await page.waitForTimeout(300);
  await screenshotStep(page, W, '06-new-env-form-empty');
  // Select a profile if available
  const options = await page.locator('#new-env-profile option:not([value=""])').count();
  if (options > 0) {
    await page.selectOption('#new-env-profile', { index: 1 });
    await page.waitForTimeout(1200);
    await screenshotStep(page, W, '06b-new-env-sizing-banner');
  }
});

test('07 — Resize cluster dialog', async ({ page }) => {
  await page.goto('/');
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(1500);
  await page.click('button:has-text("Resize cluster")');
  await page.waitForSelector('#resize-modal:not(.hidden)');
  await screenshotStep(page, W, '07-resize-cluster-dialog');
  // Close without resizing
  await page.click('button:has-text("Cancel")');
});

test('08 — Setup Wizard tab', async ({ page }) => {
  await page.goto('/');
  await page.waitForLoadState('networkidle');
  await page.click('button:has-text("Setup Wizard")');
  await page.waitForSelector('#tab-setup:not(.hidden)');
  await screenshotStep(page, W, '08-setup-wizard-tab');
});

test('09 — Scan results (requires GITHUB_TOKEN)', async ({ page }) => {
  const token = process.env.GITHUB_TOKEN;
  test.skip(!token, 'Set GITHUB_TOKEN env to run scan test');
  await page.goto('/');
  await page.click('button:has-text("Setup Wizard")');
  await page.fill('#s-platform', 'github');
  await page.fill('#s-org', 'slothlabsorg');
  await page.fill('#s-token', token!);
  await page.fill('#s-registry', 'ghcr.io/slothlabsorg');
  await page.click('button:has-text("Scan repos")');
  await page.waitForSelector('#step2:not(.hidden)', { timeout: 15000 });
  await screenshotStep(page, W, '09-scan-results-slothlabsorg');
});
