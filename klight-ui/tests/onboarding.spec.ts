/**
 * Get started — role-based onboarding assistant.
 *
 * The /api/onboarding/probe call is intercepted with a mock response, so the
 * test runs without a real cluster. Exercises each role path and verifies the
 * assistant routes to the right workshop + commands.
 *
 * Run:
 *   cd klight-ui && npx playwright test onboarding.spec.ts
 */

import { test, expect, Page } from '@playwright/test';
import { waitForServer, screenshotStep } from './helpers';

const W = 'onboarding';

const MOCK_PROBE = {
  kubectl_access: true,
  local_cluster: true,
  has_team_yaml: true,
  team_name: 'mi-empresa',
  profiles: ['todo', 'backend-only'],
  active_target: 'local',
};

async function setupMocks(page: Page) {
  await page.route('/api/onboarding/probe', route => route.fulfill({ json: MOCK_PROBE }));
}

async function openAssistant(page: Page) {
  await setupMocks(page);
  await page.goto('/');
  await page.waitForLoadState('networkidle');
  await page.locator('#tb-start').click();
  await page.waitForSelector('#tab-start:not(.hidden)');
}

test.beforeAll(async () => {
  await waitForServer({ page: null } as any, 'http://localhost:7700').catch(() => {});
});

test('01 — Get started: role question + probe banner', async ({ page }) => {
  await openAssistant(page);
  // Probe banner reflects detected capabilities
  await expect(page.locator('#probe-banner')).toContainText('Detectado');
  await expect(page.locator('#probe-banner')).toContainText("team 'mi-empresa'");
  await expect(page.locator('#q-role')).toContainText('¿Qué eres?');
  await screenshotStep(page, W, '01-role-question');
});

test('02 — Developer path routes to dev-students (World 1)', async ({ page }) => {
  await openAssistant(page);
  await page.locator('#q-role button', { hasText: 'Desarrollador' }).click();
  await page.waitForSelector('#q-follow:not(.hidden)');
  await expect(page.locator('#q-follow-title')).toContainText('clonados localmente');

  await page.locator('#q-follow-opts button', { hasText: 'Sí, tengo los repos' }).click();
  await page.waitForSelector('#q-result:not(.hidden)');
  await expect(page.locator('#q-result-cmd')).toContainText('klight from-repos');
  await expect(page.locator('#q-result-link')).toHaveAttribute('href', /dev-students\/WORKSHOP\.md/);
  await screenshotStep(page, W, '02-dev-world1-result', { fullPage: true });
});

test('03 — Developer (no clones) routes to sync flow', async ({ page }) => {
  await openAssistant(page);
  await page.locator('#q-role button', { hasText: 'Desarrollador' }).click();
  await page.waitForSelector('#q-follow:not(.hidden)');
  await page.locator('#q-follow-opts button', { hasText: 'URL de klight-team.yaml' }).click();
  await page.waitForSelector('#q-result:not(.hidden)');
  await expect(page.locator('#q-result-cmd')).toContainText('klight sync');
});

test('04 — DevOps local path routes to Setup Wizard', async ({ page }) => {
  await openAssistant(page);
  await page.locator('#q-role button', { hasText: 'DevOps' }).click();
  await page.waitForSelector('#q-follow:not(.hidden)');
  await expect(page.locator('#q-follow-title')).toContainText('acceso a un cluster');

  await page.locator('#q-follow-opts button', { hasText: 'minikube local' }).click();
  await page.waitForSelector('#q-result:not(.hidden)');
  await expect(page.locator('#q-result-link')).toHaveAttribute('href', /devops-todo\/WORKSHOP\.md/);
  await expect(page.locator('#q-result-goto')).toContainText('Setup Wizard');
  await screenshotStep(page, W, '04-devops-local-result', { fullPage: true });
});

test('05 — Tech lead path skips follow-up and routes to polyglot demo', async ({ page }) => {
  await openAssistant(page);
  await page.locator('#q-role button', { hasText: 'Tech lead' }).click();
  await page.waitForSelector('#q-result:not(.hidden)');
  await expect(page.locator('#q-result-cmd')).toContainText('klight from-repos');
  await expect(page.locator('#q-result-link')).toHaveAttribute('href', /techlead-dropship\/WORKSHOP\.md/);
  await screenshotStep(page, W, '05-techlead-result', { fullPage: true });
});
