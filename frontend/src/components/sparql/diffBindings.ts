/** A single binding value as returned in SPARQL Protocol JSON results. */
export interface BindingValue {
  type: 'uri' | 'literal' | 'bnode'
  value: string
  'xml:lang'?: string
  datatype?: string
}

/** One row of SPARQL bindings — a map from variable name to value. */
export type BindingRow = Record<string, BindingValue>

export interface DiffResult {
  onlyFrom: BindingRow[]
  onlyTo: BindingRow[]
  both: BindingRow[]
  vars: string[]
}

/**
 * Produce a stable string key for a binding row. Two rows with the same
 * bindings (modulo variable insertion order) yield the same key. Different
 * types / langs / datatypes produce different keys even when `value` matches.
 *
 * Note: a missing variable is distinguishable from a present binding because
 * variable names are part of the canonical key.
 */
export function canonicalRow(row: BindingRow): string {
  const keys = Object.keys(row).sort()
  const parts = keys.map(k => {
    const v = row[k]
    const lang = v['xml:lang'] ?? ''
    const dt = v.datatype ?? ''
    return `${k}\x01${v.type}\x02${v.value}\x03${lang}\x04${dt}`
  })
  return parts.join('\x1f')
}

/**
 * Set-diff two SPARQL binding lists. Returns three buckets (only-on-from-side,
 * only-on-to-side, present-on-both) plus the union of variable names.
 *
 * Order preservation:
 *   - `both` preserves From-side order (so the user sees them as they appeared
 *     in the From-side response).
 *   - `onlyFrom` / `onlyTo` preserve their respective side's order.
 */
export function diffBindings(from: BindingRow[], to: BindingRow[]): DiffResult {
  const fromKeys = new Set(from.map(canonicalRow))
  const toKeys = new Set(to.map(canonicalRow))

  const onlyFrom: BindingRow[] = []
  const both: BindingRow[] = []
  for (const r of from) {
    if (toKeys.has(canonicalRow(r))) both.push(r)
    else onlyFrom.push(r)
  }

  const onlyTo: BindingRow[] = []
  for (const r of to) {
    if (!fromKeys.has(canonicalRow(r))) onlyTo.push(r)
  }

  const varSet = new Set<string>()
  for (const r of from) for (const k of Object.keys(r)) varSet.add(k)
  for (const r of to) for (const k of Object.keys(r)) varSet.add(k)

  return { onlyFrom, onlyTo, both, vars: Array.from(varSet).sort() }
}
