
import React from 'react';

interface LogoProps {
  /** Extra classes for the lockup. Size the mark with `iconClassName`, not this: the
   *  lockup is icon plus wordmark, so constraining it clips the text. */
  className?: string;
  iconClassName?: string;
  variant?: 'dark' | 'light';
}

export const Logo: React.FC<LogoProps> = ({
  className = '',
  iconClassName = 'w-9 h-9',
  variant = 'dark',
}) => {
  const textColor = variant === 'light' ? 'text-white' : 'text-slate-200';

  return (
    <div className={`flex items-center gap-3 ${className}`}>
      {/* Custom Vector Icon matching your design */}
      <svg viewBox="0 0 100 100" className={`${iconClassName} shrink-0`} fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="PainSense">
        {/* Head / Sensor Arc */}
        <path 
          d="M30 65C30 45 40 35 50 35C60 35 70 45 70 65" 
          stroke="#3b82f6" 
          strokeWidth="8" 
          strokeLinecap="round" 
        />
        {/* Head Dot / Sensor Node */}
        <circle cx="50" cy="22" r="8" fill="#1e293b" stroke="#3b82f6" strokeWidth="6" />
        <circle cx="50" cy="22" r="3" fill="#8b5cf6" />
        {/* Heartbeat Pulse Line */}
        <path 
          d="M20 68H38L44 55L52 78L60 62L66 68H80" 
          stroke="#2dd4bf" 
          strokeWidth="6" 
          strokeLinecap="round" 
          strokeLinejoin="round" 
        />
      </svg>
      
      <div>
        <span className={`font-extrabold text-lg tracking-tight ${textColor}`}>Pain<span className="text-blue-500">Sense</span></span>
        <span className="block text-[9px] text-slate-400 uppercase tracking-widest font-semibold">ICU Intelligence</span>
      </div>
    </div>
  );
};