export interface Patient {
  id: string;
  name: string;
  age: number;
  gender: string;
  unit: string;
  bed: string;
  status: 'Stable' | 'Critical' | 'Monitoring' | 'Recovering';
  nrsScore: number;
  aiEstimate: number;
  lastUpdated: string;
}

export interface AssessmentRecord {
  id: string;
  patientId: string;
  patientName: string;
  timestamp: string;
  location: string;
  nrs: number;
  aiScore: number;
  priority: 'Low' | 'Moderate' | 'High' | 'Severe';
  status: 'Completed' | 'Pending Review';
}