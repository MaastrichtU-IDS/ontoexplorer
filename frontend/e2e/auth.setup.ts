import { test as setup, expect } from '@playwright/test'
import { STORAGE_STATE } from './fixtures'
import fs from 'node:fs'
import path from 'node:path'

// Signs in once through the platform (Keycloak `ontoexplorer` realm) and saves the
// browser state so the authenticated dashboard specs can reuse the session. The
// app keeps its access token in memory and re-hydrates from an httpOnly refresh
// cookie on load, so saving cookies (storageState) is enough to stay signed in.
//
// Credentials come from the environment and are NEVER committed:
//   E2E_USER=<platform account> E2E_PASS=<password> npm run e2e
// Without them this setup writes an empty state and the dashboard-authenticated
// specs skip themselves — the rest of the suite still runs.
const USER = process.env.E2E_USER
const PASS = process.env.E2E_PASS

setup('authenticate', async ({ page }) => {
  fs.mkdirSync(path.dirname(STORAGE_STATE), { recursive: true })

  if (!USER || !PASS) {
    // Keep a valid (empty) state file so a stray context creation can't error.
    fs.writeFileSync(STORAGE_STATE, JSON.stringify({ cookies: [], origins: [] }))
    setup.skip(true, 'E2E_USER / E2E_PASS not set — dashboard-authenticated specs will skip')
    return
  }

  await page.goto('/login', { waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: /platform account/i }).click()

  // Keycloak login form (standard theme).
  await expect(page).toHaveURL(/keycloak.*\/realms\/ontoexplorer/, { timeout: 20_000 })
  await page.locator('#username').fill(USER)
  await page.locator('#password').fill(PASS)
  await page.locator('#kc-login').click()

  // Back in the app and authenticated: the guarded dashboard loads instead of
  // bouncing to /login.
  await page.waitForURL((u) => !/keycloak/.test(u.href), { timeout: 30_000 })
  await page.goto('/dashboard', { waitUntil: 'domcontentloaded' })
  await expect(page, 'sign-in did not establish a session (still redirected to /login)')
    .not.toHaveURL(/\/login/, { timeout: 20_000 })

  await page.context().storageState({ path: STORAGE_STATE })
})
