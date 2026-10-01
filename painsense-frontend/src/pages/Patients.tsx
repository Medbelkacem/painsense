import React, { useMemo, useState } from 'react';
import { Search, ChevronRight, User } from 'lucide-react';
import type { Patient } from '../types/clinical';

const mockPatients: Patient[] = [
  { id: 'PT-2026-00388', name: 'Eleanor Vance', age: 64, gender: 'Female', unit: 'ICU-West', bed: 'Bed 4', status: 'Critical', nrsScore: 8, aiEstimate: 8.2, lastUpdated: '12 mins ago' },
  { id: 'PT-2026-00389', name: 'Marcus Sterling', age: 52, gender: 'Male', unit: 'ICU-East', bed: 'Bed 12', status: 'Stable', nrsScore: 3, aiEstimate: 3.1, lastUpdated: '38 mins ago' },
  { id: 'PT-2026-00390', name: 'Sarah Jenkins', age: 41, gender: 'Female', unit: 'ICU-West', bed: 'Bed 2', status: 'Monitoring', nrsScore: 5, aiEstimate: 5.4, lastUpdated: '4 mins ago' },
];

// One colour per status. Folding Monitoring and Recovering in with Stable reads as
// "nothing to do here", which is not what either of them means.
const STATUS_STYLES: Record<Patient['status'], string> = {
  Critical: 'bg-red-500/10 text-red-400 border border-red-500/20',
  Monitoring: 'bg-amber-500/10 text-amber-400 border border-amber-500/20',
  Recovering: 'bg-blue-500/10 text-blue-400 border border-blue-500/20',
  Stable: 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20',
};

export const Patients: React.FC = () => {
  const [selectedPatient, setSelectedPatient] = useState<Patient | null>(null);
  const [query, setQuery] = useState('');

  const visiblePatients = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return mockPatients;
    return mockPatients.filter((p) =>
      [p.name, p.id, p.unit, p.bed].some((field) => field.toLowerCase().includes(needle)),
    );
  }, [query]);

  if (selectedPatient) {
    return (
      <div className="space-y-6">
        <button 
          onClick={() => setSelectedPatient(null)}
          className="text-xs text-blue-400 hover:underline flex items-center gap-1 font-medium"
        >
          ← Back to Patients List
        </button>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 flex justify-between items-start">
          <div className="flex items-center gap-4">
            <div className="w-14 h-14 rounded-full bg-blue-600/20 text-blue-400 flex items-center justify-center font-bold text-xl border border-blue-500/30">
              <User className="w-7 h-7" />
            </div>
            <div>
              <div className="flex items-center gap-3">
                <h1 className="text-xl font-bold text-white">{selectedPatient.name}</h1>
                <span className={`text-xs px-2 py-0.5 rounded font-semibold ${STATUS_STYLES[selectedPatient.status]}`}>{selectedPatient.status}</span>
              </div>
              <p className="text-xs text-slate-400 mt-1">{selectedPatient.id} • {selectedPatient.gender}, {selectedPatient.age} yrs • {selectedPatient.unit} ({selectedPatient.bed})</p>
            </div>
          </div>
          <button className="bg-blue-600 hover:bg-blue-500 text-white px-4 py-2 rounded-lg text-xs font-semibold shadow">
            Start New Assessment
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-2">
            <span className="text-xs text-slate-400">Patient-Reported NRS</span>
            <div className="text-3xl font-bold text-white">{selectedPatient.nrsScore} <span className="text-sm font-normal text-slate-500">/ 10</span></div>
            <p className="text-[10px] text-slate-500">Last recorded {selectedPatient.lastUpdated}</p>
          </div>
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-2">
            <span className="text-xs text-slate-400">AI Estimated Score</span>
            <div className="text-3xl font-bold text-blue-400">{selectedPatient.aiEstimate} <span className="text-sm font-normal text-slate-500">/ 10</span></div>
            <p className="text-[10px] text-slate-500">Model v1.6 (High Confidence)</p>
          </div>
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-2">
            <span className="text-xs text-slate-400">Clinical Priority</span>
            <div className="text-3xl font-bold text-amber-400">High</div>
            <p className="text-[10px] text-slate-500">Variance exceeds threshold</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">Patient Registry</h1>
          <p className="text-xs text-slate-400">Manage admitted ICU patients and pain diagnostics</p>
        </div>
        <div className="relative w-64">
          <Search className="absolute left-3 top-2.5 w-4 h-4 text-slate-500" />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search patient or ID..."
            aria-label="Search patients by name, identifier, unit or bed"
            className="w-full bg-slate-900 border border-slate-800 rounded-lg pl-9 pr-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-blue-500"
          />
        </div>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
        <table className="w-full text-left text-xs">
          <thead className="bg-slate-800/50 text-slate-400 border-b border-slate-800 uppercase tracking-wider">
            <tr>
              <th className="p-4">Patient ID & Name</th>
              <th className="p-4">Demographics</th>
              <th className="p-4">Location</th>
              <th className="p-4">Status</th>
              <th className="p-4">NRS / AI Score</th>
              <th className="p-4 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800 text-slate-300">
            {visiblePatients.map((p) => (
              <tr key={p.id} className="hover:bg-slate-800/40 transition">
                <td className="p-4 font-semibold text-white">
                  <div>{p.name}</div>
                  <span className="text-[10px] text-slate-500 font-normal">{p.id}</span>
                </td>
                <td className="p-4 text-slate-400">{p.gender}, {p.age} yrs</td>
                <td className="p-4">{p.unit} ({p.bed})</td>
                <td className="p-4">
                  <span className={`px-2 py-0.5 rounded text-[10px] font-medium ${STATUS_STYLES[p.status]}`}>
                    {p.status}
                  </span>
                </td>
                <td className="p-4 font-mono font-medium">{p.nrsScore} / <span className="text-blue-400">{p.aiEstimate}</span></td>
                <td className="p-4 text-right">
                  <button
                    onClick={() => setSelectedPatient(p)}
                    aria-label={`Open the record for ${p.name}`}
                    className="p-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition"
                  >
                    <ChevronRight className="w-4 h-4" />
                  </button>
                </td>
              </tr>
            ))}
            {visiblePatients.length === 0 && (
              <tr>
                <td colSpan={6} className="p-8 text-center text-slate-500">
                  No patient matches &ldquo;{query}&rdquo;.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};