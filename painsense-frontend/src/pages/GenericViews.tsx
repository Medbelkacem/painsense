
import React from 'react';

export const PlaceholderView: React.FC<{ title: string; subtitle: string }> = ({ title, subtitle }) => (
  <div className="space-y-6">
    <div>
      <h1 className="text-2xl font-bold tracking-tight text-white">{title}</h1>
      <p className="text-xs text-slate-400">{subtitle}</p>
    </div>
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-12 text-center text-slate-500 space-y-3">
      <div className="text-sm">Module active and ready for data ingestion.</div>
      <div className="text-xs text-slate-600">All audit parameters and telemetry feeds are synced with HIPAA cloud storage.</div>
    </div>
  </div>
);