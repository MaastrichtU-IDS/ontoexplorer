import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import Yasgui from '@triply/yasgui'
import '@triply/yasgui/build/yasgui.min.css'
import './Sparql.css'
import QuerySidebar from '../components/QuerySidebar'
import { api } from '../lib/api'
import { ScopeToolbar } from '../components/sparql/ScopeToolbar'
import { hasPrefix, prependPrefix, extractBaseIri } from '../components/sparql/prefixUtils'
import { useOntologies } from '../hooks/useOntologies'
import { buildOntoCompleter } from '../components/sparql/ontoCompleter'
import type { Ontology } from '../lib/api'

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
  const [queryError, setQueryError] = useState<string | null>(null)
  const { ontologies } = useOntologies()

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
        <div ref={containerRef} style={{ flex: 1, minHeight: 0, overflowY: 'auto' }} />
      </div>
    </div>
  )
}
