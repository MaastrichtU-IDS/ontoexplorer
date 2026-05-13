import { useCallback } from 'react'

interface Props {
  onDelta: (delta: number) => void
}

export default function ResizeHandle({ onDelta }: Props) {
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    let lastX = e.clientX

    function onMouseMove(ev: MouseEvent) {
      onDelta(ev.clientX - lastX)
      lastX = ev.clientX
    }
    function onMouseUp(ev: MouseEvent) {
      onDelta(ev.clientX - lastX)
      document.removeEventListener('mousemove', onMouseMove)
      document.removeEventListener('mouseup', onMouseUp)
    }
    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
  }, [onDelta])

  return (
    <div
      onMouseDown={handleMouseDown}
      style={{
        width: 4, cursor: 'col-resize', flexShrink: 0,
        background: 'var(--border)',
        transition: 'background 0.15s',
      }}
      onMouseEnter={e => (e.currentTarget.style.background = 'var(--accent)')}
      onMouseLeave={e => (e.currentTarget.style.background = 'var(--border)')}
    />
  )
}
