import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from './client'
import type {
  Analytics,
  AnatomyOntology,
  AssessmentDetail,
  AssessmentSummary,
  AuditEntry,
  Band,
  Comparison,
  Confounder,
  DatasetVersion,
  DemoCase,
  Disease,
  Factor,
  History,
  IntegrityStatus,
  Location,
  MedicalDocument,
  ModelStatus,
  ModelVersion,
  Page,
  PainType,
  PatientDetail,
  PatientSummary,
  Quality,
  Question,
  QuestionContext,
  SecurityStatus,
  Symptom,
  User,
  VitalRange,
} from './types'

/** Reference data changes only when the deployment is upgraded, so it is cached for the session. */
const CATALOGUE = { staleTime: Infinity, gcTime: Infinity }

export const keys = {
  patients: (query: string) => ['patients', query] as const,
  patient: (id: string) => ['patient', id] as const,
  history: (id: string) => ['history', id] as const,
  assessments: (query: string) => ['assessments', query] as const,
  assessment: (id: string) => ['assessment', id] as const,
  documents: (query: string) => ['documents', query] as const,
  analytics: ['analytics'] as const,
  integrity: ['integrity'] as const,
  security: ['security'] as const,
  audit: (query: string) => ['audit', query] as const,
  datasets: ['datasets'] as const,
  model: ['model'] as const,
  doctors: ['doctors'] as const,
}

function catalogue<T>(name: string, path: string) {
  return () => useQuery({ queryKey: [name], queryFn: () => api.get<T[]>(path), ...CATALOGUE })
}

export const useLocations = catalogue<Location>('locations', '/api/pain-locations')
export const useQualities = catalogue<Quality>('qualities', '/api/pain-qualities')
export const usePainTypes = catalogue<PainType>('pain-types', '/api/pain-types')
export const useSymptoms = catalogue<Symptom>('symptoms', '/api/symptoms')
export const useDiseases = catalogue<Disease>('diseases', '/api/diseases')
export const useFactors = catalogue<Factor>('factors', '/api/pain-factors')
export const useConfounders = catalogue<Confounder>('confounders', '/api/confounders')
export const useBands = catalogue<Band>('bands', '/api/pain-bands')
export const useVitalRanges = catalogue<VitalRange>('vital-ranges', '/api/physiology/ranges')
export const useAllQuestions = catalogue<Question>('questions', '/api/clinical-questions')
export const useDemoCases = catalogue<DemoCase>('demo-cases', '/api/demo/cases')

/**
 * The anatomy ontology behind the 3D model. One payload, cached for the session like the
 * rest of the catalogue: it changes only when the deployment is upgraded.
 */
export const useAnatomy = () =>
  useQuery({
    queryKey: ['anatomy'],
    queryFn: () => api.get<AnatomyOntology>('/api/anatomy'),
    ...CATALOGUE,
  })

export function useApplicableQuestions(context: QuestionContext, enabled = true) {
  return useQuery({
    queryKey: ['applicable-questions', context],
    queryFn: () => api.post<Question[]>('/api/clinical-questions/applicable', context),
    enabled,
    placeholderData: (previous) => previous,
  })
}

export function usePatients(params: URLSearchParams) {
  const query = params.toString()
  return useQuery({
    queryKey: keys.patients(query),
    queryFn: () => api.get<Page<PatientSummary>>(`/api/patients?${query}`),
    placeholderData: (previous) => previous,
  })
}

export const usePatient = (id?: string) =>
  useQuery({
    queryKey: keys.patient(id ?? ''),
    queryFn: () => api.get<PatientDetail>(`/api/patients/${id}`),
    enabled: Boolean(id),
  })

export const usePatientHistory = (id?: string) =>
  useQuery({
    queryKey: keys.history(id ?? ''),
    queryFn: () => api.get<History>(`/api/patients/${id}/history`),
    enabled: Boolean(id),
  })

export const usePatientAssessments = (id?: string) =>
  useQuery({
    queryKey: ['patient-assessments', id],
    queryFn: () => api.get<AssessmentSummary[]>(`/api/patients/${id}/assessments`),
    enabled: Boolean(id),
  })

export function useCreatePatient() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: unknown) => api.post<PatientDetail>('/api/patients', body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['patients'] }),
  })
}

export function useUpdatePatient(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: unknown) => api.patch<PatientDetail>(`/api/patients/${id}`, body),
    onSuccess: (patient) => {
      queryClient.setQueryData(keys.patient(id), patient)
      queryClient.invalidateQueries({ queryKey: ['patients'] })
    },
  })
}

export function useArchivePatient(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<PatientDetail>(`/api/patients/${id}/archive`),
    onSuccess: (patient) => {
      queryClient.setQueryData(keys.patient(id), patient)
      queryClient.invalidateQueries({ queryKey: ['patients'] })
    },
  })
}

export function useAssessments(params: URLSearchParams) {
  const query = params.toString()
  return useQuery({
    queryKey: keys.assessments(query),
    queryFn: () => api.get<Page<AssessmentSummary>>(`/api/assessments?${query}`),
    placeholderData: (previous) => previous,
  })
}

