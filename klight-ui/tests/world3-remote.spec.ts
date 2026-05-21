/**
 * World 3 — Remote cluster (EKS/GKE or simulated with second minikube profile).
 *
 * To simulate locally (no cloud needed):
 *   minikube start --profile klight-remote-sim --driver=docker --cpus=2 --memory=3072 --kubernetes-version=v1.30.0
 *   kubectl config use-context klight-remote-sim
 *   klight cluster setup-remote
 *   klight connect --url https://127.0.0.1:<port> --token <token> --name klight-remote
 *   klight use klight-remote
 *   klight sync https://raw.githubusercontent.com/slothlabsorg/klight-demo-infra/main/klight-team.yaml
 *   klight up store --env alice
 *   KUBECONFIG=/tmp/klight-demo-kubeconfig.yaml uvicorn server:app --port 7700
 *
 * Run:
 *   cd klight-ui && npm run screenshots:w3
 */

import { test } from '@playwright/test';
import { screenshotStep, waitForServer } from './helpers';

const W = 'world3-remote';
const SERVER = process.env.KLIGHT_URL || 'http://localhost:7700';

test.beforeAll(async ({ browser }) => {
  const page = await browser.newPage();
  await waitForServer(page, SERVER, 10);
  await page.close();
});

async function waitForEnvList(page: any) {
  await page.waitForFunction(
    () => {
      const el = document.querySelector('#env-list');
      return el && !el.textContent?.includes('Loading');
    },
    { timeout: 15000 }
  );
}

test('01 — Environments tab on remote cluster', async ({ page }) => {
  await page.goto('/');
  await waitForEnvList(page);
  await screenshotStep(page, W, '01-environments-tab-remote');
});

test('02 — Cluster status bar (remote context)', async ({ page }) => {
  await page.goto('/');
  await page.waitForFunction(
    () => {
      const el = document.querySelector('#cb-name');
      return el && el.textContent && !el.textContent.includes('—');
    },
    { timeout: 12000 }
  ).catch(() => null);
  await screenshotStep(page, W, '02-cluster-bar-remote');
});

test('03 — env-alice running on remote (CI images from ghcr.io)', async ({ page }) => {
  await page.goto('/');
  await waitForEnvList(page);
  const envLink = page.locator('#env-list').getByText('alice');
  const visible = await envLink.isVisible().catch(() => false);
  if (!visible) {
    test.skip(true, 'env-alice not found — run: klight up store --env alice');
    return;
  }
  await envLink.click();
  await page.waitForFunction(
    () => document.getElementById('services-panel')?.querySelectorAll('[onclick^="showLogs"]').length ?? 0 > 0,
    { timeout: 15000 }
  );
  await page.waitForTimeout(600);
  await screenshotStep(page, W, '03-alice-running-remote');
});

test('04 — Service detail: store-api (remote)', async ({ page }) => {
  await page.goto('/');
  await waitForEnvList(page);
  const envLink = page.locator('#env-list').getByText('alice');
  const visible = await envLink.isVisible().catch(() => false);
  if (!visible) {
    test.skip(true, 'env-alice not found');
    return;
  }
  await envLink.click();
  await page.waitForFunction(
    () => document.getElementById('services-panel')?.querySelectorAll('[onclick^="showLogs"]').length ?? 0 > 0,
    { timeout: 15000 }
  );
  const card = page.locator('[onclick*="store-api"]').first();
  const cardVisible = await card.isVisible().catch(() => false);
  if (!cardVisible) {
    test.skip(true, 'store-api card not visible');
    return;
  }
  await card.click();
  await page.waitForTimeout(600);
  await screenshotStep(page, W, '04-service-detail-store-api');
});

test('05 — Logs: store-api on remote cluster', async ({ page }) => {
  await page.goto('/');
  await waitForEnvList(page);
  const envLink = page.locator('#env-list').getByText('alice');
  const visible = await envLink.isVisible().catch(() => false);
  if (!visible) {
    test.skip(true, 'env-alice not found');
    return;
  }
  await envLink.click();
  await page.waitForFunction(
    () => document.getElementById('services-panel')?.querySelectorAll('[onclick^="showLogs"]').length ?? 0 > 0,
    { timeout: 15000 }
  );
  const card = page.locator('[onclick*="store-api"]').first();
  const cardVisible = await card.isVisible().catch(() => false);
  if (!cardVisible) {
    test.skip(true, 'store-api card not visible');
    return;
  }
  await card.click();
  const logsBtn = page.locator('button', { hasText: /[Ll]og/ });
  const logsBtnVisible = await logsBtn.first().isVisible().catch(() => false);
  if (logsBtnVisible) {
    await logsBtn.first().click();
    await page.waitForTimeout(1500);
  }
  await screenshotStep(page, W, '05-logs-store-api-remote');
});

test('06 — Env list on remote cluster', async ({ page }) => {
  await page.goto('/');
  await waitForEnvList(page);
  await screenshotStep(page, W, '06-env-list-remote-cluster');
});
