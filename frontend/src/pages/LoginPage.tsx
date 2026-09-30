import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'

import { useAuth } from '@/auth/AuthProvider'
import { DISCLAIMER } from '@/components/Disclaimer'
import { Button } from '@/components/ui/button'
import { Field, Input } from '@/components/ui/field'
import { Notice } from '@/components/ui/feedback'
import { credentialsSchema, type Credentials } from '@/validation/schemas'

export function LoginPage() {
  const { user, ready, signIn } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [failure, setFailure] = useState<string | null>(null)

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Credentials>({
    resolver: zodResolver(credentialsSchema),
    defaultValues: { email: '', password: '' },
  })

  if (ready && user) return <Navigate to="/dashboard" replace />

  const onSubmit = handleSubmit(async (values) => {
    setFailure(null)
    try {
      await signIn(values.email, values.password)
      navigate((location.state as { from?: string } | null)?.from ?? '/dashboard', { replace: true })
    } catch (error) {
      setFailure(error instanceof Error ? error.message : 'Sign-in failed')
    }
  })

  return (
    <div className="flex min-h-dvh flex-col items-center justify-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-3">
          <img src="/icon.svg" alt="" className="size-10 rounded-lg" />
          <div>
            <h1 className="text-lg font-semibold text-ink">Pain Score</h1>
            <p className="text-[0.8125rem] text-muted">Clinical decision support</p>
          </div>
        </div>

        <form
          onSubmit={onSubmit}
          className="space-y-4 rounded-lg border border-line bg-surface p-5"
          noValidate
        >
          <div>
            <h2 className="text-sm font-semibold text-ink">Sign in</h2>
            <p className="mt-0.5 text-[0.8125rem] text-muted">
              Accounts are created by an administrator.
            </p>
          </div>

          {failure && <Notice tone="alert">{failure}</Notice>}

          <Field label="Email address" error={errors.email?.message} required>
            {(props) => (
              <Input
                {...props}
                {...register('email')}
                type="email"
                autoComplete="username"
                autoFocus
                placeholder="name@hospital.example"
              />
            )}
          </Field>

          <Field label="Password" error={errors.password?.message} required>
            {(props) => (
              <Input
                {...props}
                {...register('password')}
                type="password"
                autoComplete="current-password"
              />
            )}
          </Field>

          <Button type="submit" className="w-full" loading={isSubmitting}>
            Sign in
          </Button>
        </form>

        <p className="mt-5 text-xs leading-relaxed text-muted">{DISCLAIMER}</p>
      </div>
    </div>
  )
}
