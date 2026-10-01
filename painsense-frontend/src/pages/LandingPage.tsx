import React from 'react';
import { useNavigate } from 'react-router-dom';
import { 
  BrainCircuit, 
  ShieldCheck, 
  Activity, 
  ArrowRight, 
  CheckCircle2, 
  BarChart3, 
  Sparkles,
  Zap,
  Lock
} from 'lucide-react';
import { Logo } from '../components/ui/Logo';

export const LandingPage: React.FC = () => {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen w-full bg-[#070b19] text-slate-100 font-sans selection:bg-purple-600 selection:text-white overflow-x-hidden">

      {/* TOP NAVIGATION BAR */}
      <header className="sticky top-0 z-50 bg-[#070b19]/85 backdrop-blur-xl border-b border-slate-800/50 w-full">
        <div className="max-w-7xl mx-auto px-6 h-20 flex items-center justify-between">
          <Logo />
          
          <nav className="hidden md:flex items-center gap-8 text-sm font-medium text-slate-300">
            <a href="#features" className="hover:text-purple-400 transition">Features</a>
            <a href="#telemetry" className="hover:text-purple-400 transition">Telemetry</a>
            <a href="#security" className="hover:text-purple-400 transition">Security</a>
          </nav>

          <div className="flex items-center gap-4">
            <button 
              onClick={() => navigate('/login')}
              className="text-sm font-medium text-slate-300 hover:text-white px-4 py-2 transition"
            >
              Sign In
            </button>
            <button 
              onClick={() => navigate('/dashboard')}
              className="bg-gradient-to-r from-purple-600 to-blue-600 hover:from-purple-500 hover:to-blue-500 text-white font-semibold px-5 py-2.5 rounded-xl text-sm transition shadow-lg shadow-purple-600/25 flex items-center gap-2"
            >
              <Zap className="w-4 h-4 fill-white" /> Launch App
            </button>
          </div>
        </div>
      </header>

      {/* HERO SECTION WITH EXCLUSIVE BACKGROUND IMAGE & LIGHTS-OFF DIMMING */}
      <section className="relative pt-28 pb-36 w-full flex flex-col items-center justify-center text-center min-h-[80vh] overflow-hidden">
        
        {/* Scoped Background Image & Dark Vignette Overlay */}
        <div className="absolute inset-0 z-0 pointer-events-none">
          <div 
            className="absolute inset-0 bg-cover bg-center bg-no-repeat filter brightness-90 scale-105"
            style={{ backgroundImage: `url('/hero-touch.jpg')` }}
          />
          {/* Lights-off gradient overlay so typography pops cleanly */}
          <div className="absolute inset-0 bg-gradient-to-b from-[#070b19]/90 via-black/60 to-[#070b19]" />
        </div>

        {/* Hero Content */}
        <div className="max-w-4xl mx-auto px-6 space-y-8 relative z-10">
          
          <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-purple-500/10 border border-purple-500/20 text-purple-400 text-xs font-semibold tracking-wider uppercase backdrop-blur-md mx-auto shadow-lg">
            <Sparkles className="w-3.5 h-3.5 animate-spin" /> MachinaFusion Intelligence
          </div>

          <h1 className="text-4xl md:text-7xl font-extrabold tracking-tight leading-[1.1] drop-shadow-md">
            Human Intuition Meets <br />
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-purple-400 via-blue-400 to-indigo-300">
              Intelligence That Feels
            </span>
          </h1>

          <p className="text-base md:text-xl text-slate-300 font-normal max-w-2xl mx-auto leading-relaxed drop-shadow">
            Bridging the gap between humanity and robotics for a smarter, more connected intensive care future.
          </p>

          <div className="flex flex-col sm:flex-row items-center justify-center gap-4 pt-4">
            <button 
              onClick={() => navigate('/dashboard')}
              className="w-full sm:w-auto bg-purple-600 hover:bg-purple-500 text-white font-semibold px-8 py-4 rounded-xl text-base transition shadow-xl shadow-purple-600/30 flex items-center justify-center gap-3 group"
            >
              Explore Live Dashboard
              <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
            </button>
            <button
              onClick={() => navigate('/login')}
              className="w-full sm:w-auto bg-slate-900/60 hover:bg-slate-800 text-slate-200 border border-slate-800 font-semibold px-8 py-4 rounded-xl text-base transition backdrop-blur"
            >
              Sign In
            </button>
          </div>

        </div>
      </section>

      {/* TRUST METRICS & COMPLIANCE */}
      <section id="security" className="border-y border-slate-800/40 bg-slate-900/20 py-8 backdrop-blur w-full relative z-10 scroll-mt-20">
        <div className="max-w-7xl mx-auto px-6 grid grid-cols-2 md:grid-cols-4 gap-6 text-center">
          <div className="flex items-center justify-center gap-2 text-slate-300 text-sm font-medium">
            <span className="text-emerald-400"><ShieldCheck className="w-5 h-5" /></span> HIPAA Compliant Vaults
          </div>
          <div className="flex items-center justify-center gap-2 text-slate-300 text-sm font-medium">
            <span className="text-purple-400"><Activity className="w-5 h-5" /></span> Live WebSocket Sync
          </div>
          <div className="flex items-center justify-center gap-2 text-slate-300 text-sm font-medium">
            <span className="text-indigo-400"><Lock className="w-5 h-5" /></span> Role-Based Access Control
          </div>
          <div className="flex items-center justify-center gap-2 text-slate-300 text-sm font-medium">
            <span className="text-teal-400"><CheckCircle2 className="w-5 h-5" /></span> ±0.4 AI Accuracy Variance
          </div>
        </div>
      </section>

      {/* CORE FEATURES SECTION */}
      <section id="features" className="py-24 max-w-7xl mx-auto px-6 space-y-16 w-full relative z-10 scroll-mt-20">
        <div className="text-center space-y-4 max-w-3xl mx-auto">
          <h2 className="text-3xl md:text-5xl font-extrabold tracking-tight">Services That We Provide</h2>
          <p className="text-slate-400 text-base">Custom software solutions crafted to drive growth and clinical precision for intensive care platforms.</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
          <div id="telemetry" className="bg-slate-900/40 border border-slate-800/60 rounded-2xl p-8 space-y-4 hover:border-purple-500/40 transition group backdrop-blur-md scroll-mt-28">
            <div className="w-12 h-12 rounded-xl bg-purple-600/10 border border-purple-500/20 text-purple-400 flex items-center justify-center group-hover:scale-110 transition">
              <BrainCircuit className="w-6 h-6" />
            </div>
            <h3 className="text-xl font-semibold text-white">Objective AI Telemetry</h3>
            <p className="text-slate-400 text-sm leading-relaxed">
              Continuously correlates facial muscle tension, respiration rhythm, and heart-rate variability against patient numerical rating scales.
            </p>
          </div>

          <div className="bg-slate-900/40 border border-slate-800/60 rounded-2xl p-8 space-y-4 hover:border-blue-500/40 transition group backdrop-blur-md">
            <div className="w-12 h-12 rounded-xl bg-blue-600/10 border border-blue-500/20 text-blue-400 flex items-center justify-center group-hover:scale-110 transition">
              <Activity className="w-6 h-6" />
            </div>
            <h3 className="text-xl font-semibold text-white">Bedside & Desk Ready</h3>
            <p className="text-slate-400 text-sm leading-relaxed">
              Optimized for high-touch tablet interfaces at patient bedsides while offering deep desktop analytics and model versioning for intensive care desks.
            </p>
          </div>

          <div className="bg-slate-900/40 border border-slate-800/60 rounded-2xl p-8 space-y-4 hover:border-indigo-500/40 transition group backdrop-blur-md">
            <div className="w-12 h-12 rounded-xl bg-indigo-600/10 border border-indigo-500/20 text-indigo-400 flex items-center justify-center group-hover:scale-110 transition">
              <BarChart3 className="w-6 h-6" />
            </div>
            <h3 className="text-xl font-semibold text-white">Immutable Audit Logs</h3>
            <p className="text-slate-400 text-sm leading-relaxed">
              Complete tracking of every clinician review, override, medication administration, and security access event backed by PostgreSQL.
            </p>
          </div>
        </div>
      </section>

      {/* CALL TO ACTION & FOOTER */}
      <footer className="border-t border-slate-800/40 bg-[#040711] py-16 w-full relative z-10">
        <div className="max-w-7xl mx-auto px-6 space-y-12">
          <div className="bg-gradient-to-r from-purple-950/40 via-slate-900/60 to-blue-950/40 border border-slate-800/60 rounded-3xl p-10 md:p-16 text-center space-y-6 backdrop-blur">
            <h2 className="text-3xl md:text-4xl font-bold tracking-tight text-white">Ready to start your next project with us?</h2>
            <p className="text-slate-400 max-w-xl mx-auto text-sm">
              Deploy PainSense across your hospital wards today with complete HIPAA security compliance and real-time telemetry integration.
            </p>
            <div className="pt-2">
              <button 
                onClick={() => navigate('/dashboard')}
                className="bg-gradient-to-r from-purple-600 to-blue-600 hover:from-purple-500 hover:to-blue-500 text-white font-semibold px-8 py-4 rounded-xl text-sm transition shadow-lg shadow-purple-600/30"
              >
                Access Secure Workspace Now
              </button>
            </div>
          </div>

          <div className="flex flex-col md:flex-row items-center justify-between gap-6 pt-8 border-t border-slate-900/80 text-xs text-slate-500">
            <Logo />
            <div>© 2026 PainSense Inc. All rights reserved. Intensive Care Intelligence Platform.</div>
            <div className="flex gap-6">
              <a href="#privacy" className="hover:text-slate-400 transition">Privacy Policy</a>
              <a href="#terms" className="hover:text-slate-400 transition">Terms of Service</a>
              <a href="#security" className="hover:text-slate-400 transition">HIPAA Compliance</a>
            </div>
          </div>
        </div>
      </footer>

    </div>
  );
};