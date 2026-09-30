import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { PainScale } from './PainScale'

describe('PainScale', () => {
  it('shows the estimate and the self-reported score as separate markers', () => {
    render(<PainScale estimate={7.2} selfReport={3} />)
    expect(screen.getByText('Estimate 7.2')).toBeInTheDocument()
    expect(screen.getByText('Self-report 3')).toBeInTheDocument()
  })

  it('shows only what it was given', () => {
    render(<PainScale estimate={5.5} />)
    expect(screen.getByText('Estimate 5.5')).toBeInTheDocument()
    expect(screen.queryByText(/Self-report/)).not.toBeInTheDocument()
  })

  it('never merges the two into one number', () => {
    render(<PainScale estimate={8} selfReport={2} />)
    expect(screen.queryByText('Estimate 5.0')).not.toBeInTheDocument()
    expect(screen.getByText('Estimate 8.0')).toBeInTheDocument()
    expect(screen.getByText('Self-report 2')).toBeInTheDocument()
  })

  it('keeps a value outside the scale inside the track', () => {
    const { container } = render(<PainScale estimate={14} />)
    const marker = container.querySelector('[style*="left"]') as HTMLElement
    expect(marker.style.left).toBe('100%')
  })
})
