import React from 'react';
import { ChevronDown } from 'lucide-react';
import type { DocumentState } from '../types';

interface HeaderProps {
  state?: DocumentState;
  progress?: { completed: number; total: number; label: string; percentage: number };
}

export const Header: React.FC<HeaderProps> = ({ state }) => {
  // Derive initials from name if available
  const initials = state?.full_name
    ? state.full_name
        .split(' ')
        .map((w) => w[0])
        .join('')
        .toUpperCase()
        .slice(0, 2)
    : 'W';

  return (
    <header className="w-full bg-white border-b border-slate-100 px-8 py-3.5 flex items-center justify-between sticky top-0 z-30">
      {/* Left side: Brand + Title + Badge */}
      <div className="flex items-center gap-6">
        <div className="text-2xl font-bold font-brand text-[#2d1b69] tracking-tight">
          Wenup
        </div>

        <div>
          <h1 className="text-lg font-serif-title font-semibold text-[#1e1b4b]">
            Document Intake Assistant
          </h1>
        </div>
      </div>

      {/* Right side: User profile */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-1.5 bg-[#f1f0fb] hover:bg-[#e9e6f9] text-[#2d1b69] text-xs font-semibold px-2.5 py-1.5 rounded-full cursor-pointer transition-colors">
          <span className="w-5 h-5 rounded-full bg-[#dcd7f8] flex items-center justify-center text-[10px]">
            {initials}
          </span>
          <ChevronDown className="w-3.5 h-3.5 text-slate-500" />
        </div>
      </div>
    </header>
  );
};
