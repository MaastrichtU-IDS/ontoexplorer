import { useState } from 'react'
import { useOntologyProfile, useProfileCandidates, usePatchProfile, useDetectProfile } from '../hooks/useOntologyProfile'
import { OntologyProfileData, ProfileCandidates } from '../lib/api'

const CURATED_LABELS: Record<string, string> = {
  'http://www.w3.org/2000/01/rdf-schema#label': 'rdfs:label',
  'http://www.w3.org/2004/02/skos/core#prefLabel': 'skos:prefLabel',
  'http://purl.org/dc/terms/title': 'dcterms:title',
  'http://purl.org/dc/elements/1.1/title': 'dc:title',
  'https://schema.org/name': 'schema:name',
  'http://purl.obolibrary.org/obo/IAO_0000115': 'IAO:0000115',
  'http://www.w3.org/2004/02/skos/core#definition': 'skos:definition',
  'http://www.w3.org/2000/01/rdf-schema#comment': 'rdfs:comment',
  'http://purl.org/dc/terms/description': 'dcterms:description',
  'http://www.w3.org/2004/02/skos/core#altLabel': 'skos:altLabel',
  'http://www.geneontology.org/formats/oboInOwl#hasExactSynonym': 'oboInOwl:hasExactSynonym',
  'http://www.geneontology.org/formats/oboInOwl#hasRelatedSynonym': 'oboInOwl:hasRelatedSynonym',
  'http://www.geneontology.org/formats/oboInOwl#hasBroadSynonym': 'oboInOwl:hasBroadSynonym',
  'http://www.geneontology.org/formats/oboInOwl#hasNarrowSynonym': 'oboInOwl:hasNarrowSynonym',
  'http://www.w3.org/2002/07/owl#deprecated': 'owl:deprecated',
  'http://www.w3.org/2004/02/skos/core#example': 'skos:example',
}

