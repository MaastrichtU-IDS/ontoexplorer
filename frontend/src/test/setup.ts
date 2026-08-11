import '@testing-library/jest-dom'

// jsdom has no IntersectionObserver; components that lazily load on scroll
// (e.g. the individuals list sentinel) construct one. Provide a no-op stub so
// those components don't throw under test. Tests that need to drive it can grab
// the captured callback via (IntersectionObserver as any).mock.
class MockIntersectionObserver {
  constructor(_cb: IntersectionObserverCallback) {}
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() { return [] }
}
;(globalThis as unknown as { IntersectionObserver: unknown }).IntersectionObserver =
  MockIntersectionObserver as unknown as typeof IntersectionObserver

// jsdom has no ResizeObserver; recharts' ResponsiveContainer constructs one.
class MockResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
;(globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = MockResizeObserver

// jsdom doesn't implement scrollIntoView; keyboard nav / reveal call it.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function () {}
}
