import React from 'react';
import { AreaChart, Area, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, CartesianGrid } from 'recharts';
import { Users, AlertTriangle, Activity, CheckCircle2 } from 'lucide-react';

const telemetryData = [
  { time: '00:00', avgPain: 5.2, critical: 2 },
  { time: '04:00', avgPain: 5.8, critical: 3 },
  { time: '08:00', avgPain: 7.1, critical: 5 },
  { time: '12:00', avgPain: 6.5, critical: 4 },
  { time: '16:00', avgPain: 6.0, critical: 3 },
  { time: '20:00', avgPain: 5.5, critical: 2 },
];

export const Dashboard: React.FC = () => {
  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">ICU Overview</h1>
          <p className="text-xs text-slate-400">Real-time telemetry and pain assessment monitoring</p>
        </div>
        <div className="flex gap-2">
          <span className="px-3 py-1 bg-blue-500/10 text-blue-400 border border-blue-500/20 text-xs rounded-lg font-medium">Ward 4 - ICU West</span>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        {[
          { label: 'Active Patients', value: '24', change: '+2 from shift change', icon: Users, color: 'text-blue-400' },
          { label: 'Critical Alerts', value: '5', change: 'Requires immediate review', icon: AlertTriangle, color: 'text-amber-400' },
          { label: 'Avg AI Variance', value: '±0.4', change: 'High model accuracy', icon: Activity, color: 'text-emerald-400' },
          { label: 'Completed Assessments', value: '142', change: '98% compliance rate', icon: CheckCircle2, color: 'text-indigo-400' },
        ].map((stat, i) => {
          const Icon = stat.icon;
          return (
            <div key={i} className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-3">
              <div className="flex justify-between items-center">
                <span className="text-xs font-medium text-slate-400">{stat.label}</span>
                <Icon className={`w-5 h-5 ${stat.color}`} />
              </div>
              <div className="text-2xl font-bold text-white">{stat.value}</div>
              <div className="text-[10px] text-slate-500">{stat.change}</div>
            </div>
          );
        })}
      </div>

      {/* Main Chart */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
        <h2 className="text-sm font-semibold text-slate-200">Unit Pain Trend & Critical Events (24h)</h2>
        <div className="h-72 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={telemetryData}>
              <defs>
                <linearGradient id="colorPain" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3}/>
                  <stop offset="95%" stopColor="#3b82f6" stopOpacity={0}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="time" stroke="#64748b" fontSize={12} />
              {/* Pain is 0-10, critical events are a count, so they cannot share an axis */}
              <YAxis yAxisId="pain" domain={[0, 10]} stroke="#64748b" fontSize={12} />
              <YAxis yAxisId="count" orientation="right" allowDecimals={false} stroke="#64748b" fontSize={12} />
              <Tooltip contentStyle={{ backgroundColor: '#0f172a', borderColor: '#334155', borderRadius: '8px', color: '#f8fafc' }} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Area yAxisId="pain" type="monotone" dataKey="avgPain" stroke="#3b82f6" strokeWidth={2} fillOpacity={1} fill="url(#colorPain)" name="Avg Pain Index" />
              <Area yAxisId="count" type="monotone" dataKey="critical" stroke="#f59e0b" strokeWidth={2} fillOpacity={0} name="Critical Events" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
};