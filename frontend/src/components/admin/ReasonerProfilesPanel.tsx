import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  api,
  type ReasonerInfo,
  type ReasonerParamSpec,
  type ReasonerProfile,
  type ReasonerProfileInput,
} from '../../lib/api'

type FormState = {
  name: string
  reasoner: string
  params: Record<string, boolean | number | string>
  dashboard_selectable: boolean
  is_default: boolean
  description: string
}

function defaultsFor(schema: ReasonerParamSpec[] | undefined): Record<string, boolean | number | string> {
  const out: Record<string, boolean | number | string> = {}
  for (const s of schema ?? []) out[s.key] = s.default
  return out
}

const inputStyle: React.CSSProperties = {
  fontSize: 13, padding: '4px 6px', borderRadius: 'var(--radius-sm)',
  border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)',
}

function ParamField({ spec, value, onChange }: {
  spec: ReasonerParamSpec
  value: boolean | number | string
  onChange: (v: boolean | number | string) => void
}) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 2, fontSize: 12 }}>
      <span style={{ fontWeight: 600 }}>{spec.label ?? spec.key}</span>
      {spec.type === 'bool' && (
        <input type="checkbox" checked={Boolean(value)} onChange={e => onChange(e.target.checked)} />
      )}
      {spec.type === 'int' && (
        <input
          type="number" style={{ ...inputStyle, maxWidth: 160 }}
          value={Number(value)} min={spec.min} max={spec.max}
          onChange={e => onChange(e.target.value === '' ? 0 : parseInt(e.target.value, 10))}
        />
      )}
      {spec.type === 'enum' && (
        <select style={{ ...inputStyle, maxWidth: 200 }} value={String(value)} onChange={e => onChange(e.target.value)}>
          {(spec.choices ?? []).map(c => <option key={c} value={c}>{c}</option>)}
        </select>
      )}
      {spec.help && <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>{spec.help}</span>}
    </label>
  )
}

function ProfileForm({ initial, catalog, onSaved, onCancel }: {
  initial: ReasonerProfile | null   // null = create
  catalog: ReasonerInfo[]
  onSaved: () => void
  onCancel: () => void
}) {
  const classifyReasoners = catalog.filter(r => r.capabilities.includes('classify'))
  const firstReasoner = initial?.reasoner ?? classifyReasoners[0]?.name ?? 'rustdl'
  const schemaFor = (name: string) => catalog.find(r => r.name === name)?.param_schema

  const [form, setForm] = useState<FormState>(() => ({
    name: initial?.name ?? '',
    reasoner: firstReasoner,
    params: initial?.params ?? defaultsFor(schemaFor(firstReasoner)),
    dashboard_selectable: initial?.dashboard_selectable ?? false,
    is_default: initial?.is_default ?? false,
    description: initial?.description ?? '',
  }))

  const schema = schemaFor(form.reasoner) ?? []
  const [error, setError] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: () => {
      const body: ReasonerProfileInput = {
        name: form.name.trim(),
        reasoner: form.reasoner,
        params: form.params,
        dashboard_selectable: form.dashboard_selectable,
        is_default: form.is_default,
        description: form.description.trim() || null,
      }
      return initial
        ? api.admin.updateReasonerProfile(initial.id, body)
        : api.admin.createReasonerProfile(body)
    },
    onSuccess: onSaved,
    onError: (e: unknown) => setError((e as Error)?.message ?? 'Save failed'),
  })

  function changeReasoner(name: string) {
    setForm(f => ({ ...f, reasoner: name, params: defaultsFor(schemaFor(name)) }))
  }

  return (
    <div style={{
      border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: 16,
      background: 'var(--bg-secondary)', display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 16,
    }}>
      <strong style={{ fontSize: 14 }}>{initial ? `Edit "${initial.name}"` : 'New reasoner profile'}</strong>

      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 2, fontSize: 12 }}>
          <span style={{ fontWeight: 600 }}>Name</span>
          <input style={{ ...inputStyle, minWidth: 220 }} value={form.name}
                 onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder="e.g. rustdl EL (fast)" />
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 2, fontSize: 12 }}>
          <span style={{ fontWeight: 600 }}>Reasoner</span>
          <select style={{ ...inputStyle, minWidth: 160 }} value={form.reasoner} onChange={e => changeReasoner(e.target.value)}>
            {classifyReasoners.map(r => (
              <option key={r.name} value={r.name} disabled={!r.available}>
                {r.name}{r.available ? '' : ' (unavailable)'} — {r.profile}
              </option>
            ))}
          </select>
        </label>
      </div>

      {schema.length > 0 ? (
        <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
          {schema.map(s => (
            <ParamField key={s.key} spec={s} value={form.params[s.key] ?? s.default}
                        onChange={v => setForm(f => ({ ...f, params: { ...f.params, [s.key]: v } }))} />
          ))}
        </div>
      ) : (
        <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>This reasoner has no tunable parameters.</span>
      )}

      <label style={{ display: 'flex', flexDirection: 'column', gap: 2, fontSize: 12 }}>
        <span style={{ fontWeight: 600 }}>Description</span>
        <input style={{ ...inputStyle }} value={form.description}
               onChange={e => setForm(f => ({ ...f, description: e.target.value }))} />
      </label>

      <div style={{ display: 'flex', gap: 20 }}>
        <label style={{ fontSize: 12, display: 'flex', gap: 6, alignItems: 'center' }}>
          <input type="checkbox" checked={form.dashboard_selectable}
                 onChange={e => setForm(f => ({ ...f, dashboard_selectable: e.target.checked }))} />
          Selectable in user dashboard
        </label>
        <label style={{ fontSize: 12, display: 'flex', gap: 6, alignItems: 'center' }}>
          <input type="checkbox" checked={form.is_default}
                 onChange={e => setForm(f => ({ ...f, is_default: e.target.checked }))} />
          Default profile
        </label>
      </div>

      {error && <span style={{ color: 'var(--red)', fontSize: 12 }}>{error}</span>}

      <div style={{ display: 'flex', gap: 8 }}>
        <button type="button" onClick={() => mutation.mutate()} disabled={!form.name.trim() || mutation.isPending}
                style={{ ...inputStyle, cursor: 'pointer', background: 'var(--accent-blue)', color: '#fff', border: 'none', padding: '6px 14px' }}>
          {mutation.isPending ? 'Saving…' : (initial ? 'Save' : 'Create')}
        </button>
        <button type="button" onClick={onCancel}
                style={{ ...inputStyle, cursor: 'pointer', padding: '6px 14px' }}>Cancel</button>
      </div>
    </div>
  )
}

