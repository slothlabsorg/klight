/**
 * World 1 — Solo dev with local monorepo.
 *
 * Prerequisites (not yet implemented):
 *   klight init     — detect monorepo, generate klight.yaml per service
 *   klight local build-load-all — build + load all local images
 *   KUBECONFIG=/tmp/klight-demo-kubeconfig.yaml uvicorn server:app --port 7700
 *
 * Run:
 *   cd klight-ui && npm run screenshots:w1
 */

import { test } from '@playwright/test';
import { screenshotStep } from './helpers';

const W = 'world1-local';

// All tests are placeholders until World 1 (local monorepo) is implemented
// Uncomment and implement when klight init + build-load-all are ready

test('01 — klight init (placeholder)', async ({ page }) => {
  test.skip(true, 'World 1 not yet implemented — needs: klight init for monorepo');
  // Steps:
  // 1. cd ~/dev/my-monorepo
  // 2. klight init → generates klight.yaml for each service
  // 3. klight local build-load-all → builds all Dockerfiles, loads into minikube
  await page.goto('/');
  await screenshotStep(page, W, '01-klight-init');
});

test('02 — klight up (local images)', async ({ page }) => {
  test.skip(true, 'World 1 not yet implemented');
  // Steps:
  // klight up all --env dev → uses :local images (imagePullPolicy: Never)
  await page.goto('/');
  await screenshotStep(page, W, '02-klight-up-local');
});

test('03 — Services running (local builds)', async ({ page }) => {
  test.skip(true, 'World 1 not yet implemented');
  await page.goto('/');
  await screenshotStep(page, W, '03-services-local-builds');
});

test('04 — Live reload (klight replace)', async ({ page }) => {
  test.skip(true, 'World 1 not yet implemented');
  // Steps:
  // Edit source → klight replace my-service --path . → pod restarts with new image
  await page.goto('/');
  await screenshotStep(page, W, '04-klight-replace-local');
});