function shortIri(iri: string): string {
  return CURATED_LABELS[iri] ?? iri.split(/[/#]/).pop() ?? iri
}

type TermRole = 'label_props' | 'definition_props' | 'elucidation_props' | 'synonym_props' | 'deprecated_props' | 'example_props'

const ROLE_OPTIONS: { value: TermRole | ''; label: string }[] = [
  { value: '', label: '—' },
  { value: 'label_props', label: 'Label' },
  { value: 'definition_props', label: 'Definition' },
  { value: 'elucidation_props', label: 'Elucidation' },
  { value: 'synonym_props', label: 'Synonym' },
  { value: 'deprecated_props', label: 'Deprecated' },
  { value: 'example_props', label: 'Example' },
]

interface TermProp {
  iri: string
  label: string
  propLabel: string | null
  count: number
  role: TermRole | null
}

function buildTermProps(profile: OntologyProfileData, cand: ProfileCandidates): TermProp[] {
  const roleMap = new Map<string, TermRole>()
  for (const iri of profile.label_props) roleMap.set(iri, 'label_props')
  for (const iri of profile.definition_props) roleMap.set(iri, 'definition_props')
  for (const iri of (profile.elucidation_props ?? [])) roleMap.set(iri, 'elucidation_props')
  for (const iri of profile.synonym_props) roleMap.set(iri, 'synonym_props')
  for (const iri of profile.deprecated_props) roleMap.set(iri, 'deprecated_props')
  for (const iri of (profile.example_props ?? [])) roleMap.set(iri, 'example_props')

  const seen = new Set<string>()
  const all: TermProp[] = []

  for (const c of [
    ...(cand.label ?? []),
    ...(cand.definition ?? []),
    ...(cand.synonym ?? []),
    ...(cand.deprecated ?? []),
    ...(cand.unknown ?? []),
  ]) {
    if (!seen.has(c.iri)) {
      seen.add(c.iri)
      all.push({ iri: c.iri, label: shortIri(c.iri), propLabel: c.label ?? null, count: c.count, role: roleMap.get(c.iri) ?? null })
    }
  }
  // Include assigned props not returned by detection (e.g. manually added)
  for (const [iri, role] of roleMap.entries()) {
    if (!seen.has(iri)) {
      all.push({ iri, label: shortIri(iri), propLabel: null, count: 0, role })
    }
  }

  return all.sort((a, b) => b.count - a.count)
}

export default function ProfileEditor({ ontologyId, versionId }: {
  ontologyId: string
  versionId: string
}) {
  const { data: profile, isLoading: profileLoading } = useOntologyProfile(ontologyId, versionId)
  const { data: candidates, isLoading: candidatesLoading } = useProfileCandidates(ontologyId, versionId)
  const patch = usePatchProfile(ontologyId, versionId)
  const detect = useDetectProfile(ontologyId, versionId)
  const [roleEdits, setRoleEdits] = useState<Record<string, TermRole | null>>({})

  if (profileLoading || candidatesLoading) {
    return <div style={{ padding: '1rem', color: 'var(--text-dim)', fontSize: 12 }}>Loading…</div>
  }

  if (!profile) {
    return (
      <div style={{ padding: '1rem' }}>
        <div style={{ color: 'var(--text-dim)', fontSize: 12, marginBottom: 12 }}>No profile detected yet.</div>
        <button
          onClick={() => detect.mutate()}
          disabled={detect.isPending}
          style={{ padding: '6px 14px', borderRadius: 4, border: 'none', background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 12, cursor: 'pointer' }}
        >
          {detect.isPending ? 'Running…' : 'Detect Profile'}
        </button>
      </div>
    )
  }

  const cand = candidates ?? { label: [], definition: [], synonym: [], deprecated: [], unknown: [], version_id: versionId }
  const props = buildTermProps(profile, cand)
  const isDirty = Object.keys(roleEdits).length > 0

  function effectiveRole(p: TermProp): TermRole | null {
    return p.iri in roleEdits ? roleEdits[p.iri] : p.role
  }

  function handleSave() {
    const groups: Record<TermRole, string[]> = { label_props: [], definition_props: [], elucidation_props: [], synonym_props: [], deprecated_props: [], example_props: [] }
    for (const p of props) {
      const r = effectiveRole(p)
      if (r) groups[r].push(p.iri)
    }
    patch.mutate(groups, { onSuccess: () => setRoleEdits({}) })
  }

  return (
    <div style={{ padding: '12px 16px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
        <span style={{
          fontSize: 10, padding: '1px 8px', borderRadius: 10,
          background: profile.status === 'user_confirmed' ? 'rgba(63,185,80,0.1)' : 'rgba(88,166,255,0.1)',
          color: profile.status === 'user_confirmed' ? 'var(--green)' : 'var(--blue)',
          border: `1px solid ${profile.status === 'user_confirmed' ? 'rgba(63,185,80,0.25)' : 'rgba(88,166,255,0.25)'}`,
        }}>
          {profile.status === 'user_confirmed' ? '● confirmed' : '⟳ auto-detected'}
        </span>
        <button
          onClick={() => detect.mutate()}
          disabled={detect.isPending}
          style={{ fontSize: 10, color: 'var(--text-dim)', background: 'none', border: 'none', cursor: 'pointer' }}
        >
          {detect.isPending ? 'Re-detecting…' : 'Re-detect'}
        </button>
        {detect.isError && (
          <span style={{ fontSize: 10, color: 'var(--red)' }}>
            {(detect.error as Error)?.message ?? 'error'}
          </span>
        )}
      </div>

      {props.length === 0 ? (
        <div>
          <div style={{ color: 'var(--text-dim)', fontSize: 12, marginBottom: 10 }}>
            No annotation properties found in this ontology.
          </div>
          <button
            onClick={() => detect.mutate()}
            disabled={detect.isPending}
            style={{ padding: '6px 14px', borderRadius: 4, border: 'none', background: 'var(--accent)', color: 'var(--on-accent)', fontSize: 12, cursor: 'pointer' }}
          >
            {detect.isPending ? 'Scanning…' : 'Scan Now'}
          </button>
        </div>
      ) : (
        <>
          <div style={{
            display: 'grid', gridTemplateColumns: '1fr 72px 112px', gap: 6,
            paddingBottom: 6, marginBottom: 2, borderBottom: '1px solid var(--border)',
          }}>
            <span style={{ fontSize: 10, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: 0.6 }}>Property</span>
            <span style={{ fontSize: 10, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: 0.6, textAlign: 'right' }}>Terms</span>
            <span style={{ fontSize: 10, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: 0.6 }}>Role</span>
          </div>
          {props.map(p => (
            <div key={p.iri} style={{
              display: 'grid', gridTemplateColumns: '1fr 72px 112px', gap: 6,
              padding: '4px 0', alignItems: 'center',
              borderBottom: '1px solid color-mix(in srgb, var(--border) 40%, transparent)',
            }}>
              <div title={p.iri} style={{ overflow: 'hidden' }}>
                <div style={{ fontSize: 11, color: 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {p.propLabel ?? p.label}
                </div>
                {p.propLabel && (
                  <div style={{ fontSize: 9, color: 'var(--text-dim)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {p.label}
                  </div>
                )}
              </div>
              <span style={{ fontSize: 11, color: 'var(--text-dim)', textAlign: 'right' }}>
                {p.count > 0 ? p.count.toLocaleString() : '—'}
              </span>
              <select
                value={effectiveRole(p) ?? ''}
                onChange={e => setRoleEdits(prev => ({
                  ...prev,
                  [p.iri]: (e.target.value || null) as TermRole | null,
                }))}
                style={{
                  fontSize: 11, padding: '2px 4px', borderRadius: 4,
                  border: '1px solid var(--border)', background: 'var(--bg)',
                  color: 'var(--text)', cursor: 'pointer', width: '100%',
                }}
              >
                {ROLE_OPTIONS.map(o => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>
          ))}
        </>
      )}

      <div style={{ marginTop: 16, paddingTop: 12, borderTop: '1px solid var(--border)' }}>
        <button
          onClick={handleSave}
          disabled={!isDirty || patch.isPending}
          style={{
            padding: '6px 16px', borderRadius: 4, border: 'none',
            background: isDirty ? 'var(--accent)' : 'var(--bg-secondary)',
            color: isDirty ? 'var(--on-accent)' : 'var(--text-dim)',
            fontSize: 12, cursor: isDirty ? 'pointer' : 'default',
          }}
        >
          {patch.isPending ? 'Saving and re-indexing…' : 'Save and re-index'}
        </button>
        {patch.isSuccess && <span style={{ marginLeft: 10, color: 'var(--green)', fontSize: 11 }}>✓ Saved</span>}
        {patch.isError && <span style={{ marginLeft: 10, color: 'var(--red)', fontSize: 11 }}>{(patch.error as Error)?.message ?? 'Save failed'}</span>}
      </div>
    </div>
  )
}
