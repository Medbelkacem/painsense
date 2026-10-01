import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { LandingPage } from './pages/LandingPage';
import { SignIn } from './pages/SignIn';
import { AppLayout } from './components/layouts/AppLayout';
import { Dashboard } from './pages/Dashboard';
import { Patients } from './pages/Patients';
import { AIAnalysis } from './pages/AIAnalysis';
import { PlaceholderView } from './pages/GenericViews';

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Landing Page (Shows at http://localhost:5173/) */}
        <Route path="/" element={<LandingPage />} />
        
        {/* Sign In page */}
        <Route path="/login" element={<SignIn />} />

        {/* Authenticated Dashboard Workspace */}
        <Route element={<AppLayout />}>
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/patients" element={<Patients />} />
          <Route path="/assessments" element={<PlaceholderView title="ICU Assessments" subtitle="Guided bedside and automated pain evaluation logs" />} />
          <Route path="/ai-analysis" element={<AIAnalysis />} />
          <Route path="/analytics" element={<PlaceholderView title="Advanced Analytics" subtitle="Cross-patient telemetry and neural model performance" />} />
          <Route path="/ai-models" element={<PlaceholderView title="AI Models Management" subtitle="Version control and weight calibrations for neural scoring" />} />
          <Route path="/dataset" element={<PlaceholderView title="Clinical Dataset" subtitle="Secure anonymized training data and validation vaults" />} />
          <Route path="/documents" element={<PlaceholderView title="Clinical Documents" subtitle="Protocols, hospital guidelines, and compliance records" />} />
          <Route path="/reports" element={<PlaceholderView title="Reports Generator" subtitle="Exportable PDF intensive care telemetry summaries" />} />
          <Route path="/security" element={<PlaceholderView title="Integrity & Security" subtitle="Role-based access control, encryption keys, and HIPAA logs" />} />
          <Route path="/audit" element={<PlaceholderView title="Audit Trail" subtitle="Complete system activity and clinician interaction log" />} />
          <Route path="/settings" element={<PlaceholderView title="System Settings" subtitle="Bedside hardware links, alert thresholds, and preferences" />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;