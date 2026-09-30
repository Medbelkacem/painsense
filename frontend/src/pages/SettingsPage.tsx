import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'

import { useCreateDoctor, useDemoCases, useDoctors, useLoadDemo, useUpdateDoctor } from '@/api/queries'
import type { User } from '@/api/types'
import { useAuth } from '@/auth/AuthProvider'
import { PageHeader } from '@/components/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader, DescriptionList, DescriptionRow } from '@/components/ui/card'
import { Field, Input, Select } from '@/components/ui/field'
import { Notice, QueryState } from '@/components/ui/feedback'
import { Td, TableWrap, Th, Tr } from '@/components/ui/table'
import { formatDateTime } from '@/utils/format'
import { doctorSchema, type DoctorForm } from '@/validation/schemas'

export function SettingsPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'ADMIN'

  return (
    <>
      <PageHeader title="Settings" />

      <Card>
        <CardHeader title="Your account" />
        <CardBody>
          <DescriptionList>
            <DescriptionRow term="Name">{user?.display_name}</DescriptionRow>
            <DescriptionRow term="Email">{user?.email}</DescriptionRow>
            <DescriptionRow term="Role">
              {user?.role === 'ADMIN' ? 'Administrator' : 'Doctor'}
            </DescriptionRow>
            <DescriptionRow term="Speciality">{user?.speciality ?? '—'}</DescriptionRow>
            <DescriptionRow term="Registration">{user?.registration_number ?? '—'}</DescriptionRow>
            <DescriptionRow term="Last sign-in">{formatDateTime(user?.last_login_at)}</DescriptionRow>
          </DescriptionList>
        </CardBody>
      </Card>

      {isAdmin ? (
        <>
          <DemoSection />
          <AccountsSection />
        </>
      ) : (
        <Notice tone="info">
          Account management and demonstration data are available to administrators.
        </Notice>
      )}
    </>
  )
}

function DemoSection() {
  const cases = useDemoCases()
  const load = useLoadDemo()

  return (
    <Card>
      <CardHeader
        title="Demonstration cases"
        description="Seven synthetic patients covering different presentations. Loading is idempotent: a case already present is left alone."
        actions={
          <Button loading={load.isPending} onClick={() => load.mutate()}>
            Load demonstration cases
          </Button>
        }
      />
      <CardBody className="space-y-3">
        {load.isSuccess && (
          <Notice tone="info">
            {String(load.data.patients_created)} patients and{' '}
            {String(load.data.assessments_created)} assessments created. Every record is marked
            synthetic.
          </Notice>
        )}
        {load.isError && (
          <Notice tone="alert">
            {load.error instanceof Error ? load.error.message : 'Unexpected error'}
          </Notice>
        )}
        <ul className="divide-y divide-line">
          {cases.data?.map((entry) => (
            <li key={entry.ref} className="py-2.5">
              <p className="text-sm font-medium text-ink">
                {entry.title}
                <span className="ml-2 text-xs font-normal text-muted">
                  {entry.ward} · {entry.visits} visit{entry.visits === 1 ? '' : 's'}
                </span>
              </p>
              <p className="text-[0.8125rem] text-body">{entry.summary}</p>
            </li>
          ))}
        </ul>
      </CardBody>
    </Card>
  )
}

function AccountsSection() {
  const doctors = useDoctors()
  const create = useCreateDoctor()
  const [open, setOpen] = useState(false)

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<DoctorForm>({
    resolver: zodResolver(doctorSchema),
    defaultValues: { role: 'DOCTOR' },
  })

  const onSubmit = handleSubmit(async (values) => {
    await create.mutateAsync(values)
    reset({ role: 'DOCTOR' })
    setOpen(false)
  })

  return (
    <Card>
      <CardHeader
        title="Accounts"
        actions={
          <Button variant="secondary" onClick={() => setOpen((value) => !value)}>
            {open ? 'Cancel' : 'Add an account'}
          </Button>
        }
      />
      {open && (
        <CardBody className="border-b border-line">
          <form onSubmit={onSubmit} className="space-y-4" noValidate>
            {create.isError && (
              <Notice tone="alert">
                {create.error instanceof Error ? create.error.message : 'Unexpected error'}
              </Notice>
            )}
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Email" error={errors.email?.message} required>
                {(props) => <Input {...props} {...register('email')} type="email" />}
              </Field>
              <Field label="Name" error={errors.display_name?.message} required>
                {(props) => <Input {...props} {...register('display_name')} />}
              </Field>
              <Field
                label="Password"
                error={errors.password?.message}
                hint="At least 12 characters."
                required
              >
                {(props) => <Input {...props} {...register('password')} type="password" />}
              </Field>
              <Field label="Role">
                {(props) => (
                  <Select {...props} {...register('role')}>
                    <option value="DOCTOR">Doctor</option>
                    <option value="ADMIN">Administrator</option>
                  </Select>
                )}
              </Field>
              <Field label="Speciality">
                {(props) => <Input {...props} {...register('speciality')} />}
              </Field>
              <Field label="Registration number">
                {(props) => <Input {...props} {...register('registration_number')} />}
              </Field>
            </div>
            <Button type="submit" loading={isSubmitting}>
              Create account
            </Button>
          </form>
        </CardBody>
      )}
      <QueryState isPending={doctors.isPending} error={doctors.error}>
        <TableWrap>
          <thead>
            <tr>
              <Th>Name</Th>
              <Th>Email</Th>
              <Th>Role</Th>
              <Th>Last sign-in</Th>
              <Th>State</Th>
            </tr>
          </thead>
          <tbody>
            {doctors.data?.map((doctor) => (
              <AccountRow key={doctor.id} doctor={doctor} />
            ))}
          </tbody>
        </TableWrap>
      </QueryState>
    </Card>
  )
}

function AccountRow({ doctor }: { doctor: User }) {
  const update = useUpdateDoctor(doctor.id)
  const { user } = useAuth()

  return (
    <Tr>
      <Td className="font-medium text-ink">{doctor.display_name}</Td>
      <Td className="text-body">{doctor.email}</Td>
      <Td>
        <Badge tone={doctor.role === 'ADMIN' ? 'accent' : 'neutral'}>
          {doctor.role === 'ADMIN' ? 'Administrator' : 'Doctor'}
        </Badge>
      </Td>
      <Td className="text-muted">{formatDateTime(doctor.last_login_at)}</Td>
      <Td>
        {doctor.id === user?.id ? (
          <span className="text-xs text-muted">You</span>
        ) : (
          <Button
            size="sm"
            variant="ghost"
            loading={update.isPending}
            onClick={() => update.mutate({ is_active: !doctor.is_active })}
          >
            {doctor.is_active ? 'Disable' : 'Enable'}
          </Button>
        )}
      </Td>
    </Tr>
  )
}
