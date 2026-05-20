/**
 * World 3 — Team with remote cluster (EKS / GKE / bare metal).
 *
 * Prerequisites:
 *   # DevOps runs once on the remote cluster:
 *   klight cluster setup-remote
 *
 *   # Dev receives the token and connects:
 *   klight connect --url https://dev.company.k8s --token eyJ...
 *   klight use klight-remote
 *   KUBECONFIG=<remote-kubeconfig> uvicorn server:app --port 7700
 *
 * Run:
 *   cd klight-ui && npm run screenshots:w3
 */

import { test } from '@playwright/test';
import { screenshotStep } from './helpers';

const W = 'world3-remote';
const REMOTE_URL = process.env.KLIGHT_REMOTE_URL;
const REMOTE_TOKEN = process.env.KLIGHT_REMOTE_TOKEN;

// Tests are placeholders until a remote cluster is configured

test('01 — klight cluster setup-remote (placeholder)', async ({ page }) => {
  test.skip(!REMOTE_URL || !REMOTE_TOKEN,
    'Set KLIGHT_REMOTE_URL and KLIGHT_REMOTE_TOKEN to run World 3 tests');
  // Steps:
  // 1. DevOps: klight cluster setup-remote  (on the remote cluster)
  // 2. Output shows: klight connect --url <url> --token <token>
  await page.goto('/');
  await screenshotStep(page, W, '01-setup-remote-done');
});

test('02 — klight connect (remote token)', async ({ page }) => {
  test.skip(!REMOTE_URL || !REMOTE_TOKEN, 'KLIGHT_REMOTE_URL and KLIGHT_REMOTE_TOKEN required');
  // klight connect --url $REMOTE_URL --token $REMOTE_TOKEN
  // klight use klight-remote
  await page.goto('/');
  await screenshotStep(page, W, '02-connected-to-remote');
});

test('03 — klight up against remote cluster', async ({ page }) => {
  test.skip(!REMOTE_URL || !REMOTE_TOKEN, 'KLIGHT_REMOTE_URL and KLIGHT_REMOTE_TOKEN required');
  // klight up store --env alice  (runs against remote klight-remote context)
  await page.goto('/');
  await screenshotStep(page, W, '03-klight-up-remote');
});

test('04 — Multiple devs on same cluster (isolated namespaces)', async ({ page }) => {
  test.skip(!REMOTE_URL || !REMOTE_TOKEN, 'KLIGHT_REMOTE_URL and KLIGHT_REMOTE_TOKEN required');
  // env-alice and env-bob both running on same remote cluster
  // Each dev only affects their own namespace
  await page.goto('/');
  await screenshotStep(page, W, '04-isolated-envs-remote');
});
