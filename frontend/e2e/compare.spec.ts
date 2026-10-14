import { test, expect, Page } from '@playwright/test'

// Coverage for the two compare surfaces and their shareable permalinks:
//  1. Cross-ontology compare at /ontologies?tab=compare (Compare.tsx)
//  2. Per-ontology version compare on the ontology page's History tab (HistoryTab)
// Run: E2E_BASE_URL=... npx playwright test compare --project=chromium

const SIO = {
  slug: 'sio',
  v162: '9d5610d8-7e05-45e5-919a-03512c64b8d9',
  v161: '187b8d93-8f1d-4c0a-b642-b9a101e7d78d',
}

// Wait for a terminal state so a hang is distinguishable from a result.
async function waitForDiffOutcome(page: Page) {
  const result = page.getByText(/\d+ added/i).first()
  const failed = page.getByText(/failed/i).first()
  await expect(result.or(failed)).toBeVisible({ timeout: 60_000 })
  return {
    hasResult: await result.isVisible().catch(() => false),
    hasFailed: await failed.isVisible().catch(() => false),
  }
}

// The cross-ontology page has both a "Compare" TAB and a "Compare" action button;
// the action button is rendered after the tab bar, so it's the last match.
function compareActionButton(page: Page) {
  return page.getByRole('button', { name: /^(compare|queuing…)$/i }).last()
}

// Pick SIO in the first still-unselected ontology picker. The option button's
// accessible name concatenates shortname + subtitle, so don't anchor on the
// shortname; scope to the open popup's options list (sibling of the search input).
async function pickSio(page: Page) {
  await page.getByRole('button', { name: /select an ontology/i }).first().click()
  const search = page.getByPlaceholder(/search ontologies/i)
  await search.fill('sio')
  await search.locator('xpath=../following-sibling::div').getByRole('button').first().click()
}

test.describe('cross-ontology compare', () => {
  test('shared URL renders a result, populates the pickers, and labels versions distinctly', async ({ page }) => {
    await page.goto(`/ontologies?tab=compare&from=${SIO.v161}&to=${SIO.v162}`)
    const outcome = await waitForDiffOutcome(page)
    expect(outcome.hasFailed, 'shared compare URL should not fail').toBeFalsy()
    expect(outcome.hasResult, 'shared compare URL should render a diff result').toBeTruthy()

    // Pickers must reflect the shared selection, not sit blank.
    await expect(page.getByRole('button', { name: /semanticscience integrated ontology/i }).first())
      .toBeVisible()

    // The diff labels (e.g. "Only in sio@v1.62") must carry the version number,
    // not the shared filename. The version IRI still appears in the dropdowns, so
    // scope to the "sio@…" label form the diff output uses.
    await expect(page.getByText(/sio@sio-release/i)).toHaveCount(0)
    await expect(page.getByText(/sio@v1\.6[12]/).first()).toBeVisible()
  })

  test('manual flow: same ontology twice auto-demotes From, yields a result, and offers a permalink', async ({ page }) => {
    await page.goto('/ontologies?tab=compare')
    await pickSio(page)
    await pickSio(page)
    const sameVersionHint = page.getByText(/different version on each side/i)
    await expect(sameVersionHint).toBeHidden({ timeout: 15_000 })
    const btn = compareActionButton(page)
    await expect(btn).toBeEnabled({ timeout: 15_000 })
    await btn.click()
    const outcome = await waitForDiffOutcome(page)
    expect(outcome.hasFailed).toBeFalsy()
    expect(outcome.hasResult).toBeTruthy()

    // A shareable link appears and the URL now carries the pair.
    await expect(page.getByRole('button', { name: /copy link/i })).toBeVisible()
    await expect(page).toHaveURL(/[?&]from=[^&]+&to=[^&]+/)
  })
})

test.describe('per-ontology history compare', () => {
  test('history tab yields a result, syncs the pair to the URL, and reloads stably', async ({ page }) => {
    await page.goto(`/ontologies/${SIO.slug}`)
    await page.getByRole('button', { name: /^history$/i }).click()
    const outcome = await waitForDiffOutcome(page)
    expect(outcome.hasFailed, 'default history diff should not fail').toBeFalsy()
    expect(outcome.hasResult, 'default history diff should render a result').toBeTruthy()

    // Opening the tab syncs the pair into the URL and offers a permalink.
    await expect(page).toHaveURL(/[?&]from=[^&]+&to=[^&]+/)
    await expect(page.getByRole('button', { name: /copy link/i })).toBeVisible()

    // The permalink reloads straight to the same diff.
    const permalink = page.url()
    await page.goto(permalink)
    const again = await waitForDiffOutcome(page)
    expect(again.hasResult, 'permalink reload should render the same diff').toBeTruthy()
  })

  test('deep-link with ?from=&to= opens the History tab directly', async ({ page }) => {
    await page.goto(`/ontologies/${SIO.slug}?from=${SIO.v161}&to=${SIO.v162}#history`)
    const outcome = await waitForDiffOutcome(page)
    expect(outcome.hasFailed).toBeFalsy()
    expect(outcome.hasResult, 'deep-linked history diff should render').toBeTruthy()
  })
})
