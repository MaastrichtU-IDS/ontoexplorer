import { render, fireEvent } from '@testing-library/react'
import ResizeHandle from './ResizeHandle'

test('fires onDelta with positive delta when dragged right', () => {
  const onDelta = vi.fn()
  const { container } = render(<ResizeHandle onDelta={onDelta} />)
  const handle = container.firstChild as HTMLElement

  fireEvent.mouseDown(handle, { clientX: 100 })
  fireEvent.mouseMove(document, { clientX: 150 })
  fireEvent.mouseUp(document, { clientX: 150 })

  expect(onDelta).toHaveBeenCalledWith(50)
})

test('fires onDelta with negative delta when dragged left', () => {
  const onDelta = vi.fn()
  const { container } = render(<ResizeHandle onDelta={onDelta} />)
  const handle = container.firstChild as HTMLElement

  fireEvent.mouseDown(handle, { clientX: 200 })
  fireEvent.mouseMove(document, { clientX: 160 })
  fireEvent.mouseUp(document, { clientX: 160 })

  expect(onDelta).toHaveBeenCalledWith(-40)
})
