import { z } from 'zod'

export const credentialsSchema = z.object({
  email: z.string().min(1, 'Enter your email address').email('That is not a valid email address'),
  password: z.string().min(1, 'Enter your password'),
})
export type Credentials = z.infer<typeof credentialsSchema>

const optionalText = (max: number) =>
  z
    .string()
    .max(max)
    .transform((value) => value.trim())
    .transform((value) => (value === '' ? undefined : value))
    .optional()

export const patientSchema = z.object({
  given_name: z.string().min(1, 'Required').max(120),
  family_name: z.string().min(1, 'Required').max(120),
  phone: optionalText(255),
  emergency_contact_name: optionalText(255),
  emergency_contact_phone: optionalText(255),
  sex: z.enum(['F', 'M', 'OTHER', 'UNDISCLOSED']),
  birth_date: z
    .string()
    .optional()
    .refine(
      (value) => !value || new Date(value) <= new Date(),
      'The date of birth cannot be in the future',
    ),
  ward: optionalText(80),
  smoking_status: z.enum(['NEVER', 'FORMER', 'CURRENT', 'UNKNOWN']),
  medical_history: optionalText(4000),
  previous_surgeries: optionalText(4000),
  allergies: optionalText(4000),
  family_history: optionalText(4000),
  lifestyle_notes: optionalText(4000),
})
export type PatientForm = z.infer<typeof patientSchema>

/**
 * Bounds match the API, which in turn takes them from the estimator's plausibility table.
 * A value outside these is a recording error; a value inside but abnormal is accepted as
 * entered and flagged later.
 */
export const VITAL_BOUNDS = {
  hr: [10, 300],
  resp_rate: [2, 80],
  sbp: [40, 300],
  dbp: [20, 200],
  spo2: [30, 100],
  temperature_c: [25, 45],
  glucose_mmol: [0.5, 60],
  weight_kg: [1, 400],
  height_cm: [31, 260],
} as const

export const doctorSchema = z.object({
  email: z.string().email('That is not a valid email address'),
  display_name: z.string().min(1, 'Required').max(255),
  password: z.string().min(12, 'At least 12 characters'),
  role: z.enum(['DOCTOR', 'ADMIN']),
  speciality: optionalText(255),
  registration_number: optionalText(255),
})
export type DoctorForm = z.infer<typeof doctorSchema>

export const PROFESSIONS = [
  { value: 'DOCTOR', label: 'Doctor' },
  { value: 'NURSE', label: 'Nurse' },
  { value: 'RESIDENT', label: 'Resident' },
  { value: 'OTHER', label: 'Other clinical role' },
] as const

export const registrationSchema = z
  .object({
    display_name: z.string().min(2, 'Enter your name').max(120),
    email: z.string().min(1, 'Enter your email address').email('That is not a valid email address'),
    password: z.string().min(12, 'At least 12 characters'),
    clinic_name: z.string().min(2, 'Enter the name of your clinic or hospital').max(160),
    phone: z.string().min(5, 'Enter a telephone number').max(48),
    profession: z.enum(['DOCTOR', 'NURSE', 'RESIDENT', 'OTHER']),
    speciality: optionalText(255),
    registration_number: optionalText(255),
  })
  // The API applies the same rule; repeating it here is what lets the field show its own
  // message instead of the form failing on submit.
  .refine((values) => values.profession !== 'DOCTOR' || Boolean(values.speciality), {
    message: 'Enter your speciality',
    path: ['speciality'],
  })

export type RegistrationForm = z.infer<typeof registrationSchema>