function paramSummary(params: Record<string, boolean | number | string>): string {
  const entries = Object.entries(params ?? {})
  if (entries.length === 0) return '—'
  return entries.map(([k, v]) => `${k}=${v}`).join(', ')
}

export function ReasonerProfilesPanel() {
  const qc = useQueryClient()
  const { data: profData, isLoading } = useQuery({
    queryKey: ['admin', 'reasoner-profiles'],
    queryFn: () => api.admin.reasonerProfiles(),
  })
  const { data: catalog } = useQuery({
    queryKey: ['reasoners'], queryFn: () => api.reasoners.list(), staleTime: 300_000,
  })
  const profiles = useMemo(() => profData?.profiles ?? [], [profData])
  const [editing, setEditing] = useState<ReasonerProfile | 'new' | null>(null)

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['admin', 'reasoner-profiles'] })
    qc.invalidateQueries({ queryKey: ['reasoner-profiles'] })
  }

  const archive = useMutation({
    mutationFn: (id: string) => api.admin.archiveReasonerProfile(id),
    onSuccess: invalidate,
  })

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
        <p style={{ fontSize: 13, color: 'var(--text-dim)', margin: 0, maxWidth: 640 }}>
          Named reasoner configurations. Each profile picks a reasoner and its parameters; mark a profile
          <em> selectable</em> to offer it in the user dashboard when adding an ontology. Deleting a profile
          archives it (kept for provenance).
        </p>
        {editing === null && (
          <button type="button" onClick={() => setEditing('new')}
                  style={{ ...inputStyle, cursor: 'pointer', background: 'var(--accent-blue)', color: '#fff', border: 'none', padding: '6px 14px', whiteSpace: 'nowrap' }}>
            + New profile
          </button>
        )}
      </div>

      {editing !== null && (
        <ProfileForm
          initial={editing === 'new' ? null : editing}
          catalog={catalog ?? []}
          onSaved={() => { invalidate(); setEditing(null) }}
          onCancel={() => setEditing(null)}
        />
      )}

      {isLoading ? <p style={{ fontSize: 13, color: 'var(--text-dim)' }}>Loading…</p> : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ textAlign: 'left', color: 'var(--text-dim)', borderBottom: '1px solid var(--border)' }}>
                <th style={{ padding: '6px 10px' }}>Name</th>
                <th style={{ padding: '6px 10px' }}>Reasoner</th>
                <th style={{ padding: '6px 10px' }}>Parameters</th>
                <th style={{ padding: '6px 10px' }}>Dashboard</th>
                <th style={{ padding: '6px 10px' }}>Default</th>
                <th style={{ padding: '6px 10px' }}></th>
              </tr>
            </thead>
            <tbody>
              {profiles.map(p => (
                <tr key={p.id} style={{ borderBottom: '1px solid var(--border)', opacity: p.archived ? 0.5 : 1 }}>
                  <td style={{ padding: '6px 10px', fontWeight: 600 }}>
                    {p.name}{p.archived && <span style={{ color: 'var(--text-dim)', fontWeight: 400 }}> (archived)</span>}
                    {p.description && <div style={{ fontWeight: 400, color: 'var(--text-dim)', fontSize: 11 }}>{p.description}</div>}
                  </td>
                  <td style={{ padding: '6px 10px' }}>{p.reasoner}</td>
                  <td style={{ padding: '6px 10px', fontFamily: 'var(--font-mono)', fontSize: 11 }}>{paramSummary(p.params)}</td>
                  <td style={{ padding: '6px 10px' }}>{p.dashboard_selectable ? '✓' : '—'}</td>
                  <td style={{ padding: '6px 10px' }}>{p.is_default ? '★' : '—'}</td>
                  <td style={{ padding: '6px 10px', textAlign: 'right', whiteSpace: 'nowrap' }}>
                    {!p.archived && (
                      <>
                        <button type="button" onClick={() => setEditing(p)}
                                style={{ ...inputStyle, cursor: 'pointer', padding: '3px 10px', marginRight: 6 }}>Edit</button>
                        <button type="button"
                                onClick={() => { if (confirm(`Archive profile "${p.name}"? It will no longer be selectable.`)) archive.mutate(p.id) }}
                                style={{ ...inputStyle, cursor: 'pointer', padding: '3px 10px', color: 'var(--red)' }}>Delete</button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
              {profiles.length === 0 && (
                <tr><td colSpan={6} style={{ padding: 16, textAlign: 'center', color: 'var(--text-dim)' }}>No reasoner profiles yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
