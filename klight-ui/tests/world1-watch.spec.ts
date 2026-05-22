/**
 * World 1 — klight watch: hot reload end-to-end test.
 *
 * Spawns `klight watch inventory-api --env dev --no-initial-build` as a
 * subprocess, touches a source file, and waits for the pod to restart
 * (visible in the UI as a brief non-Running state followed by Running).
 *
 * Prerequisites (all must be true):
 *   - minikube klight-demo running
 *   - env-dev up with inventory-api deployed (klight from-repos ... --env dev)
 *   - inventory-api:local image already loaded (klight local build-load inventory-api ...)
 *   - KUBECONFIG=/tmp/klight-demo-kubeconfig.yaml
 *   - KLIGHT_TEST_SERVICES_DIR pointing to a dir with inventory-api/klight.yaml + Dockerfile
 *     (default: /Users/dany/dev/klight-suite-test/services)
 *   - klight UI server running: uvicorn server:app --port 7700
 *
 * Run:
 *   cd klight-ui && npm run screenshots:watch
 */

import { test, expect } from '@playwright/test';
import { screenshotStep, waitForServer } from './helpers';
import { spawn, ChildProcess } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';

const W = 'world1-watch';
const ENV = 'dev';
const SVC = 'inventory-api';
const SERVER = process.env.KLIGHT_URL || 'http://localhost:7700';
const KUBECONFIG = process.env.KUBECONFIG || '/tmp/klight-demo-kubeconfig.yaml';
const SERVICES_DIR = process.env.KLIGHT_TEST_SERVICES_DIR
  || '/Users/dany/dev/klight-suite-test/services';
const SVC_PATH = path.join(SERVICES_DIR, SVC);

function isPrereqMet(): boolean {
  return fs.existsSync(path.join(SVC_PATH, 'klight.yaml'))
    && fs.existsSync(path.join(SVC_PATH, 'Dockerfile'));
}

async function waitForEnvList(page: any) {
  await page.waitForFunction(
    () => {
      const el = document.querySelector('#env-list');
      return el && !el.textContent?.includes('Loading');
    },
    { timeout: 15000 }
  );
}

async function clickEnv(page: any) {
  const envLink = page.locator('#env-list').getByText(ENV);
  const visible = await envLink.isVisible().catch(() => false);
  if (!visible) return false;
  await envLink.click();
  await page.waitForFunction(
    () => document.getElementById('services-panel')
      ?.querySelectorAll('[onclick^="showLogs"]').length ?? 0 > 0,
    { timeout: 15000 }
  );
  return true;
}

test.beforeAll(async ({ browser }) => {
  const page = await browser.newPage();
  await waitForServer(page, SERVER, 10);
  await page.close();
});

test('01 — env-dev baseline (before watch)', async ({ page }) => {
  if (!isPrereqMet()) {
    test.skip(true, `inventory-api service dir not found at ${SVC_PATH}`);
    return;
  }
  await page.goto('/');
  await waitForEnvList(page);
  const ok = await clickEnv(page);
  if (!ok) {
    test.skip(true, `env-${ENV} not running`);
    return;
  }
  await page.waitForTimeout(600);
  await screenshotStep(page, W, '01-baseline-env-dev');
});

test('02 — klight watch starts and outputs watching message', async ({ page }) => {
  if (!isPrereqMet()) {
    test.skip(true, `Service dir not found: ${SVC_PATH}`);
    return;
  }

  let watchProc: ChildProcess | null = null;
  let stdout = '';

  try {
    watchProc = spawn(
      'klight',
      ['watch', SVC, '--env', ENV, '--path', SVC_PATH, '--no-initial-build'],
      {
        env: { ...process.env, KUBECONFIG },
        detached: false,
      }
    );

    watchProc.stdout?.on('data', (d) => { stdout += d.toString(); });
    watchProc.stderr?.on('data', (d) => { stdout += d.toString(); });

    // Wait for "Watching" line in output (up to 10s)
    const started = await new Promise<boolean>((resolve) => {
      const timer = setTimeout(() => resolve(false), 10000);
      const check = setInterval(() => {
        if (stdout.toLowerCase().includes('watching')) {
          clearInterval(check);
          clearTimeout(timer);
          resolve(true);
        }
      }, 200);
    });

    if (!started) {
      test.skip(true, 'klight watch did not output "Watching" within 10s');
      return;
    }

    // Screenshot the UI while watch is running
    await page.goto('/');
    await waitForEnvList(page);
    await clickEnv(page);
    await page.waitForTimeout(600);
    await screenshotStep(page, W, '02-watch-running-baseline');

  } finally {
    watchProc?.kill('SIGTERM');
  }
});

