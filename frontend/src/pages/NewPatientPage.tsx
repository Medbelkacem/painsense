import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { useNavigate } from 'react-router-dom'

import { useCreatePatient } from '@/api/queries'
import type { Medication } from '@/api/types'
import { PageHeader } from '@/components/PageHeader'
import { Button } from '@/components/ui/button'
import { Card, CardBody } from '@/components/ui/card'
import { Notice } from '@/components/ui/feedback'
import {
  ConditionPicker,
  DemographicFields,
  HistoryFields,
  IdentityFields,
  MedicationEditor,
} from '@/forms/PatientFields'
import { patientSchema, type PatientForm } from '@/validation/schemas'

export function NewPatientPage() {
  const navigate = useNavigate()
  const createPatient = useCreatePatient()
  const [conditions, setConditions] = useState<string[]>([])
  const [medications, setMedications] = useState<Medication[]>([])

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<PatientForm>({
    resolver: zodResolver(patientSchema),
    defaultValues: { sex: 'UNDISCLOSED', smoking_status: 'UNKNOWN' },
  })

  const onSubmit = handleSubmit(async (values) => {
    const { given_name, family_name, phone, emergency_contact_name, emergency_contact_phone, ...rest } =
      values
    const patient = await createPatient.mutateAsync({
      ...rest,
      birth_date: rest.birth_date || null,
      identity: {
        given_name,
        family_name,
        phone,
        emergency_contact_name,
        emergency_contact_phone,
      },
      condition_codes: conditions,
      medications: medications.filter((item) => item.name.trim()),
    })
    navigate(`/patients/${patient.id}`)
  })

  return (
    <>
      <PageHeader
        title="New patient"
        description="The record is given an internal code. Direct identifiers are sealed before storage."
      />

      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        {createPatient.isError && (
          <Notice tone="alert" title="The record was not created">
            {createPatient.error instanceof Error ? createPatient.error.message : 'Unexpected error'}
          </Notice>
        )}

        <Card>
          <CardBody className="space-y-6">
            <IdentityFields register={register} errors={errors} />
            <DemographicFields register={register} errors={errors} />
          </CardBody>
        </Card>

        <Card>
          <CardBody className="space-y-6">
            <ConditionPicker
              selected={conditions}
              onToggle={(code) =>
                setConditions((current) =>
                  current.includes(code)
                    ? current.filter((item) => item !== code)
                    : [...current, code],
                )
              }
            />
            <MedicationEditor medications={medications} onChange={setMedications} />
            <HistoryFields register={register} />
          </CardBody>
        </Card>

        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={() => navigate('/patients')}>
            Cancel
          </Button>
          <Button type="submit" loading={isSubmitting}>
            Create patient
          </Button>
        </div>
      </form>
    </>
  )
}
