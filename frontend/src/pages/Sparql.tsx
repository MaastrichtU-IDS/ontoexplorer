import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import Yasgui from '@triply/yasgui'
import '@triply/yasgui/build/yasgui.min.css'
import './Sparql.css'
import QuerySidebar from '../components/QuerySidebar'
import { api } from '../lib/api'
import { ScopeToolbar } from '../components/sparql/ScopeToolbar'
import { hasPrefix, prependPrefix, extractBaseIri } from '../components/sparql/prefixUtils'
import { useOntologies } from '../hooks/useOntologies'
import { buildOntoCompleter } from '../components/sparql/ontoCompleter'
import { installIriClickHandler } from '../components/sparql/iriClickHandler'
import { collectIris, buildLabelsQuery, applyLabels, removeLabels } from '../components/sparql/labelEnricher'
import type { Ontology, OntologyVersion } from '../lib/api'
import { DiffQueryView } from '../components/sparql/DiffQueryView'
import { endpointForVersion } from '../components/sparql/scopeUrls'
import type { BindingRow } from '../components/sparql/diffBindings'
import type { DiffScope } from '../components/sparql/ScopeToolbar'
import type { ReasoningMode } from '../components/sparql/scopeUrls'

const DEFAULT_QUERY = `PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT DISTINCT ?class ?label WHERE {
  GRAPH ?g {
    ?class a owl:Class .
    OPTIONAL { ?class rdfs:label ?label }
  }
}
LIMIT 10`

// ── Page ──────────────────────────────────────────────────────────────────────

