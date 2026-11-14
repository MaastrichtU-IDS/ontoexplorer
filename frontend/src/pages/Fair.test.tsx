import { render, screen, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import FairOverview from './Fair'

const FLEET = {
  n: 2015,
  overall_histogram: [
    { bucket: '<50', count: 72 },
    { bucket: '50-69', count: 318 },
    { bucket: '70-84', count: 790 },
    { bucket: '85-100', count: 835 },
  ],
  principle_means: { F: 0.79, A: 0.74, I: 0.86, R: 0.63 },
  check_pass_rate: [
    { id: 'I1', principle: 'I', name: 'Formal language tier', rate: 1.0 },
    { id: 'R6', principle: 'R', name: 'Terms carry definitions', rate: 0.61 },
  ],
}

const fleetFn = vi.fn(() => Promise.resolve(FLEET))

vi.mock('../lib/api', () => ({
  api: { fair: { fleet: (...args: unknown[]) => (fleetFn as any)(...args) } },
}))

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  fleetFn.mockImplementation(() => Promise.resolve(FLEET))
})

test('renders fleet size, principle means, and per-check rates', async () => {
  wrap(<FairOverview />)
  const root = await screen.findByTestId('fair-overview')
  expect(within(root).getByText('2015')).toBeInTheDocument()
  // I1 pass rate 100%
  const i1 = screen.getByTestId('fair-rate-I1')
  expect(within(i1).getByText('100%')).toBeInTheDocument()
  // R6 at 61%
  const r6 = screen.getByTestId('fair-rate-R6')
  expect(within(r6).getByText('61%')).toBeInTheDocument()
})

test('shows a failure message when the fleet query errors', async () => {
  fleetFn.mockImplementationOnce(() => Promise.reject(new Error('boom')))
  wrap(<FairOverview />)
  expect(await screen.findByText(/Failed to load fleet FAIR data/i)).toBeInTheDocument()
})
