import React from 'react';
import { Outlet, Link, useLocation, useNavigate } from 'react-router-dom';
import { 
  LayoutDashboard, 
  Users, 
  ClipboardPlus, 
  BrainCircuit, 
  BarChart3, 
  FileText, 
  ShieldCheck, 
  Settings as SettingsIcon,
  LogOut,
  Activity,
  History,
  Database
} from 'lucide-react';
import { Logo } from '../ui/Logo'; // <-- Import the new logo component

export const AppLayout: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();

  const navItems = [
    { label: 'Dashboard', path: '/dashboard', icon: LayoutDashboard },
    { label: 'Patients', path: '/patients', icon: Users },
    { label: 'Assessments', path: '/assessments', icon: ClipboardPlus },
    { label: 'AI Analysis', path: '/ai-analysis', icon: BrainCircuit },
    { label: 'Analytics', path: '/analytics', icon: BarChart3 },
    { label: 'AI Models', path: '/ai-models', icon: Activity },
    { label: 'Dataset', path: '/dataset', icon: Database },
    { label: 'Documents', path: '/documents', icon: FileText },
    { label: 'Reports', path: '/reports', icon: FileText },
    { label: 'Security', path: '/security', icon: ShieldCheck },
    { label: 'Audit Log', path: '/audit', icon: History },
    { label: 'Settings', path: '/settings', icon: SettingsIcon },
  ];

  return (
    <div className="flex h-screen bg-slate-950 text-slate-100 overflow-hidden font-sans">
      {/* Sidebar */}
      <aside className="w-64 border-r border-slate-800 bg-slate-900 flex flex-col select-none">
        <div className="p-5 border-b border-slate-800">
          <Logo /> {/* <-- Replaced old box icon with custom logo */}
        </div>

        <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
          <div className="px-3 py-2 text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Clinical Workspace</div>
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = location.pathname === item.path;
            return (
              <Link
                key={item.path}
                to={item.path}
                className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                  isActive 
                    ? 'bg-blue-600/10 text-blue-400 border border-blue-500/20' 
                    : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'
                }`}
              >
                <Icon className={`w-4 h-4 ${isActive ? 'text-blue-400' : 'text-slate-500'}`} />
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="p-3 border-t border-slate-800">
          <button 
            onClick={() => navigate('/login')}
            className="flex items-center gap-3 w-full px-3 py-2 rounded-lg text-sm font-medium text-red-400 hover:bg-red-500/10 transition-colors"
          >
            <LogOut className="w-4 h-4" />
            Sign Out
          </button>
        </div>
      </aside>

      {/* Main Content Body */}
      <main className="flex-1 flex flex-col min-w-0 overflow-hidden bg-slate-950">
        <header className="h-14 border-b border-slate-800 bg-slate-900/50 backdrop-blur flex items-center justify-between px-6 z-10">
          <div className="flex items-center gap-4 text-xs font-medium text-slate-400">
            <span className="flex items-center gap-1.5 text-emerald-400 bg-emerald-500/10 px-2.5 py-1 rounded-full border border-emerald-500/20">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              Secure WS Active
            </span>
            <span className="hidden md:inline">ICU Bedside Unit #4B Connected</span>
          </div>
          <div className="flex items-center gap-3">
            <div className="text-right">
              <div className="text-xs font-semibold text-slate-200">Dr. Ahmed</div>
              <div className="text-[10px] text-slate-400">Senior Intensivist</div>
            </div>
            <div className="w-8 h-8 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center font-bold text-xs text-blue-400">
              DA
            </div>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto p-6">
          <Outlet />
        </div>
      </main>
    </div>
  );
};