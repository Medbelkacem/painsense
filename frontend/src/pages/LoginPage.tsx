import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'

import { useAuth } from '@/auth/AuthProvider'
import { AuthPanel } from '@/components/AuthPanel'
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
    <AuthPanel title="Log in" subtitle="Use your clinical workspace account.">
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
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
          Log in
        </Button>

        <p className="text-center text-[0.8125rem] text-muted">
          No account yet?{' '}
          <Link to="/register" className="font-medium text-accent hover:underline">
            Sign up
          </Link>
        </p>
      </form>
    </AuthPanel>
  )
}
