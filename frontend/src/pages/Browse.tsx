import { useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useOntologies } from '../hooks/useOntologies'
import { useVersions } from '../hooks/useVersions'
import ClassTree from '../components/ClassTree'
import TermPanel from '../components/TermPanel'
import ResizeHandle from '../components/ResizeHandle'
import { useIsMobile } from '../hooks/useIsMobile'

const PANE_MIN = 200
const PANE_MAX = 600
const PANE_DEFAULT = 280

export default function Browse() {
  const isMobile = useIsMobile()
  const { oid, vid } = useParams<{ oid: string; vid: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const { ontologies } = useOntologies()
  const { data: versionsData } = useVersions(oid)

  const selectedTermIri = searchParams.get('term')

  const [paneWidth, setPaneWidth] = useState<number>(() => {
    const stored = localStorage.getItem('browse-pane-width')
    return stored ? Number(stored) : PANE_DEFAULT
  })

  function handleDelta(delta: number) {
    setPaneWidth(w => {
      const next = Math.min(PANE_MAX, Math.max(PANE_MIN, w + delta))
      localStorage.setItem('browse-pane-width', String(next))
      return next
    })
  }

  const versions = versionsData?.versions ?? []
  const activeVid = vid ?? versions[0]?.id

  function selectTerm(iri: string) {
    setSearchParams({ term: iri })
  }

  return (
    <div style={{ display: 'flex', flexDirection: isMobile ? 'column' : 'row', height: 'calc(100vh - var(--nav-height))', overflow: 'hidden' }}>
      {/* Left pane */}
      <div style={{
        width: isMobile ? '100%' : paneWidth, flexShrink: 0,
        maxHeight: isMobile ? '45vh' : undefined,
        display: 'flex', flexDirection: 'column',
        background: 'var(--bg-secondary)',
        borderRight: isMobile ? 'none' : '1px solid var(--border)',
        borderBottom: isMobile ? '1px solid var(--border)' : 'none',
        overflow: 'hidden',
      }}>
        {/* Ontology list */}
        <div style={{ padding: '10px', borderBottom: '1px solid var(--border)' }}>
          <div style={{ color: 'var(--text-dim)', fontSize: 11, textTransform: 'uppercase', marginBottom: 6 }}>
            Ontologies
          </div>
          <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 2, maxHeight: 200, overflowY: 'auto' }}>
            {ontologies.map(o => (
              <li
                key={o.id}
                onClick={() => navigate(`/browse/${o.id}/${versions[0]?.id ?? 'latest'}`)}
                style={{
                  padding: '4px 8px', borderRadius: 'var(--radius-sm)', cursor: 'pointer',
                  background: oid === o.id ? 'var(--bg-hover)' : 'transparent',
                  color: oid === o.id ? 'var(--accent)' : 'var(--text-muted)',
                  fontSize: 'var(--font-size-sm)',
                }}
                onMouseEnter={e => { if (oid !== o.id) e.currentTarget.style.background = 'var(--overlay)' }}
                onMouseLeave={e => { if (oid !== o.id) e.currentTarget.style.background = '' }}
              >
                {o.id}
              </li>
            ))}
          </ul>
        </div>

        {/* Version selector */}
        {oid && versions.length > 1 && (
          <div style={{ padding: '6px 10px', borderBottom: '1px solid var(--border)' }}>
            <select
              value={activeVid}
              onChange={e => navigate(`/browse/${oid}/${e.target.value}`)}
              style={{ width: '100%', fontSize: 'var(--font-size-sm)' }}
            >
              {versions.map(v => (
                <option key={v.id} value={v.id}>{v.id}</option>
              ))}
            </select>
          </div>
        )}

        {/* Class tree */}
        {oid && activeVid ? (
          <ClassTree
            ontologyId={oid}
            versionId={activeVid}
            selectedIri={selectedTermIri}
            onSelect={selectTerm}
            revealIri={selectedTermIri}
          />
        ) : (
          <div style={{ padding: '1rem', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
            Select an ontology to browse
          </div>
        )}
      </div>

      {/* Resize handle */}
      {!isMobile && <ResizeHandle onDelta={handleDelta} />}

      {/* Right pane */}
      <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {oid && activeVid && selectedTermIri ? (
          <TermPanel ontologyId={oid} versionId={activeVid} termIri={selectedTermIri} slug={oid}
            versionReasoner={versions.find(v => v.id === activeVid)?.reasoner} />
        ) : (
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            height: '100%', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)',
          }}>
            {oid ? 'Click a class in the tree to see its details' : 'Select an ontology from the left'}
          </div>
        )}
      </div>
    </div>
  )
}