export default function Sparql() {
  const containerRef = useRef<HTMLDivElement>(null)
  const yasguiRef = useRef<InstanceType<typeof Yasgui> | null>(null)
  const selectedOntologyIdsRef = useRef<string[]>([])
  const ontologiesRef = useRef<Ontology[]>([])
  const location = useLocation()
  const navigate = useNavigate()
  const [queryError, setQueryError] = useState<string | null>(null)
  const { ontologies } = useOntologies()
  const [labelsOn, setLabelsOn] = useState(false)
  const labelsOnRef = useRef(false)
  useEffect(() => { labelsOnRef.current = labelsOn }, [labelsOn])

  const [diffScope, setDiffScope] = useState<DiffScope | null>(null)
  const diffScopeRef = useRef<DiffScope | null>(null)
  useEffect(() => { diffScopeRef.current = diffScope }, [diffScope])

  const [diffResult, setDiffResult] = useState<{
    from: BindingRow[]
    to: BindingRow[]
    fromError: string | null
    toError: string | null
  } | null>(null)
  const diffAbortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    if (!containerRef.current || yasguiRef.current) return

    const Yasqe = (Yasgui as any).Yasqe
    if (Yasqe?.registerAutocompleter) {
      Yasqe.registerAutocompleter(
        buildOntoCompleter(
          () => selectedOntologyIdsRef.current,
          () => ontologiesRef.current,
        ),
      )
    }

    yasguiRef.current = new Yasgui(containerRef.current, {
      persistenceId: null,
      requestConfig: {
        endpoint: '/api/v1/sparql/content',
        method: 'POST',
        acceptHeaderSelect: 'application/sparql-results+json',
        acceptHeaderGraph: 'text/turtle',
      },
      endpointCatalogueOptions: {
        getData: () => [
          { endpoint: '/api/v1/sparql/content', title: 'OntoExplorer — Ontology Content' },
        ],
      },
    } as any)

    const teardownClickHandler = containerRef.current
      ? installIriClickHandler(containerRef.current, {
          getOntologies: () => ontologiesRef.current,
          navigate,
        })
      : () => {}

    const yasr = yasguiRef.current?.getTab()?.getYasr()
    if (yasr && typeof yasr.on === 'function') {
      yasr.on('drawn', () => {
        if (labelsOnRef.current) runLabelEnrichment()
      })
    }

    const yasqeForQuery = yasguiRef.current?.getTab()?.getYasqe() as any
    if (yasqeForQuery && typeof yasqeForQuery.on === 'function') {
      yasqeForQuery.on('query', (req: any) => {
        const scope = diffScopeRef.current
        if (!scope) return
        try { req?.abort?.() } catch { /* superagent abort can be noisy */ }
        void runDiffQuery(yasqeForQuery.getValue() ?? '', scope)
      })
    }

    const qId = new URLSearchParams(location.search).get('q')
    if (qId) {
      api.savedQueries.get(qId)
        .then(sq => {
          yasguiRef.current?.getTab()?.getYasqe()?.setValue(sq.query_text)
        })
        .catch(() => {
          setQueryError('Query not found or not accessible')
          yasguiRef.current?.getTab()?.getYasqe()?.setValue(DEFAULT_QUERY)
        })
    } else {
      yasguiRef.current.getTab()?.getYasqe()?.setValue(DEFAULT_QUERY)
    }

    return () => {
      teardownClickHandler()
      if (yasguiRef.current) {
        if (typeof yasguiRef.current.destroy === 'function') {
          yasguiRef.current.destroy()
        } else if (containerRef.current) {
          containerRef.current.innerHTML = ''
        }
        yasguiRef.current = null
      }
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Keep ontologiesRef in sync with fetched ontologies for the autocompleter.
  useEffect(() => {
    ontologiesRef.current = ontologies
  }, [ontologies])

  // Stable handler refs so the toolbar's onScopeChange effect doesn't refire
  // every time this component re-renders (e.g. queryError changes).
  const handleScopeChange = useCallback((endpoint: string) => {
    yasguiRef.current?.getTab()?.setEndpoint(endpoint)
  }, [])

  const handleCopy = useCallback((fromBlock: string) => {
    const current = yasguiRef.current?.getTab()?.getYasqe()?.getValue() ?? ''
    const text = fromBlock ? `${fromBlock}${current}` : current
    navigator.clipboard?.writeText(text)?.catch(() => {})
  }, [])

  const handleSelectionChange = useCallback((ids: string[]) => {
    selectedOntologyIdsRef.current = ids
  }, [])

  const handleOntologyAdded = useCallback((ontologyId: string) => {
    const onto = ontologies.find(o => o.id === ontologyId)
    if (!onto) return
    const shortname = onto.shortname || onto.iri.replace(/[/#]+$/, '').split(/[/#]/).pop() || 'ns'
    const baseIri = extractBaseIri(onto.iri)
    const yasqe = yasguiRef.current?.getTab()?.getYasqe()
    if (!yasqe) return
    const current = yasqe.getValue() ?? ''
    if (hasPrefix(current, shortname)) return
    yasqe.setValue(prependPrefix(current, shortname, baseIri))
  }, [ontologies])

  const runLabelEnrichment = useCallback(async () => {
    const root = containerRef.current
    if (!root) return
    const iris = collectIris(root)
    if (iris.length === 0) return
    const endpoint = (() => {
      const cfg = yasguiRef.current?.getTab()?.getRequestConfig()
      const raw = cfg?.endpoint
      if (typeof raw === 'string') return raw
      return '/api/v1/sparql/content'
    })()
    try {
      const resp = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
          'Accept': 'application/sparql-results+json',
        },
        body: `query=${encodeURIComponent(buildLabelsQuery(iris))}`,
      })
      if (!resp.ok) return
      const data = await resp.json()
      const labels = new Map<string, string>()
      for (const b of data?.results?.bindings ?? []) {
        const iri = b?.iri?.value
        const lbl = b?.label?.value
        if (iri && lbl && !labels.has(iri)) labels.set(iri, lbl)
      }
      if (containerRef.current) applyLabels(containerRef.current, labels)
    } catch {
      // Silent fallback: labels aren't critical
    }
  }, [])

  const handleLabelsToggle = useCallback((enabled: boolean) => {
    setLabelsOn(enabled)
    if (!containerRef.current) return
    if (enabled) {
      runLabelEnrichment()
    } else {
      removeLabels(containerRef.current)
    }
  }, [runLabelEnrichment])

  const runDiffQuery = useCallback(async (query: string, scope: DiffScope) => {
    if (diffAbortRef.current) diffAbortRef.current.abort()
    const ac = new AbortController()
    diffAbortRef.current = ac

    async function fetchSide(side: { version: OntologyVersion; mode: ReasoningMode }): Promise<{ bindings: BindingRow[]; error: string | null }> {
      try {
        const resp = await fetch(endpointForVersion(side.version, side.mode), {
          method: 'POST',
          signal: ac.signal,
          headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/sparql-results+json',
          },
          body: `query=${encodeURIComponent(query)}`,
        })
        if (!resp.ok) return { bindings: [], error: `HTTP ${resp.status}` }
        const data = await resp.json()
        if (!data?.head?.vars) {
          return { bindings: [], error: 'Diff mode supports SELECT queries only' }
        }
        return { bindings: data.results?.bindings ?? [], error: null }
      } catch (e) {
        if ((e as Error).name === 'AbortError') return { bindings: [], error: 'aborted' }
        return { bindings: [], error: e instanceof Error ? e.message : 'fetch failed' }
      }
    }

    const [fromResp, toResp] = await Promise.all([
      fetchSide(scope.from),
      fetchSide(scope.to),
    ])

    if (ac.signal.aborted) return

    setDiffResult({
      from: fromResp.bindings,
      to: toResp.bindings,
      fromError: fromResp.error,
      toError: toResp.error,
    })
  }, [])

  // Hide the native Yasr pane when in diff mode.
  useEffect(() => {
    const yasrEl = containerRef.current?.querySelector('.yasr') as HTMLElement | null
    if (yasrEl) yasrEl.style.display = diffScope ? 'none' : ''
  }, [diffScope])

  // Clear stale diffResult when exiting diff mode.
  useEffect(() => {
    if (!diffScope) setDiffResult(null)
  }, [diffScope])

  return (
    <div style={{
      height: 'calc(100vh - var(--nav-height))',
      display: 'flex', flexDirection: 'column', overflow: 'hidden',
      background: 'var(--bg)',
    }}>
      <div style={{
        padding: '0.6rem 1.5rem', borderBottom: '1px solid var(--border)',
        background: 'var(--bg-secondary)', flexShrink: 0,
        display: 'flex', alignItems: 'baseline', gap: '0.75rem',
      }}>
        <h1 style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text)' }}>SPARQL</h1>
        <span style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)' }}>
          Query the full ontology graph · read-only · SPARQL 1.1
        </span>
      </div>
      <ScopeToolbar
        onScopeChange={handleScopeChange}
        onCopy={handleCopy}
        onOntologyAdded={handleOntologyAdded}
        onSelectionChange={handleSelectionChange}
        onLabelsToggle={handleLabelsToggle}
        onDiffScopeChange={setDiffScope}
      />
      {queryError && (
        <div style={{
          padding: '0.4rem 1.5rem', background: 'rgba(239,68,68,0.1)',
          borderBottom: '1px solid rgba(239,68,68,0.3)',
          color: '#f87171', fontSize: 'var(--font-size-sm)', flexShrink: 0,
        }}>{queryError}</div>
      )}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'row', overflow: 'hidden', minHeight: 0 }}>
        <QuerySidebar yasguiRef={yasguiRef} />
        <div style={{ flex: 1, minHeight: 0, position: 'relative' }}>
          <div ref={containerRef} data-testid="yasgui-container" style={{
            height: '100%', overflowY: 'auto',
          }} />
          {diffScope && diffResult && (
            <div style={{
              position: 'absolute', left: 0, right: 0, bottom: 0,
              top: '50%',
              background: 'var(--bg)', borderTop: '2px solid var(--border)',
              overflow: 'hidden',
            }}>
              <DiffQueryView
                from={diffResult.from}
                to={diffResult.to}
                fromError={diffResult.fromError}
                toError={diffResult.toError}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
