import { useEffect, useState } from 'react'

/**
 * Returns a value that lags `value` by `ms` milliseconds.
 *
 * Useful for live-search inputs: the user types fast, but we only want to
 * fire a network request after they've paused. Updates are reset every time
 * the source value changes within the debounce window.
 */
export function useDebounced<T>(value: T, ms = 200): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return debounced
}
