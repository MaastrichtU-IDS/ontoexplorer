import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Stats from './Stats'

const { mockUsagePublic } = vi.hoisted(() => ({ mockUsagePublic: vi.fn() }))

vi.mock('../lib/api', async () => {
  const actual = await vi.importActual('../lib/api')
  return {
    ...actual,
    api: {
      ...(actual as any).api,
      stats: {
        get: vi.fn().mockResolvedValue({
          total_ontologies: 3, total_versions: 5, storage_bytes: 0,
          uploads_per_month: [], queries_per_month: [], job_durations: [],
        }),
        usagePublic: mockUsagePublic,
      },
    },
  }
})

// recharts' ResponsiveContainer needs a non-zero layout size in jsdom.
beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, 'offsetWidth', { configurable: true, value: 800 })
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', { configurable: true, value: 300 })
})

function wrap() {
  const qc = new QueryClient()
  return render(<QueryClientProvider client={qc}><Stats /></QueryClientProvider>)
}

describe('Stats usage section', () => {
  it('shows both unique and total for views and downloads, and toggles granularity', async () => {
    mockUsagePublic.mockResolvedValue({
      granularity: 'month',
      totals: { views: { unique: 1240, total: 3010 }, downloads: { unique: 88, total: 205 } },
      trend: [{ period: '2026-07', view_unique: 1240, view_total: 3010, download_unique: 88, download_total: 205 }],
    })

    wrap()

    expect(await screen.findByText('Views')).toBeInTheDocument()
    // "Show both": unique headline + total alongside (one <p>, split spans).
    // Comma-agnostic (toLocaleString separators vary by the test env's ICU).
    const pWith = (needle: string) => (_: string, el: Element | null) =>
      el?.tagName === 'P' && (el.textContent ?? '').replace(/,/g, '').includes(needle)
    expect(await screen.findByText(pWith('1240 / 3010 total'))).toBeInTheDocument()
    expect(screen.getByText(pWith('88 / 205 total'))).toBeInTheDocument()

    // Default granularity is month.
    await waitFor(() => expect(mockUsagePublic).toHaveBeenCalledWith('month', 12))

    // Toggling to year re-queries.
    fireEvent.click(screen.getByRole('button', { name: 'year' }))
    await waitFor(() => expect(mockUsagePublic).toHaveBeenCalledWith('year', 12))
  })
})
