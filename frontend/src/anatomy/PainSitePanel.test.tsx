import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { AnatomicalSite, Location } from '@/api/types'
import { PainSitePanel, type SiteActions } from './PainSitePanel'
import { STRUCTURES } from './fixtures'

const LOCATIONS: Location[] = [
  { code: 'KNEE', label: 'Knee', region: 'LOWER_LIMB', parent_code: null },
  { code: 'ABD_RUQ', label: 'Right upper quadrant', region: 'ABDOMEN', parent_code: 'ABDOMEN' },
]

const site = (code: string, side: AnatomicalSite['side'], extra: Partial<AnatomicalSite> = {}) => ({
  structure_code: code,
  side,
  intensity: null,
  is_primary: false,
  note: null,
  ...extra,
})

function setup(sites: AnatomicalSite[]) {
  const actions: SiteActions = {
    setSide: vi.fn(),
    setIntensity: vi.fn(),
    setNote: vi.fn(),
    setMainSite: vi.fn(),
    remove: vi.fn(),
    locate: vi.fn(),
  }
  render(
    <PainSitePanel
      sites={sites}
      structures={new Map(STRUCTURES.map((entry) => [entry.code, entry]))}
      locations={LOCATIONS}
      focused={null}
      actions={actions}
    />,
  )
  return actions
}

describe('PainSitePanel', () => {
  it('asks for a site and points at the fallback when nothing is recorded', () => {
    setup([])
    expect(screen.getByText('No structure recorded yet')).toBeInTheDocument()
    expect(screen.getByText(/pick the region instead/)).toBeInTheDocument()
  })

  it('shows the structure, its Latin name and the identifier that gets stored', () => {
    setup([site('JOINT_KNEE', 'LEFT', { is_primary: true })])
    expect(screen.getByText('Articulatio genus ·')).toBeInTheDocument()
    expect(screen.getByText('JOINT_KNEE')).toBeInTheDocument()
    expect(screen.getByText('Main site')).toBeInTheDocument()
  })

  it('records an intensity for one site without touching another', async () => {
    const actions = setup([site('JOINT_KNEE', 'LEFT'), site('JOINT_KNEE', 'RIGHT')])
    await userEvent.click(screen.getByRole('button', { name: '7 at Knee joint, left' }))
    expect(actions.setIntensity).toHaveBeenCalledWith('JOINT_KNEE', 'LEFT', 7)
  })

  it('offers only the sides the structure has', () => {
    setup([site('JOINT_KNEE', 'LEFT'), site('ORG_LIVER', 'RIGHT')])
    const knee = screen.getByLabelText('Side for Knee joint, left')
    const liver = screen.getByLabelText('Side for Liver, right')
    expect([...knee.querySelectorAll('option')].map((option) => option.textContent)).toEqual([
      'Left',
      'Right',
      'Both sides',
    ])
    expect(liver).toBeDisabled()
  })

  it('moves a site to the other side', async () => {
    const actions = setup([site('JOINT_KNEE', 'LEFT')])
    await userEvent.selectOptions(screen.getByLabelText('Side for Knee joint, left'), 'RIGHT')
    expect(actions.setSide).toHaveBeenCalledWith('JOINT_KNEE', 'LEFT', 'RIGHT')
  })

  it('names the band the recorded intensity falls in', () => {
    setup([site('JOINT_KNEE', 'LEFT', { intensity: 8 })])
    expect(screen.getByText('severe')).toBeInTheDocument()
  })

  it('shows the pain sites the structures record', () => {
    setup([site('JOINT_KNEE', 'LEFT'), site('ORG_LIVER', 'RIGHT')])
    expect(screen.getByText('Knee (left), Right upper quadrant (right)')).toBeInTheDocument()
  })

  it('removes a site and can bring one back into view', async () => {
    const actions = setup([site('NRV_SCIATIC', 'LEFT')])
    await userEvent.click(screen.getByRole('button', { name: 'Remove Sciatic nerve, left' }))
    expect(actions.remove).toHaveBeenCalledWith('NRV_SCIATIC', 'LEFT')

    await userEvent.click(
      screen.getByRole('button', { name: 'Show Sciatic nerve, left on the model' }),
    )
    expect(actions.locate).toHaveBeenCalledWith('NRV_SCIATIC', 'LEFT')
  })
})
