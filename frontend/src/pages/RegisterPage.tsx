import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, Navigate, useNavigate } from 'react-router-dom'

import { api, setAccessToken } from '@/api/client'
import type { TokenResponse } from '@/api/types'
import { useAuth } from '@/auth/AuthProvider'
import { AuthPanel } from '@/components/AuthPanel'
import { Button } from '@/components/ui/button'
import { Field, Input, Select } from '@/components/ui/field'
import { Notice } from '@/components/ui/feedback'
import { PROFESSIONS, registrationSchema, type RegistrationForm } from '@/validation/schemas'

export function RegisterPage() {
  const { user, ready, refresh } = useAuth()
  const navigate = useNavigate()
  const [failure, setFailure] = useState<string | null>(null)

  const {
    register,
    handleSubmit,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<RegistrationForm>({
    resolver: zodResolver(registrationSchema),
    defaultValues: { profession: 'DOCTOR' },
  })

  const profession = watch('profession')

  if (ready && user) return <Navigate to="/dashboard" replace />

  const onSubmit = handleSubmit(async (values) => {
    setFailure(null)
    try {
      const response = await api.post<TokenResponse>('/api/auth/register', values)
      setAccessToken(response.access_token)
      refresh(response.user)
      navigate('/dashboard', { replace: true })
    } catch (error) {
      setFailure(error instanceof Error ? error.message : 'The account could not be created')
    }
  })

  return (
    <AuthPanel
      title="Create your account"
      subtitle="For clinicians. An account gives access to the records you create."
    >
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        {failure && <Notice tone="alert">{failure}</Notice>}

        <Field label="Your name" error={errors.display_name?.message} required>
          {(props) => (
            <Input {...props} {...register('display_name')} autoComplete="name" autoFocus />
          )}
        </Field>

        <Field
          label="Clinic or hospital"
          error={errors.clinic_name?.message}
          hint="The organisation this account belongs to."
          required
        >
          {(props) => (
            <Input {...props} {...register('clinic_name')} autoComplete="organization" />
          )}
        </Field>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Role" error={errors.profession?.message} required>
            {(props) => (
              <Select {...props} {...register('profession')}>
                {PROFESSIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </Select>
            )}
          </Field>

          <Field label="Telephone" error={errors.phone?.message} required>
            {(props) => <Input {...props} {...register('phone')} type="tel" autoComplete="tel" />}
          </Field>
        </div>

        {profession === 'DOCTOR' && (
          <div className="grid gap-4 border-l-2 border-line pl-4 sm:grid-cols-2">
            <Field label="Speciality" error={errors.speciality?.message} required>
              {(props) => (
                <Input {...props} {...register('speciality')} placeholder="Anaesthesia and pain medicine" />
              )}
            </Field>
            <Field label="Registration number" error={errors.registration_number?.message}>
              {(props) => <Input {...props} {...register('registration_number')} />}
            </Field>
          </div>
        )}

        <Field label="Email address" error={errors.email?.message} required>
          {(props) => <Input {...props} {...register('email')} type="email" autoComplete="username" />}
        </Field>

        <Field
          label="Password"
          error={errors.password?.message}
          hint="At least 12 characters. A passphrase of a few words is easier to remember."
          required
        >
          {(props) => (
            <Input {...props} {...register('password')} type="password" autoComplete="new-password" />
          )}
        </Field>

        <Button type="submit" className="w-full" loading={isSubmitting}>
          Create account
        </Button>

        <p className="text-center text-[0.8125rem] text-muted">
          Already have an account?{' '}
          <Link to="/login" className="font-medium text-accent hover:underline">
            Log in
          </Link>
        </p>
      </form>
    </AuthPanel>
  )
}
