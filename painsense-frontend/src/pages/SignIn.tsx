import React from 'react';
import { useNavigate } from 'react-router-dom';
import { ShieldCheck } from 'lucide-react';
import { Logo } from '../components/ui/Logo';

export const SignIn: React.FC = () => {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex items-center justify-center p-6">
      <div className="w-full max-w-md bg-slate-900 border border-slate-800 rounded-2xl p-8 shadow-2xl space-y-6">
        <div className="flex items-center">
          <Logo iconClassName="w-10 h-10" />
        </div>

        <form
          className="space-y-4 pt-2"
          onSubmit={(event) => {
            event.preventDefault();
            navigate('/dashboard');
          }}
        >
          <div className="space-y-1.5">
            <label htmlFor="identifier" className="block text-xs font-medium text-slate-300">
              Clinical Identifier / Email
            </label>
            <input
              id="identifier"
              name="identifier"
              type="email"
              autoComplete="username"
              placeholder="dr.ahmed@painsense.icu"
              className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3.5 py-2.5 text-sm focus:outline-none focus:border-blue-500 text-slate-200"
            />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="access-key" className="block text-xs font-medium text-slate-300">
              Secure Access Key / Password
            </label>
            <input
              id="access-key"
              name="password"
              type="password"
              autoComplete="current-password"
              placeholder="Enter your access key"
              className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3.5 py-2.5 text-sm focus:outline-none focus:border-blue-500 text-slate-200"
            />
          </div>

          <button
            type="submit"
            className="w-full bg-blue-600 hover:bg-blue-500 text-white font-semibold py-2.5 rounded-lg text-sm transition shadow-lg shadow-blue-600/20"
          >
            Authenticate Session
          </button>
        </form>

        <div className="pt-4 border-t border-slate-800 flex items-center justify-between text-xs text-slate-500">
          <span className="flex items-center gap-1">
            <ShieldCheck className="w-4 h-4 text-emerald-400" /> HIPAA Compliant
          </span>
          <span>v2.0-secure</span>
        </div>
      </div>
    </div>
  );
};