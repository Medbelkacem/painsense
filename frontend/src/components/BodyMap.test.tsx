import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { BodyMap } from './BodyMap'

describe('BodyMap', () => {
  it('reports the site and the side when a zone is chosen', async () => {
    const onToggle = vi.fn()
    render(<BodyMap selected={[]} onToggle={onToggle} />)

    await userEvent.click(screen.getByRole('checkbox', { name: 'Right upper quadrant' }))
    expect(onToggle).toHaveBeenCalledWith({ code: 'ABD_RUQ', side: 'RIGHT' })
  })

  it('marks a chosen zone as checked', () => {
    render(<BodyMap selected={[{ code: 'CHEST_CENTRAL', side: 'MIDLINE' }]} onToggle={vi.fn()} />)
    expect(screen.getByRole('checkbox', { name: 'Central chest' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Left chest' })).not.toBeChecked()
  })

  it('offers the spinal regions on the posterior view', async () => {
    render(<BodyMap selected={[]} onToggle={vi.fn()} />)
    expect(screen.queryByRole('checkbox', { name: 'Lumbar spine' })).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('radio', { name: 'Back' }))
    expect(screen.getByRole('checkbox', { name: 'Lumbar spine' })).toBeInTheDocument()
  })

  it("keeps left and right as the patient's own when the view turns round", async () => {
    render(<BodyMap selected={[]} onToggle={vi.fn()} />)
    await userEvent.click(screen.getByRole('radio', { name: 'Back' }))
    expect(screen.getByRole('checkbox', { name: 'Right hand' })).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: 'Left hand' })).toBeInTheDocument()
  })
})
