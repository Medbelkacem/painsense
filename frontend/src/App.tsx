import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { ThemeProvider } from './theme';
import { SessionProvider } from './auth/session';
import { RequireSession } from './auth/RequireSession';
import { AppLayout } from './components/layouts/AppLayout';
import { LandingPage } from './pages/LandingPage';
import { SignIn } from './pages/SignIn';
import { Dashboard } from './pages/Dashboard';
import { Patients } from './pages/Patients';
import { PatientProfile } from './pages/PatientProfile';
import { Assessments } from './pages/Assessments';
import { NewAssessment } from './pages/NewAssessment';
import { AIAnalysis } from './pages/AIAnalysis';
import { Analytics } from './pages/Analytics';
import { AIModels } from './pages/AIModels';
import { Dataset } from './pages/Dataset';
import { Documents } from './pages/Documents';
import { Reports } from './pages/Reports';
import { Security } from './pages/Security';
import { Audit } from './pages/Audit';
import { Settings } from './pages/Settings';
import { ExternalDatasets } from './pages/ExternalDatasets';

export function App() {
  return (
    <ThemeProvider>
      <SessionProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<LandingPage />} />
            <Route path="/login" element={<SignIn />} />

            <Route element={<RequireSession />}>
              <Route element={<AppLayout />}>
                <Route path="/dashboard" element={<Dashboard />} />
                <Route path="/patients" element={<Patients />} />
                <Route path="/patients/:id" element={<PatientProfile />} />
                <Route path="/assessments" element={<Assessments />} />
                <Route path="/assessments/new" element={<NewAssessment />} />
                <Route path="/ai-analysis" element={<AIAnalysis />} />
                <Route path="/analytics" element={<Analytics />} />
                <Route path="/ai-models" element={<AIModels />} />
                <Route path="/dataset" element={<Dataset />} />
                <Route path="/reports" element={<Reports />} />
                <Route path="/documents" element={<Documents />} />
                <Route path="/external-datasets" element={<ExternalDatasets />} />
                <Route path="/security" element={<Security />} />
                <Route path="/audit" element={<Audit />} />
                <Route path="/settings" element={<Settings />} />
              </Route>
            </Route>

            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </SessionProvider>
    </ThemeProvider>
  );
}

export default App;