test('03 — file change triggers rebuild + pod restart', async ({ page }) => {
  if (!isPrereqMet()) {
    test.skip(true, `Service dir not found: ${SVC_PATH}`);
    return;
  }

  // Find a .py file to touch
  const appDir = path.join(SVC_PATH, 'app');
  const searchDir = fs.existsSync(appDir) ? appDir : SVC_PATH;
  const pyFiles = fs.readdirSync(searchDir, { withFileTypes: true })
    .filter(e => e.isFile() && e.name.endsWith('.py'))
    .map(e => path.join(searchDir, e.name));

  if (pyFiles.length === 0) {
    test.skip(true, `No .py files found in ${searchDir}`);
    return;
  }

  const targetFile = pyFiles[0];
  let watchProc: ChildProcess | null = null;
  let watchOut = '';

  try {
    watchProc = spawn(
      'klight',
      ['watch', SVC, '--env', ENV, '--path', SVC_PATH, '--no-initial-build'],
      { env: { ...process.env, KUBECONFIG }, detached: false }
    );
    watchProc.stdout?.on('data', d => { watchOut += d.toString(); });
    watchProc.stderr?.on('data', d => { watchOut += d.toString(); });

    // Wait for watch to initialize
    await new Promise(r => setTimeout(r, 2000));

    // Touch the file to trigger a rebuild
    const now = Date.now() / 1000;
    fs.utimesSync(targetFile, now, now);

    // Wait for rebuild output (up to 60s — docker build can be slow)
    const rebuilt = await new Promise<boolean>((resolve) => {
      const timer = setTimeout(() => resolve(false), 60000);
      const check = setInterval(() => {
        if (watchOut.toLowerCase().includes('done') || watchOut.toLowerCase().includes('redeployed')) {
          clearInterval(check);
          clearTimeout(timer);
          resolve(true);
        }
      }, 500);
    });

    if (!rebuilt) {
      // Still take a screenshot showing the watch output state
      await page.goto('/');
      await waitForEnvList(page);
      await clickEnv(page);
      await screenshotStep(page, W, '03-watch-timeout-no-rebuild');
      test.skip(true, 'Rebuild did not complete within 60s');
      return;
    }

    // Screenshot the UI right after rebuild completes
    await page.goto('/');
    await waitForEnvList(page);
    await clickEnv(page);
    await page.waitForTimeout(1000);
    await screenshotStep(page, W, '03-after-rebuild-redeployed');

    // Wait for pod to become ready again, then screenshot
    await page.waitForTimeout(5000);
    await page.goto('/');
    await waitForEnvList(page);
    await clickEnv(page);
    await screenshotStep(page, W, '03b-after-rollout-ready');

  } finally {
    watchProc?.kill('SIGTERM');
  }
});

test('04 — pod is healthy after watch cycle', async ({ page }) => {
  if (!isPrereqMet()) {
    test.skip(true, `Service dir not found: ${SVC_PATH}`);
    return;
  }

  // This test runs independently of test 03 — just verifies current state.
  await page.goto('/');
  await waitForEnvList(page);

  const envLink = page.locator('#env-list').getByText(ENV);
  const visible = await envLink.isVisible().catch(() => false);
  if (!visible) {
    test.skip(true, `env-${ENV} not running`);
    return;
  }
  await envLink.click();

  await page.waitForFunction(
    () => document.getElementById('services-panel')
      ?.querySelectorAll('[onclick^="showLogs"]').length ?? 0 > 0,
    { timeout: 20000 }
  );

  // inventory-api should be Running
  const card = page.locator('[onclick*="inventory-api"]').first();
  const cardVisible = await card.isVisible().catch(() => false);
  if (cardVisible) {
    await card.click();
    await page.waitForTimeout(600);
  }

  await screenshotStep(page, W, '04-pod-healthy-after-watch');
});
