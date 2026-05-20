import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  outputDir: './tests/screenshots',
  use: {
    baseURL: process.env.KLIGHT_URL || 'http://localhost:7700',
    screenshot: 'on',
    video: 'off',
    viewport: { width: 1440, height: 900 },
  },
  // Single worker — we're taking screenshots, not running in parallel
  workers: 1,
  reporter: [['list'], ['html', { outputFolder: 'tests/report', open: 'never' }]],
});
