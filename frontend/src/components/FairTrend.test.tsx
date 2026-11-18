import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import FairTrend from './FairTrend'

const historyFn = vi.fn()

vi.mock('../lib/api', () => ({
  api: { fair: { history: (...a: unknown[]) => (historyFn as any)(...a) } },
}))

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

test('shows the accumulating note with fewer than two snapshots', async () => {
  historyFn.mockResolvedValue({
    series: [{ day: '2026-11-18', n: 10, overall_mean: 0.7, overall_stddev: 0.1, principle_means: {}, principle_stddevs: {} }],
  })
  wrap(<FairTrend />)
  expect(await screen.findByText(/fairness trend appears once/i)).toBeInTheDocument()
})

test('renders a trend chart with two or more snapshots', async () => {
  historyFn.mockResolvedValue({
    series: [
      { day: '2026-11-17', n: 10, overall_mean: 0.70, overall_stddev: 0.10, principle_means: { F: 0.7, A: 0.7, I: 0.8, R: 0.5 }, principle_stddevs: {} },
      { day: '2026-11-18', n: 11, overall_mean: 0.74, overall_stddev: 0.12, principle_means: { F: 0.7, A: 0.76, I: 0.83, R: 0.55 }, principle_stddevs: {} },
    ],
  })
  wrap(<FairTrend />)
  expect(await screen.findByRole('img', { name: /fleet fair score over time/i })).toBeInTheDocument()
  expect(screen.getByText('Overall')).toBeInTheDocument()
  expect(screen.getByText('Reusable')).toBeInTheDocument()
})
