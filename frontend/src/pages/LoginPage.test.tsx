import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { useAuth } from '@/auth/AuthProvider'
import { renderWithProviders } from '@/test/render'
import { LoginPage } from './LoginPage'

vi.mock('@/auth/AuthProvider', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/auth/AuthProvider')>()
  return { ...actual, useAuth: vi.fn() }
})

const mockedUseAuth = vi.mocked(useAuth)

function setup(signIn = vi.fn()) {
  mockedUseAuth.mockReturnValue({ user: null, ready: true, signIn, signOut: vi.fn() })
  renderWithProviders(<LoginPage />)
  return signIn
}

describe('LoginPage', () => {
  it('refuses to submit an address that is not one', async () => {
    const signIn = setup()
    await userEvent.type(screen.getByLabelText(/Email address/), 'not-an-address')
    await userEvent.type(screen.getByLabelText(/Password/), 'a-password')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByText('That is not a valid email address')).toBeInTheDocument()
    expect(signIn).not.toHaveBeenCalled()
  })

  it('passes the credentials on when they are complete', async () => {
    const signIn = setup(vi.fn().mockResolvedValue(undefined))
    await userEvent.type(screen.getByLabelText(/Email address/), 's.benali@chu-batna.dz')
    await userEvent.type(screen.getByLabelText(/Password/), 'Consultation-Batna-2026')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    await waitFor(() =>
      expect(signIn).toHaveBeenCalledWith('s.benali@chu-batna.dz', 'Consultation-Batna-2026'),
    )
  })

  it('shows what went wrong when sign-in is refused', async () => {
    setup(vi.fn().mockRejectedValue(new Error('Invalid credentials')))
    await userEvent.type(screen.getByLabelText(/Email address/), 's.benali@chu-batna.dz')
    await userEvent.type(screen.getByLabelText(/Password/), 'wrong')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByText('Invalid credentials')).toBeInTheDocument()
  })

  it('carries the disclaimer', () => {
    setup()
    expect(screen.getByText(/does not constitute a medical diagnosis/)).toBeInTheDocument()
  })
})
