import type { ComponentType } from 'react'
import { Navigate, createBrowserRouter } from 'react-router-dom'

import { RequireAuth } from '@/auth/RequireAuth'
import { AppLayout } from '@/layouts/AppLayout'
import { LoginPage } from '@/pages/LoginPage'
import { NotFoundPage } from '@/pages/NotFoundPage'

/**
 * Everything past the dashboard is fetched when it is first opened.
 *
 * The charting library alone is most of the bundle, and the sign-in screen needs none
 * of it, so loading everything up front costs the first paint for nothing.
 */
function page(load: () => Promise<Record<string, unknown>>, name: string) {
  return async () => ({ Component: (await load())[name] as ComponentType })
}

export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  {
    element: (
      <RequireAuth>
        <AppLayout />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <Navigate to="/dashboard" replace /> },
      { path: 'dashboard', lazy: page(() => import('@/pages/DashboardPage'), 'DashboardPage') },
      {
        path: 'patients',
        lazy: page(() => import('@/pages/PatientsPage'), 'PatientsPage'),
      },
      {
        path: 'patients/new',
        lazy: page(() => import('@/pages/NewPatientPage'), 'NewPatientPage'),
      },
      {
        path: 'patients/:patientId',
        lazy: page(() => import('@/pages/PatientPage'), 'PatientPage'),
      },
      {
        path: 'patients/:patientId/assessment',
        lazy: page(() => import('@/pages/AssessmentWizardPage'), 'AssessmentWizardPage'),
      },
      {
        path: 'patients/:patientId/history',
        lazy: page(() => import('@/pages/PatientHistoryPage'), 'PatientHistoryPage'),
      },
      {
        path: 'assessments/:assessmentId',
        lazy: page(() => import('@/pages/AssessmentPage'), 'AssessmentPage'),
      },
      { path: 'analytics', lazy: page(() => import('@/pages/AnalyticsPage'), 'AnalyticsPage') },
      { path: 'reports', lazy: page(() => import('@/pages/ReportsPage'), 'ReportsPage') },
      { path: 'datasets', lazy: page(() => import('@/pages/DatasetsPage'), 'DatasetsPage') },
      { path: 'ai-model', lazy: page(() => import('@/pages/ModelPage'), 'ModelPage') },
      { path: 'integrity', lazy: page(() => import('@/pages/IntegrityPage'), 'IntegrityPage') },
      { path: 'security', lazy: page(() => import('@/pages/SecurityPage'), 'SecurityPage') },
      { path: 'audit', lazy: page(() => import('@/pages/AuditPage'), 'AuditPage') },
      {
        path: 'architecture',
        lazy: page(() => import('@/pages/ArchitecturePage'), 'ArchitecturePage'),
      },
      { path: 'settings', lazy: page(() => import('@/pages/SettingsPage'), 'SettingsPage') },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])