export const useAssessment = (id?: string) =>
  useQuery({
    queryKey: keys.assessment(id ?? ''),
    queryFn: () => api.get<AssessmentDetail>(`/api/assessments/${id}`),
    enabled: Boolean(id),
  })

export const useComparison = (current?: string, previous?: string) =>
  useQuery({
    queryKey: ['comparison', current, previous],
    queryFn: () => api.get<Comparison>(`/api/assessments/${current}/compare/${previous}`),
    enabled: Boolean(current && previous),
  })

export function useCreateAssessment() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: unknown) => api.post<AssessmentDetail>('/api/assessments', body),
    onSuccess: (assessment) => {
      queryClient.setQueryData(keys.assessment(assessment.id), assessment)
      queryClient.invalidateQueries({ queryKey: ['assessments'] })
      queryClient.invalidateQueries({ queryKey: ['patient-assessments'] })
    },
  })
}

function assessmentAction(path: (id: string) => string) {
  return function useAction(id: string) {
    const queryClient = useQueryClient()
    return useMutation({
      mutationFn: (body?: unknown) => api.post<AssessmentDetail>(path(id), body),
      onSuccess: (assessment) => {
        queryClient.setQueryData(keys.assessment(id), assessment)
        queryClient.invalidateQueries({ queryKey: ['assessments'] })
        queryClient.invalidateQueries({ queryKey: ['patient-assessments'] })
        queryClient.invalidateQueries({ queryKey: keys.history(assessment.patient_id) })
        queryClient.invalidateQueries({ queryKey: keys.analytics })
        queryClient.invalidateQueries({ queryKey: keys.integrity })
      },
    })
  }
}

export const useRunEstimate = assessmentAction((id) => `/api/assessments/${id}/predict`)
export const useValidateAssessment = assessmentAction((id) => `/api/assessments/${id}/validate`)

export function useUpdateAssessment(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: unknown) => api.patch<AssessmentDetail>(`/api/assessments/${id}`, body),
    onSuccess: (assessment) => queryClient.setQueryData(keys.assessment(id), assessment),
  })
}

export function useAddNote(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: string) => api.post(`/api/assessments/${id}/notes`, { body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.assessment(id) }),
  })
}

export function useDocuments(params: URLSearchParams) {
  const query = params.toString()
  return useQuery({
    queryKey: keys.documents(query),
    queryFn: () => api.get<MedicalDocument[]>(`/api/documents?${query}`),
  })
}

export function useUploadDocument() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (form: FormData) => api.upload<MedicalDocument>('/api/documents', form),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] })
      queryClient.invalidateQueries({ queryKey: ['assessment'] })
    },
  })
}

export function useSetFindings(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (findings: string) => api.patch(`/api/documents/${id}`, { findings }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['documents'] }),
  })
}

export const useAnalytics = () =>
  useQuery({ queryKey: keys.analytics, queryFn: () => api.get<Analytics>('/api/analytics') })

export const useIntegrity = () =>
  useQuery({
    queryKey: keys.integrity,
    queryFn: () => api.get<IntegrityStatus>('/api/integrity/status'),
  })

export function useVerifyIntegrity() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<IntegrityStatus>('/api/integrity/verify'),
    onSuccess: (status) => {
      queryClient.setQueryData(keys.integrity, status)
      queryClient.invalidateQueries({ queryKey: keys.security })
    },
  })
}

export const useSecurity = () =>
  useQuery({ queryKey: keys.security, queryFn: () => api.get<SecurityStatus>('/api/security') })

export function useAudit(params: URLSearchParams) {
  const query = params.toString()
  return useQuery({
    queryKey: keys.audit(query),
    queryFn: () => api.get<Page<AuditEntry>>(`/api/audit?${query}`),
    placeholderData: (previous) => previous,
  })
}

export const useDatasets = () =>
  useQuery({ queryKey: keys.datasets, queryFn: () => api.get<DatasetVersion[]>('/api/datasets') })

export function useGenerateDataset() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { rows: number; seed: number }) =>
      api.post<DatasetVersion>('/api/datasets/generate', body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.datasets }),
  })
}

export const useModelStatus = () =>
  useQuery({ queryKey: keys.model, queryFn: () => api.get<ModelStatus>('/api/ai-model') })

export function useTrainModel() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: { test_size: number; seed: number; cv_folds: number }) =>
      api.post<ModelVersion>('/api/ai-model/train', body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.model })
      queryClient.invalidateQueries({ queryKey: keys.integrity })
    },
  })
}

export function useActivateModel() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (version: string) => api.post<ModelVersion>(`/api/ai-model/${version}/activate`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.model }),
  })
}

export const useDoctors = () =>
  useQuery({ queryKey: keys.doctors, queryFn: () => api.get<User[]>('/api/doctors') })

export function useCreateDoctor() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: unknown) => api.post<User>('/api/doctors', body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.doctors }),
  })
}

export function useUpdateDoctor(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: unknown) => api.patch<User>(`/api/doctors/${id}`, body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.doctors }),
  })
}

export function useLoadDemo() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<Record<string, unknown>>('/api/demo/load'),
    onSuccess: () => queryClient.invalidateQueries(),
  })
}

export async function downloadReport(assessmentId: string, filename: string) {
  const blob = await api.post<Blob>(`/api/reports/${assessmentId}/generate`)
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.append(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
