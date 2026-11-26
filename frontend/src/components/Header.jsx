// Purpose: Executive-grade top navigation header with product branding, security status, and workspace controls.
import React from 'react';
import { Shield, Cpu, Key, RotateCcw, Lock, Radio } from 'lucide-react';

export default function Header({ status, onReset }) {
  const secretDisplay = status?.secret_hint || 'ACTIVE';

  return (
    <header className="raksha-header border-b border-[#1E293B] bg-[#0B1120]/95 backdrop-blur-md px-6 py-3.5 sticky top-0 z-50">
      <div className="max-w-7xl mx-auto flex flex-wrap items-center justify-between gap-4">
        {/* Left: Branding & Subtitle */}
        <div className="flex items-center gap-3.5">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-teal-500 to-cyan-600 flex items-center justify-center shadow-lg shadow-teal-500/20 border border-teal-400/30">
            <Shield className="w-5 h-5 text-white stroke-[2.2]" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-lg font-bold tracking-tight text-white font-sans">
                RAKSHA
              </span>
              <span className="text-[11px] font-semibold px-2 py-0.5 rounded-md bg-teal-500/10 text-teal-400 border border-teal-500/30 font-mono">
                v1.0
              </span>
            </div>
            <p className="text-[12px] text-slate-400 font-medium">
              Multilingual Healthcare Privacy Firewall • DevForge Track 3 ("Secret Wards")
            </p>
          </div>
        </div>

        {/* Center & Right: Security Indicators & Controls */}
        <div className="flex items-center flex-wrap gap-2.5">
          {/* Air-Gapped Indicator */}
          <div className="flex items-center gap-2 px-3 py-1.5 bg-[#111C2E] border border-[#1E293B] rounded-lg text-xs font-medium text-slate-300">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
            </span>
            <span className="text-[11px] uppercase tracking-wider text-emerald-400 font-semibold font-mono">
              Air-Gapped / Offline
            </span>
          </div>

          {/* CPU-Only Engine */}
          <div className="flex items-center gap-1.5 px-3 py-1.5 bg-[#111C2E] border border-[#1E293B] rounded-lg text-xs font-medium text-slate-300">
            <Cpu className="w-3.5 h-3.5 text-cyan-400" />
            <span className="text-[11px] font-mono text-cyan-300">CPU-Only • Zero LLM</span>
          </div>

          {/* Secret Key Status */}
          <div className="flex items-center gap-1.5 px-3 py-1.5 bg-[#111C2E] border border-[#1E293B] rounded-lg text-xs font-medium text-slate-300">
            <Lock className="w-3.5 h-3.5 text-amber-400" />
            <span className="text-[11px] font-mono text-slate-300">HMAC-SHA256:</span>
            <span className="text-[11px] font-mono text-amber-400 font-semibold">{secretDisplay}</span>
          </div>

          {/* Reset Workspace */}
          <button
            onClick={onReset}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-[#111C2E] hover:bg-[#16243C] border border-[#1E293B] hover:border-slate-600 rounded-lg text-xs font-medium text-slate-300 hover:text-white transition-all shadow-sm"
            title="Clear all staged files and reset output"
          >
            <RotateCcw className="w-3.5 h-3.5 text-slate-400" />
            <span>Reset</span>
          </button>
        </div>
      </div>
    </header>
  );
}
