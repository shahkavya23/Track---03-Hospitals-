// Purpose: Horizontal stepper and workflow navigation bar indicating active, completed, and pending stages.
import React from 'react';
import { Layers, Activity, SplitSquareVertical, Network, HeartPulse, AlertOctagon, FileCheck } from 'lucide-react';

const STEPS = [
  { id: 'files', step: 1, label: 'Ingest & Presets', icon: Layers },
  { id: 'pipeline', step: 2, label: 'Firewall Pipeline', icon: Activity },
  { id: 'diff', step: 3, label: 'Side-by-Side Diff', icon: SplitSquareVertical },
  { id: 'linkage', step: 4, label: 'Cross-Record Linkage', icon: Network },
  { id: 'clinical', step: 5, label: 'Clinical Preservation', icon: HeartPulse },
  { id: 'quarantine', step: 6, label: 'Quarantine Defense', icon: AlertOctagon },
  { id: 'report', step: 7, label: 'Official Audit Report', icon: FileCheck },
];

export default function Navigation({ activeTab, onSelectTab, filesCount, hasOutput }) {
  return (
    <nav className="raksha-nav border-b border-[#1E293B] bg-[#0E1726]/80 backdrop-blur-sm sticky top-[65px] z-40">
      <div className="max-w-7xl mx-auto flex items-center gap-1.5 px-6 overflow-x-auto scrollbar-none py-1.5">
        {STEPS.map((s) => {
          const Icon = s.icon;
          const isActive = activeTab === s.id;

          // Determine step status
          let isCompleted = false;
          if (s.id === 'files' && filesCount > 0) isCompleted = true;
          if (['pipeline', 'diff', 'linkage', 'clinical', 'quarantine', 'report'].includes(s.id) && hasOutput) {
            isCompleted = true;
          }

          return (
            <button
              key={s.id}
              onClick={() => onSelectTab(s.id)}
              className={`raksha-step flex items-center gap-2.5 px-3.5 py-2 rounded-lg text-xs font-semibold transition-all whitespace-nowrap border ${isActive ? 'is-active' : ''} ${
                isActive
                  ? 'bg-teal-500/15 text-teal-300 border-teal-500/40 shadow-sm shadow-teal-500/10'
                  : isCompleted
                  ? 'bg-[#111C2E]/60 text-slate-300 border-[#1E293B] hover:border-slate-600 hover:text-white'
                  : 'bg-transparent text-slate-500 border-transparent hover:text-slate-300 hover:bg-[#111C2E]/40'
              }`}
            >
              <div
                className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-mono font-bold ${
                  isActive
                    ? 'bg-teal-500 text-slate-950 font-black'
                    : isCompleted
                    ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                    : 'bg-slate-800 text-slate-500'
                }`}
              >
                {s.step}
              </div>
              <Icon className={`w-3.5 h-3.5 ${isActive ? 'text-teal-400' : isCompleted ? 'text-emerald-400' : 'text-slate-500'}`} />
              <span>{s.label}</span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}
