import { defineConfig, devices } from '@playwright/test'

// Ports are overridable so the suite can run beside something already using the defaults.
const API_PORT = process.env.API_PORT ?? '8000'
const WEB_PORT = process.env.WEB_PORT ?? '5173'
const API_URL = `http://127.0.0.1:${API_PORT}`
const BASE_URL = `http://127.0.0.1:${WEB_PORT}`

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI ? 'list' : [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: BASE_URL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: `.venv/bin/uvicorn app.main:app --port ${API_PORT} --log-level warning`,
      cwd: '../backend',
      url: `${API_URL}/api/health`,
      reuseExistingServer: true,
      timeout: 60_000,
    },
    {
      command: `npm run dev -- --port ${WEB_PORT}`,
      url: BASE_URL,
      reuseExistingServer: true,
      timeout: 60_000,
      env: { API_URL },
    },
  ],
})
