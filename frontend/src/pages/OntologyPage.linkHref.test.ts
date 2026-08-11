import { describe, it, expect } from 'vitest'
import { linkHref } from './OntologyPage'

describe('linkHref (Info-page metadata hyperlinking)', () => {
  it('links bare http(s) and mailto values', () => {
    expect(linkHref('http://example.org')).toBe('http://example.org')
    expect(linkHref('https://w3id.org/sulo/')).toBe('https://w3id.org/sulo/')
    expect(linkHref('https://creativecommons.org/licenses/by/4.0/')).toBe('https://creativecommons.org/licenses/by/4.0/')
    expect(linkHref('mailto:author@example.org')).toBe('mailto:author@example.org')
  })

  it('trims surrounding whitespace', () => {
    expect(linkHref('  https://example.org/x  ')).toBe('https://example.org/x')
  })

  it('does NOT link unsafe or non-URL schemes', () => {
    expect(linkHref('javascript:alert(1)')).toBeNull()
    expect(linkHref('data:text/html,<script>alert(1)</script>')).toBeNull()
    expect(linkHref('vbscript:msgbox(1)')).toBeNull()
    expect(linkHref('ftp://example.org/file')).toBeNull()
    expect(linkHref('urn:isbn:0451450523')).toBeNull()
    expect(linkHref('file:///etc/passwd')).toBeNull()
  })

  it('does NOT partially linkify prose that merely mentions a URL', () => {
    expect(linkHref('See https://example.org for details')).toBeNull()
    expect(linkHref('A multilingual biomedical ontology')).toBeNull()
    expect(linkHref('')).toBeNull()
  })
})
