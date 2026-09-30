import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { StructureBrowser } from './StructureBrowser'
import { ONTOLOGY, STRUCTURES } from './fixtures'

function setup(selected: string[] = []) {
  const onSelect = vi.fn()
  render(
    <StructureBrowser
      ontology={ONTOLOGY}
      offered={STRUCTURES}
      selectedCodes={new Set(selected)}
      onSelect={onSelect}
    />,
  )
  return onSelect
}

describe('StructureBrowser', () => {
  it('keeps the regions closed until one is opened', async () => {
    const onSelect = setup()
    expect(screen.queryByRole('button', { name: 'Knee joint' })).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /Lower limb/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Knee joint' }))
    expect(onSelect).toHaveBeenCalledWith(STRUCTURES.find((entry) => entry.code === 'JOINT_KNEE'))
  })

  it('finds a structure by a synonym and opens the region holding it', async () => {
    setup()
    await userEvent.type(screen.getByLabelText('Search the anatomy'), 'sciatica')

    expect(screen.getByRole('button', { name: 'Sciatic nerve' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Liver' })).not.toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('1 structure matches')
  })

  it('finds a structure by its Latin name', async () => {
    setup()
    await userEvent.type(screen.getByLabelText('Search the anatomy'), 'Hepar')
    expect(screen.getByRole('button', { name: 'Liver' })).toBeInTheDocument()
  })

  it('says so when nothing in the ontology matches', async () => {
    setup()
    await userEvent.type(screen.getByLabelText('Search the anatomy'), 'pancreas')
    expect(screen.getByRole('status')).toHaveTextContent('Nothing in the ontology matches')
  })

  it('shows which structures are already recorded', async () => {
    setup(['JOINT_KNEE'])
    await userEvent.click(screen.getByRole('button', { name: /Lower limb/ }))
    expect(screen.getByRole('button', { name: 'Knee joint' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(screen.getByRole('button', { name: 'Sciatic nerve' })).toHaveAttribute(
      'aria-pressed',
      'false',
    )
  })

  it('offers the region fallback alongside the exact structures', async () => {
    setup()
    await userEvent.click(screen.getByRole('button', { name: /Back/ }))
    expect(screen.getByRole('button', { name: 'Lower back' })).toBeInTheDocument()
  })
})
