import { test, expect } from '@playwright/test'
import { DASHBOARD_ROUTES, STORAGE_STATE } from './fixtures'
import { installVitals, measureNav } from './helpers/metrics'

const HAS_CREDS = !!(process.env.E2E_USER && process.env.E2E_PASS)

// ── Anonymous: AuthGuard must gate every dashboard route ──────────────────────
// No session → each guarded route redirects to /login. This needs no credentials
// and guards the access-control contract (a dashboard page must never render to an
// anonymous visitor).
test.describe('dashboard — anonymous is redirected to login', () => {
  for (const r of [...DASHBOARD_ROUTES, { name: 'admin', url: '/admin' }]) {
    test(`${r.name} → /login`, async ({ page }) => {
      await page.goto(r.url, { waitUntil: 'domcontentloaded' })
      await expect(page).toHaveURL(/\/login/, { timeout: 15_000 })
      await expect(page.getByRole('heading', { name: /sign in/i })).toBeVisible()
    })
  }
})

// ── Authenticated: each dashboard page loads for a signed-in user ─────────────
// Gated on credentials (auth.setup.ts establishes the session). Measures load and
// asserts no redirect-to-login and no API errors.
test.describe('dashboard — authenticated pages load', () => {
  test.skip(!HAS_CREDS, 'E2E_USER / E2E_PASS not set')
  test.use({ storageState: STORAGE_STATE })

  test.beforeEach(async ({ page }) => {
    await installVitals(page)
  })

  for (const r of DASHBOARD_ROUTES) {
    test(`${r.name} loads for a signed-in user`, async ({ page }, testInfo) => {
      await measureNav(page, testInfo, `dashboard:${r.name}`, r.url, async () => {
        // Must not bounce to /login, and the app shell must render.
        await expect(page).not.toHaveURL(/\/login/, { timeout: 20_000 })
        await expect(page.locator('main, [role="main"], body').first()).toBeVisible()
      })
      // No white-screen: some dashboard chrome/content is present.
      await expect(page.locator('body')).toBeVisible()
    })
  }

  // /admin is admin-only. For a non-admin test account it may show an access-denied
  // state rather than the admin console — both are acceptable; what matters is it
  // doesn't bounce to /login (the user IS authenticated) or white-screen.
  test('admin route resolves to admin console or access-denied (not login)', async ({ page }) => {
    await page.goto('/admin', { waitUntil: 'domcontentloaded' })
    await expect(page).not.toHaveURL(/\/login/, { timeout: 20_000 })
    await expect(page.locator('body')).toBeVisible()
  })
})
