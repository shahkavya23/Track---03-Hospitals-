// Purpose: Tab 3 - Split-screen Side-by-Side Diff comparing raw healthcare records vs RAKSHA sanitized output.
import React from 'react';
import { SplitSquareVertical, CheckCircle2, AlertOctagon, FileText, ShieldCheck } from 'lucide-react';

export default function DiffTab({ files, selectedFile, onSelectFile, diffData }) {
  const isQuarantined = diffData?.status === 'quarantined';

  return (
    <div className="raksha-diff space-y-5">
      {/* Control Bar */}
      <div className="bg-[#111C2E] border border-[#1E293B] rounded-xl p-4 flex flex-wrap items-center justify-between gap-3 shadow-sm">
        <div className="flex items-center gap-3">
          <span className="text-xs font-semibold text-slate-400">Select File to Inspect:</span>
          <select
            value={selectedFile}
            onChange={(e) => onSelectFile(e.target.value)}
            className="bg-[#0B1120] border border-[#1E293B] text-teal-300 text-xs font-mono rounded-lg px-3 py-1.5 focus:outline-none focus:border-teal-500 cursor-pointer"
          >
            {files.map((f) => (
              <option key={f.name} value={f.name}>
                {f.name} ({f.format.toUpperCase()})
              </option>
            ))}
          </select>
        </div>

        {diffData && (
          <div className="flex items-center gap-2">
            <span
              className={`text-[11px] font-mono font-bold px-2.5 py-1 rounded-md uppercase tracking-wider flex items-center gap-1.5 border ${
                isQuarantined
                  ? 'bg-rose-500/15 text-rose-400 border-rose-500/30'
                  : 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
              }`}
            >
              {isQuarantined ? <AlertOctagon className="w-3.5 h-3.5" /> : <CheckCircle2 className="w-3.5 h-3.5" />}
              {isQuarantined ? 'Quarantined (Security Threat)' : 'Sanitized & Verified'}
            </span>
          </div>
        )}
      </div>

      {/* Side-by-Side View */}
      <div className="grid md:grid-cols-2 gap-4">
        {/* Raw Input File Panel */}
        <div className="bg-[#111C2E] border border-[#1E293B] rounded-xl overflow-hidden flex flex-col shadow-sm">
          <div className="bg-[#0B1120] px-4 py-3 border-b border-[#1E293B] flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-rose-400"></span>
              <span className="text-xs font-bold text-slate-200">
                Original Raw Input
              </span>
            </div>
            <span className="text-[10px] font-mono text-rose-400 bg-rose-500/10 px-2 py-0.5 rounded border border-rose-500/20">
              Contains Sensitive PII
            </span>
          </div>

          <div className="p-4 flex-1 bg-[#070B14] overflow-auto max-h-[520px]">
            <pre className="text-xs font-mono text-slate-300 whitespace-pre-wrap leading-relaxed select-text">
              {diffData?.original || '// Select a file to inspect'}
            </pre>
          </div>
        </div>

        {/* Sanitized Protected Output Panel */}
        <div className="bg-[#111C2E] border border-[#1E293B] rounded-xl overflow-hidden flex flex-col shadow-sm">
          <div className="bg-[#0B1120] px-4 py-3 border-b border-[#1E293B] flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-400"></span>
              <span className="text-xs font-bold text-slate-200">
                RAKSHA Sanitized Output
              </span>
            </div>
            <span className="text-[10px] font-mono text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">
              De-Identified & Safe
            </span>
          </div>

          <div className="p-4 flex-1 bg-[#070B14] overflow-auto max-h-[520px]">
            <pre className="text-xs font-mono text-emerald-300/90 whitespace-pre-wrap leading-relaxed select-text">
              {diffData?.sanitized || (
                isQuarantined
                  ? '[QUARANTINED BY RAKSHA FIREWALL]\n\nThis file was quarantined because it violated security rules (malicious path traversal or corrupted encoding). It has been excluded from sanitized output.'
                  : '// Execute firewall pipeline to view sanitized output'
              )}
            </pre>
          </div>
        </div>
      </div>

      {/* Color Legend */}
      <div className="bg-[#111C2E] border border-[#1E293B] rounded-xl p-4 flex flex-wrap items-center justify-center gap-6 text-xs">
        <span className="flex items-center gap-2">
          <span className="w-3 h-3 rounded bg-purple-500/40 border border-purple-400"></span>
          <span className="text-slate-300 font-mono text-[11px]">PSN-XXXX (HMAC Pseudonym)</span>
        </span>
        <span className="flex items-center gap-2">
          <span className="w-3 h-3 rounded bg-blue-500/40 border border-blue-400"></span>
          <span className="text-slate-300 font-mono text-[11px]">Timeline Date-Shifted</span>
        </span>
        <span className="flex items-center gap-2">
          <span className="w-3 h-3 rounded bg-amber-500/40 border border-amber-400"></span>
          <span className="text-slate-300 font-mono text-[11px]">Age / Pincode Generalized</span>
        </span>
        <span className="flex items-center gap-2">
          <span className="w-3 h-3 rounded bg-rose-500/40 border border-rose-400"></span>
          <span className="text-slate-300 font-mono text-[11px]">[REDACTED] Direct Identifiers</span>
        </span>
        <span className="flex items-center gap-2">
          <span className="w-3 h-3 rounded bg-emerald-500/40 border border-emerald-400"></span>
          <span className="text-slate-300 font-mono text-[11px]">Clinical Data 100% Preserved</span>
        </span>
      </div>
    </div>
  );
}
