import React from 'react';
import { LineChart, Line, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, CartesianGrid } from 'recharts';
import { BrainCircuit, AlertCircle } from 'lucide-react';

const analysisData = [
  { time: '00:00', ai: 6.4, nrs: 6.0 },
  { time: '04:00', ai: 6.8, nrs: 6.5 },
  { time: '08:00', ai: 7.2, nrs: 7.0 },
  { time: '12:00', ai: 7.9, nrs: 8.2 },
  { time: '16:00', ai: 7.1, nrs: 7.0 },
];

// Read off the latest reading rather than hard-coded, so the sentence underneath can never
// contradict the chart above it.
const latest = analysisData[analysisData.length - 1];
const variance = Number((latest.ai - latest.nrs).toFixed(1));

export const AIAnalysis: React.FC = () => {
  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
            <BrainCircuit className="text-blue-500" /> AI Diagnostic Analysis
          </h1>
          <p className="text-xs text-slate-400">Step 6 of 7 • Compare model estimate vs. patient report before clinical review</p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="md:col-span-2 bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
          <h2 className="text-sm font-semibold text-slate-200">Pain Trajectory & Model Variance</h2>
          <div className="h-72 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={analysisData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="time" stroke="#64748b" fontSize={12} />
                <YAxis domain={[0, 10]} stroke="#64748b" fontSize={12} />
                <Tooltip contentStyle={{ backgroundColor: '#0f172a', borderColor: '#334155', borderRadius: '8px', color: '#f8fafc' }} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Line type="monotone" dataKey="ai" stroke="#3b82f6" strokeWidth={2} name="AI Model v1.6" />
                <Line type="monotone" dataKey="nrs" stroke="#10b981" strokeWidth={2} name="Patient Reported" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-6">
          <div className="space-y-2">
            <span className="text-xs text-slate-400">Clinical Priority Index</span>
            <div className="text-4xl font-extrabold text-amber-400">8.2 <span className="text-xs font-normal text-slate-500">/ 10</span></div>
            <p className="text-xs text-slate-400 bg-amber-500/10 border border-amber-500/20 p-3 rounded-lg flex gap-2">
              <AlertCircle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
              <span>
                At {latest.time}, the AI estimate is {Math.abs(variance).toFixed(1)} points{' '}
                {variance === 0 ? 'from' : variance > 0 ? 'above' : 'below'} the patient report
                ({latest.ai.toFixed(1)} against {latest.nrs.toFixed(1)}). To be confirmed by a
                clinician.
              </span>
            </p>
          </div>

          <div className="space-y-3 pt-4 border-t border-slate-800 text-xs text-slate-300">
            <div className="flex justify-between">
              <span className="text-slate-500">Heartrate (Avg)</span>
              <span className="font-mono font-semibold">96 BPM</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Facial Muscle Tension</span>
              <span className="font-mono font-semibold">High (+2.4)</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Respiration Telemetry</span>
              <span className="font-mono font-semibold">22 resp/min</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};