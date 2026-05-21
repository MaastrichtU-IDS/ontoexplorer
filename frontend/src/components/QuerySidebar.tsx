import { useState, useEffect, useRef, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import Yasgui from '@triply/yasgui'
import { useAuth } from '../hooks/useAuth'
import { api, SavedQuery, StarterQuery } from '../lib/api'

interface Props {
  yasguiRef: React.RefObject<InstanceType<typeof Yasgui> | null>
}

interface FormState {
  name: string
  description: string
  tags: string[]
  tagInput: string
  is_public: boolean
}

const EMPTY_FORM: FormState = { name: '', description: '', tags: [], tagInput: '', is_public: false }

export default function QuerySidebar({ yasguiRef }: Props) {
  const { user } = useAuth()
  const navigate = useNavigate()

  const [queries, setQueries] = useState<SavedQuery[]>([])
  const [search, setSearch] = useState('')
  const [view, setView] = useState<'list' | 'form'>('list')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [activeId, setActiveId] = useState<string | null>(null)
  const [ontologyNames, setOntologyNames] = useState<string[]>([])
  const [showTagSuggestions, setShowTagSuggestions] = useState(false)
  const tagInputRef = useRef<HTMLInputElement>(null)
  const [starters, setStarters] = useState<StarterQuery[]>([])
  type SidebarTab = 'my' | 'starters'
  const [tab, setTab] = useState<SidebarTab>(user ? 'my' : 'starters')

  useEffect(() => {
    if (!user) return
    api.savedQueries.list().then(r => setQueries(r.queries)).catch(() => {})
  }, [user])

  useEffect(() => {
    setTab(user ? 'my' : 'starters')
  }, [user])

  useEffect(() => {
    api.ontologies.list(0, 200)
      .then(r => setOntologyNames(r.ontologies.map(o => o.shortname).filter(Boolean) as string[]))
      .catch(() => {})
  }, [])

  useEffect(() => {
    api.savedQueries.listStarters()
      .then(r => setStarters(r.starters))
      .catch(() => {})
  }, [])

  function loadQuery(sq: SavedQuery) {
    setActiveId(sq.id)
    yasguiRef.current?.getTab()?.getYasqe()?.setValue(sq.query_text)
  }

  function openSaveForm() {
    setForm(EMPTY_FORM)
    setEditingId(null)
    setView('form')
  }

  function openEditForm(sq: SavedQuery, e: React.MouseEvent) {
    e.stopPropagation()
    setForm({ name: sq.name, description: sq.description ?? '', tags: sq.tags, tagInput: '', is_public: sq.is_public })
    setEditingId(sq.id)
    setView('form')
  }

  function cancelForm() {
    setForm(EMPTY_FORM)
    setEditingId(null)
    setSaveError(null)
    setView('list')
  }

  async function submitForm(e: React.FormEvent) {
    e.preventDefault()
    if (!form.name.trim()) return
    setSaving(true)
    setSaveError(null)
    try {
      const queryText = editingId
        ? (queries.find(q => q.id === editingId)?.query_text ?? '')
        : (yasguiRef.current?.getTab()?.getYasqe()?.getValue() ?? '')
      const payload = {
        name: form.name.trim(),
        description: form.description || undefined,
        query_text: queryText,
        tags: form.tags,
        is_public: form.is_public,
      }
      if (editingId) {
        const updated = await api.savedQueries.update(editingId, payload)
        setQueries(qs => qs.map(q => q.id === editingId ? updated : q))
      } else {
        const created = await api.savedQueries.create(payload)
        setQueries(qs => [created, ...qs])
      }
      cancelForm()
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  async function deleteQuery(id: string, e: React.MouseEvent) {
    e.stopPropagation()
    await api.savedQueries.delete(id)
    setQueries(qs => qs.filter(q => q.id !== id))
    if (activeId === id) setActiveId(null)
  }

  function addTag(tag: string) {
    const t = tag.trim()
    if (t && !form.tags.includes(t)) {
      setForm(f => ({ ...f, tags: [...f.tags, t], tagInput: '' }))
    } else {
      setForm(f => ({ ...f, tagInput: '' }))
    }
    setShowTagSuggestions(false)
  }

  function handleTagKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault()
      addTag(form.tagInput)
    } else if (e.key === 'Escape') {
      setShowTagSuggestions(false)
    }
  }

  const filteredQueries = queries.filter(q =>
    q.name.toLowerCase().includes(search.toLowerCase()) ||
    q.tags.some(t => t.toLowerCase().includes(search.toLowerCase()))
  )

  const tagSuggestions = form.tagInput
    ? ontologyNames.filter(n => n.toLowerCase().includes(form.tagInput.toLowerCase()) && !form.tags.includes(n)).slice(0, 6)
    : []

  const startersByCategory = useMemo(() => {
    const m = new Map<string, StarterQuery[]>()
    for (const s of starters) {
      const cat = s.category ?? 'Other'
      if (!m.has(cat)) m.set(cat, [])
      m.get(cat)!.push(s)
    }
    return Array.from(m.entries()).sort(([a], [b]) => a.localeCompare(b))
  }, [starters])

  const base: React.CSSProperties = {
    width: 200,
    flexShrink: 0,
    background: 'var(--bg-secondary)',
    borderRight: '1px solid var(--border)',
    display: 'flex',
    flexDirection: 'column',
    fontSize: '0.75rem',
    overflow: 'hidden',
  }

  return (
    <div style={base}>
      {/* Header */}
      <div style={{ padding: '6px 10px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0, gap: 8 }}>
        <div style={{ display: 'flex', gap: 10 }}>
          {user && (
            <button
              onClick={() => { setTab('my'); setView('list') }}
              style={{
                background: 'none', border: 'none', cursor: 'pointer', padding: 0,
                color: tab === 'my' && view !== 'form' ? 'var(--text)' : 'var(--text-dim)',
                fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.05em',
              }}
            >MINE</button>
          )}
          <button
            onClick={() => { setTab('starters'); setView('list') }}
            style={{
              background: 'none', border: 'none', cursor: 'pointer', padding: 0,
              color: tab === 'starters' && view !== 'form' ? 'var(--text)' : 'var(--text-dim)',
              fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.05em',
            }}
          >STARTERS</button>
        </div>
        {user && (
          view === 'list' ? (
            <button
              onClick={openSaveForm}
              style={{ background: 'var(--accent)', color: 'var(--bg)', border: 'none', borderRadius: 3, padding: '2px 7px', fontSize: '0.65rem', fontWeight: 700, cursor: 'pointer' }}
            >＋ Save</button>
          ) : (
            <span onClick={cancelForm} style={{ color: 'var(--text-dim)', cursor: 'pointer', fontSize: '0.7rem' }}>✕ cancel</span>
          )
        )}
      </div>

      {view === 'list' && tab === 'my' && user && (
        <>
          {/* Search */}
          <div style={{ padding: '5px 8px', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
            <div style={{ background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 3, padding: '3px 7px', display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ color: 'var(--text-dim)', fontSize: '0.7rem' }}>⌕</span>
              <input
                type="text"
                placeholder="Search my queries…"
                value={search}
                onChange={e => setSearch(e.target.value)}
                style={{ background: 'transparent', border: 'none', outline: 'none', color: 'var(--text)', fontSize: '0.7rem', width: '100%' }}
              />
            </div>
          </div>

          {/* List */}
          <div style={{ flex: 1, overflowY: 'auto' }}>
            {filteredQueries.length === 0 && (
              <div style={{ padding: '10px', color: 'var(--text-dim)', fontSize: '0.65rem', textAlign: 'center' }}>
                {search ? 'No matches' : 'No saved queries yet'}
              </div>
            )}
            {filteredQueries.map(q => (
              <div
                key={q.id}
                onClick={() => loadQuery(q)}
                style={{
                  padding: '5px 10px',
                  borderBottom: '1px solid rgba(51,65,85,0.4)',
                  cursor: 'pointer',
                  background: activeId === q.id ? 'rgba(34,197,94,0.08)' : undefined,
                  borderLeft: activeId === q.id ? '2px solid var(--accent)' : '2px solid transparent',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ color: activeId === q.id ? 'var(--text)' : 'var(--text-muted)', fontSize: '0.7rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
                    {q.name}
                  </span>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 3, flexShrink: 0 }}>
                    <span style={{ color: q.is_public ? 'var(--accent-blue)' : 'var(--text-dim)', fontSize: '0.6rem' }}>
                      {q.is_public ? '🔗' : '🔒'}
                    </span>
                    <span
                      onClick={e => openEditForm(q, e)}
                      style={{ color: 'var(--text-dim)', cursor: 'pointer', fontSize: '0.65rem', padding: '0 2px' }}
                    >✎</span>
                    <span
                      onClick={e => deleteQuery(q.id, e)}
                      style={{ color: 'var(--text-dim)', cursor: 'pointer', fontSize: '0.65rem', padding: '0 2px' }}
                    >✕</span>
                  </div>
                </div>
                {q.tags.length > 0 && (
                  <div style={{ color: 'var(--text-dim)', fontSize: '0.6rem', marginTop: 1 }}>
                    {q.tags.slice(0, 3).join(' · ')}
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* Footer */}
          <div style={{ padding: '6px 10px', borderTop: '1px solid var(--border)', flexShrink: 0 }}>
            <span
              onClick={() => navigate('/sparql/gallery')}
              style={{ color: 'var(--accent-blue)', fontSize: '0.65rem', cursor: 'pointer' }}
            >→ Browse Gallery</span>
          </div>
        </>
      )}

      {view === 'list' && tab === 'starters' && (
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {startersByCategory.length === 0 && (
            <div style={{ padding: '10px', color: 'var(--text-dim)', fontSize: '0.65rem', textAlign: 'center' }}>
              No starters available
            </div>
          )}
          {startersByCategory.map(([category, items]) => (
            <div key={category} style={{ borderBottom: '1px solid rgba(51,65,85,0.4)' }}>
              <div style={{ padding: '4px 10px', color: 'var(--text-dim)', fontSize: '0.6rem', fontWeight: 700, letterSpacing: '0.05em', background: 'rgba(51,65,85,0.2)' }}>
                {category}
              </div>
              {items.map(s => (
                <div
                  key={s.id}
                  onClick={() => yasguiRef.current?.getTab()?.getYasqe()?.setValue(s.query_text)}
                  style={{ padding: '5px 10px', cursor: 'pointer', borderLeft: '2px solid transparent' }}
                  onMouseEnter={e => (e.currentTarget.style.background = 'rgba(34,197,94,0.05)')}
                  onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                >
                  <div style={{ color: 'var(--text-muted)', fontSize: '0.7rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {s.name}
                  </div>
                  {s.description && (
                    <div style={{ color: 'var(--text-dim)', fontSize: '0.6rem', marginTop: 1, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                      {s.description}
                    </div>
                  )}
                </div>
              ))}
            </div>
          ))}
        </div>
      )}

      {view === 'form' && (
        <form
          onSubmit={submitForm}
          style={{ flex: 1, overflowY: 'auto', padding: '8px 10px', display: 'flex', flexDirection: 'column', gap: 6, background: 'var(--bg)' }}
        >
          <div>
            <div style={{ color: 'var(--text-dim)', fontSize: '0.6rem', marginBottom: 2 }}>Name *</div>
            <input
              required
              value={form.name}
              onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
              style={{ width: '100%', background: 'var(--bg-secondary)', border: '1px solid var(--accent)', borderRadius: 3, padding: '3px 6px', color: 'var(--text)', fontSize: '0.7rem', boxSizing: 'border-box' }}
            />
          </div>

          <div>
            <div style={{ color: 'var(--text-dim)', fontSize: '0.6rem', marginBottom: 2 }}>Description</div>
            <textarea
              value={form.description}
              onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
              rows={2}
              style={{ width: '100%', background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 3, padding: '3px 6px', color: 'var(--text)', fontSize: '0.7rem', resize: 'none', boxSizing: 'border-box' }}
            />
          </div>

          <div style={{ position: 'relative' }}>
            <div style={{ color: 'var(--text-dim)', fontSize: '0.6rem', marginBottom: 2 }}>Tags</div>
            <div
              style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 3, padding: '3px 6px', display: 'flex', gap: 3, flexWrap: 'wrap', alignItems: 'center', minHeight: 26, cursor: 'text' }}
              onClick={() => tagInputRef.current?.focus()}
            >
              {form.tags.map(t => (
                <span key={t} style={{ background: 'rgba(103,232,249,0.1)', border: '1px solid rgba(103,232,249,0.3)', color: 'var(--accent-blue)', borderRadius: 3, padding: '1px 4px', fontSize: '0.6rem', display: 'flex', alignItems: 'center', gap: 2 }}>
                  {t}
                  <span
                    onClick={e => { e.stopPropagation(); setForm(f => ({ ...f, tags: f.tags.filter(x => x !== t) })) }}
                    style={{ cursor: 'pointer' }}
                  >✕</span>
                </span>
              ))}
              <input
                ref={tagInputRef}
                value={form.tagInput}
                onChange={e => { setForm(f => ({ ...f, tagInput: e.target.value })); setShowTagSuggestions(true) }}
                onKeyDown={handleTagKeyDown}
                onFocus={() => setShowTagSuggestions(true)}
                onBlur={() => setTimeout(() => setShowTagSuggestions(false), 150)}
                placeholder="+tag…"
                style={{ background: 'transparent', border: 'none', outline: 'none', color: 'var(--text-dim)', fontSize: '0.7rem', minWidth: 40, flex: 1 }}
              />
            </div>
            {showTagSuggestions && tagSuggestions.length > 0 && (
              <div style={{ position: 'absolute', top: '100%', left: 0, right: 0, background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 3, zIndex: 10, maxHeight: 120, overflowY: 'auto' }}>
                {tagSuggestions.map(s => (
                  <div
                    key={s}
                    onMouseDown={() => addTag(s)}
                    style={{ padding: '3px 8px', color: 'var(--text-muted)', fontSize: '0.7rem', cursor: 'pointer' }}
                  >{s}</div>
                ))}
              </div>
            )}
          </div>

          {saveError && (
            <div style={{ color: '#f87171', fontSize: '0.6rem', wordBreak: 'break-word' }}>{saveError}</div>
          )}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 4, color: 'var(--text-muted)', fontSize: '0.7rem', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={form.is_public}
                onChange={e => setForm(f => ({ ...f, is_public: e.target.checked }))}
                style={{ accentColor: 'var(--accent)' }}
              />
              Public
            </label>
            <button
              type="submit"
              disabled={!form.name.trim() || saving}
              style={{ background: 'var(--accent)', color: 'var(--bg)', border: 'none', borderRadius: 3, padding: '2px 8px', fontSize: '0.7rem', fontWeight: 700, cursor: 'pointer', opacity: (!form.name.trim() || saving) ? 0.5 : 1 }}
            >{saving ? '…' : 'Save'}</button>
          </div>
        </form>
      )}
    </div>
  )
}
