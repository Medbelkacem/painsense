import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { Question } from '@/api/types'
import { QuestionField } from './QuestionField'

const base: Question = {
  code: 'TEST',
  prompt: 'Does the pain come on with exertion?',
  kind: 'BOOL',
  group: 'REGIONAL',
  group_label: 'Site-specific',
  options: [],
  unit: null,
  minimum: null,
  maximum: null,
  help_text: '',
  order: 10,
}

describe('QuestionField', () => {
  it('renders a boolean question as a checkbox and reports the answer', async () => {
    const onChange = vi.fn()
    render(<QuestionField question={base} value={undefined} onChange={onChange} />)

    await userEvent.click(screen.getByRole('checkbox'))
    expect(onChange).toHaveBeenCalledWith(true)
  })

  it('renders a single choice with a "not recorded" option', () => {
    render(
      <QuestionField
        question={{
          ...base,
          kind: 'SINGLE',
          options: [
            { value: 'NORMAL', label: 'Normal' },
            { value: 'ABNORMAL', label: 'Abnormal' },
          ],
        }}
        value={undefined}
        onChange={vi.fn()}
      />,
    )
    expect(screen.getByRole('option', { name: 'Not recorded' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Abnormal' })).toBeInTheDocument()
  })

  it('adds to the selection for a multiple choice', async () => {
    const onChange = vi.fn()
    render(
      <QuestionField
        question={{
          ...base,
          kind: 'MULTI',
          options: [
            { value: 'LEFT_ARM', label: 'Left arm' },
            { value: 'JAW', label: 'Jaw or neck' },
          ],
        }}
        value={['LEFT_ARM']}
        onChange={onChange}
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Jaw or neck' }))
    expect(onChange).toHaveBeenCalledWith(['LEFT_ARM', 'JAW'])
  })

  it('reports a cleared number as unanswered rather than as zero', async () => {
    const onChange = vi.fn()
    render(
      <QuestionField
        question={{ ...base, kind: 'NUMBER', unit: 'days' }}
        value={7}
        onChange={onChange}
      />,
    )
    await userEvent.clear(screen.getByRole('spinbutton'))
    expect(onChange).toHaveBeenLastCalledWith(undefined)
  })

  it('shows the unit for a numeric question', () => {
    render(
      <QuestionField
        question={{ ...base, kind: 'NUMBER', unit: 'minutes' }}
        value={undefined}
        onChange={vi.fn()}
      />,
    )
    expect(screen.getByText('In minutes.')).toBeInTheDocument()
  })
})
