#!/usr/bin/env node
// Aggregate e2e-report/metrics.ndjson into a human report (markdown + console).
//   node e2e/report.mjs [> e2e-report/SUMMARY.md]
import fs from 'node:fs'
import path from 'node:path'

const SINK = path.join(process.cwd(), 'e2e-report', 'metrics.ndjson')
if (!fs.existsSync(SINK)) { console.error('no metrics at', SINK, '— run `npm run e2e` first'); process.exit(1) }
const rows = fs.readFileSync(SINK, 'utf8').trim().split('\n').filter(Boolean).map((l) => JSON.parse(l))

const V = { good: '🟢', 'needs-work': '🟡', poor: '🔴', 'n/a': '⚪' }
const out = []
const p = (s) => out.push(s)

p('# OntoExplorer — Playwright performance & usability report\n')
p(`Generated ${new Date().toISOString()} · ${rows.length} measurements · target: ${process.env.E2E_BASE_URL || 'dev'}\n`)

// ── Page load / Web Vitals ──
const pages = rows.filter((r) => r.kind === 'page')
if (pages.length) {
  p('## Page load (Core Web Vitals)\n')
  p('| project | page | LCP | FCP | TTFB | CLS | wall | API p95 | reqs | JS KB |')
  p('|---|---|---|---|---|---|---|---|---|---|')
  for (const r of pages) {
    const vd = r.verdicts || {}
    p(`| ${r.project} | ${r.name} | ${fmt(r.lcp)} ${V[vd.lcp]||''} | ${fmt(r.fcp)} | ${fmt(r.ttfb)} ${V[vd.ttfb]||''} | ${r.cls ?? '—'} | ${r.wallMs}ms | ${r.api?.p95 ?? '—'}ms ${V[vd.apiP95]||''} | ${r.requests} | ${Math.round((r.jsBytes||0)/1024)} |`)
  }
  p('')
}

// ── Interaction timings ──
const inter = rows.filter((r) => ['treeRender', 'treeExpand', 'search', 'autocomplete'].includes(r.kind))
if (inter.length) {
  p('## Interaction latency\n')
  p('| project | kind | subject | ms | verdict |')
  p('|---|---|---|---|---|')
  for (const r of inter) p(`| ${r.project} | ${r.kind} | ${r.slug || r.term || ''} | ${r.ms}ms | ${V[r.verdict]||''} ${r.verdict||''} |`)
  p('')
}

// ── Slowest API endpoints ──
const apiSlow = pages.flatMap((r) => (r.api?.slowest || []).map((s) => ({ ...s, page: r.name }))).sort((a, b) => b.ms - a.ms).slice(0, 12)
if (apiSlow.length) {
  p('## Slowest API calls observed\n')
  p('| ms | status | path | on page |')
  p('|---|---|---|---|')
  for (const s of apiSlow) p(`| ${s.ms} | ${s.status} | ${s.path} | ${s.page} |`)
  p('')
}

// ── Accessibility ──
const a11y = rows.filter((r) => r.kind === 'a11y')
if (a11y.length) {
  p('## Accessibility (axe, WCAG 2.1 A/AA)\n')
  p('| project | page | total | critical | serious | moderate | minor |')
  p('|---|---|---|---|---|---|---|')
  for (const r of a11y) { const b = r.byImpact || {}; p(`| ${r.project} | ${r.page} | ${r.total} | ${b.critical||0} | ${b.serious||0} | ${b.moderate||0} | ${b.minor||0} |`) }
  const uniq = {}
  for (const r of a11y) for (const v of r.violations || []) uniq[v.id] = { impact: v.impact, help: v.help }
  if (Object.keys(uniq).length) { p('\n**Distinct violations:**'); for (const [id, v] of Object.entries(uniq)) p(`- \`${id}\` (${v.impact}) — ${v.help}`) }
  p('')
}

// ── Errors / responsive ──
const errs = rows.filter((r) => r.kind === 'errors' && ((r.consoleErrors||[]).length || (r.failedRequests||[]).length))
if (errs.length) { p('## Console errors / failed requests\n'); for (const r of errs) p(`- **${r.page}** (${r.project}): ${(r.failedRequests||[]).join(', ')} ${(r.consoleErrors||[]).slice(0,3).join(' | ')}`); p('') }
const overflow = rows.filter((r) => r.kind === 'responsive' && r.overflowPx > 2)
if (overflow.length) { p('## Responsive overflow (>2px at 400px)\n'); for (const r of overflow) p(`- ${r.page}: ${r.overflowPx}px`); p('') }

const report = out.join('\n')
console.log(report)
try { fs.writeFileSync(path.join(process.cwd(), 'e2e-report', 'SUMMARY.md'), report) } catch {}

function fmt(n) { return n == null ? '—' : `${n}ms` }
