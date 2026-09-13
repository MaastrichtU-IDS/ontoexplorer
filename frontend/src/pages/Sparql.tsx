import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import Yasgui from '@triply/yasgui'
import '@triply/yasgui/build/yasgui.min.css'
import './Sparql.css'
import QuerySidebar from '../components/QuerySidebar'
import { useIsMobile } from '../hooks/useIsMobile'
import { api } from '../lib/api'
import { ScopeToolbar } from '../components/sparql/ScopeToolbar'
import { hasPrefix, prependPrefix, extractBaseIri } from '../components/sparql/prefixUtils'
import { useOntologies } from '../hooks/useOntologies'
import { buildOntoCompleter } from '../components/sparql/ontoCompleter'
import { installIriClickHandler } from '../components/sparql/iriClickHandler'
import { collectIris, buildLabelsQuery, applyLabels, removeLabels } from '../components/sparql/labelEnricher'
import type { Ontology, OntologyVersion } from '../lib/api'
import { DiffQueryView } from '../components/sparql/DiffQueryView'
import { endpointForVersion, formatScopeAsFromClauses, stripManagedFromClauses } from '../components/sparql/scopeUrls'
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
  const isMobile = useIsMobile()
  const containerRef = useRef<HTMLDivElement>(null)
  const resultsWrapperRef = useRef<HTMLDivElement>(null)
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
    fromIsSelect: boolean
    toIsSelect: boolean
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

    const teardownClickHandler = resultsWrapperRef.current
      ? installIriClickHandler(resultsWrapperRef.current, {
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
      yasqeForQuery.on('query', (_req: any) => {
        const scope = diffScopeRef.current
        if (!scope) return
        // Don't abort Yasr's bound fetch — let it render the From-side
        // response natively. We'll hide it via display:none if the diff is
        // renderable; otherwise (non-SELECT, error) the user sees Yasr.
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

  // The editor's managed FROM clauses are kept in sync with chip state via
  // handleScopeGraphsChange, so the editor already contains the correct
  // FROM/FROM NAMED list. Copy just snapshots whatever's in the editor.
  const handleCopy = useCallback((_fromBlock: string) => {
    const current = yasguiRef.current?.getTab()?.getYasqe()?.getValue() ?? ''
    navigator.clipboard?.writeText(current)?.catch(() => {})
  }, [])

  // Keep the editor's managed FROM/FROM NAMED clauses (those using our
  // `urn:ontology:` IRI scheme) in sync with the ScopeToolbar's chip
  // selection. Hand-written FROM clauses with other IRI patterns are left
  // alone. In Diff mode this fires with [] so any stale managed FROM lines
  // get stripped (Diff mode scopes via URL params instead).
  const handleScopeGraphsChange = useCallback((graphIris: string[]) => {
    const yasqe = yasguiRef.current?.getTab()?.getYasqe()
    if (!yasqe) return
    const current = yasqe.getValue() ?? ''
    const stripped = stripManagedFromClauses(current)
    const block = formatScopeAsFromClauses(graphIris)
    const next = block + stripped
    if (next !== current) yasqe.setValue(next)
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

    async function fetchSide(side: { version: OntologyVersion; mode: ReasoningMode }): Promise<{ bindings: BindingRow[]; error: string | null; isSelect: boolean }> {
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
        if (!resp.ok) return { bindings: [], error: `HTTP ${resp.status}`, isSelect: false }
        const data = await resp.json()
        // SELECT responses carry `head.vars`. CONSTRUCT / DESCRIBE / ASK do not.
        if (!data?.head?.vars) {
          return { bindings: [], error: null, isSelect: false }
        }
        return { bindings: data.results?.bindings ?? [], error: null, isSelect: true }
      } catch (e) {
        if ((e as Error).name === 'AbortError') return { bindings: [], error: 'aborted', isSelect: false }
        return { bindings: [], error: e instanceof Error ? e.message : 'fetch failed', isSelect: false }
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
      fromIsSelect: fromResp.isSelect,
      toIsSelect: toResp.isSelect,
    })
  }, [])

  // Hide the native Yasr pane only when a renderable diff is on screen
  // (both sides returned SELECT bindings). In Diff mode with a non-SELECT
  // response (or before any results are in), leave Yasr visible so the user
  // sees the From-side query result natively.
  const diffRenderable = !!(
    diffScope &&
    diffResult &&
    diffResult.fromIsSelect &&
    diffResult.toIsSelect
  )
  useEffect(() => {
    const yasrEl = containerRef.current?.querySelector('.yasr') as HTMLElement | null
    if (yasrEl) yasrEl.style.display = diffRenderable ? 'none' : ''
  }, [diffRenderable])

  // Clear stale diffResult when exiting diff mode.
  useEffect(() => {
    if (!diffScope) {
      diffAbortRef.current?.abort()
      setDiffResult(null)
    }
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
        onScopeGraphsChange={handleScopeGraphsChange}
      />
      {queryError && (
        <div style={{
          padding: '0.4rem 1.5rem', background: 'rgba(239,68,68,0.1)',
          borderBottom: '1px solid rgba(239,68,68,0.3)',
          color: 'var(--red-soft)', fontSize: 'var(--font-size-sm)', flexShrink: 0,
        }}>{queryError}</div>
      )}
      <div style={{ flex: 1, display: 'flex', flexDirection: isMobile ? 'column' : 'row', overflow: isMobile ? 'auto' : 'hidden', minHeight: 0 }}>
        <QuerySidebar yasguiRef={yasguiRef} />
        <div ref={resultsWrapperRef} style={{ flex: 1, minHeight: 0, position: 'relative' }}>
          <div ref={containerRef} data-testid="yasgui-container" style={{
            height: '100%', overflowY: 'auto',
          }} />
          {diffRenderable && diffResult && (
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
          {diffScope && diffResult && !diffRenderable && (
            <div style={{
              position: 'absolute', left: 0, right: 0, top: 0,
              background: 'rgba(229,192,123,0.10)', borderBottom: '1px solid rgba(229,192,123,0.35)',
              color: 'var(--od-yellow)', padding: '6px 12px', fontSize: 12, zIndex: 5,
            }}>
              Diff mode supports SELECT queries only. Showing the From-side response natively.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
