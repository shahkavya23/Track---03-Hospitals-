// Purpose: Tab 6 - Quarantine log displaying rejected hostile files and security reasons.
import React from 'react';
import { AlertOctagon, ShieldAlert, CheckCircle2 } from 'lucide-react';

export default function QuarantineTab({ report }) {
  const quarantinedFiles = report?.files ? report.files.filter((f) => f.status === 'quarantined') : [];

  return (
    <div className="space-y-6">
      <div className="bg-[#111C2E] border border-[#1E293B] rounded-xl p-6 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-rose-500/10 border border-rose-500/20 flex items-center justify-center text-rose-400">
            <AlertOctagon className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-base font-bold text-white">
              Quarantine & Hostile Attack Defense Log
            </h2>
            <p className="text-xs text-slate-400">
              Fail-closed isolation: RAKSHA stops path traversal attacks, corrupted byte encodings, and unauthorized binaries without pipeline crash.
            </p>
          </div>
        </div>
      </div>

      <div className="bg-[#111C2E] border border-[#1E293B] rounded-xl overflow-hidden shadow-sm">
        <div className="px-5 py-3.5 border-b border-[#1E293B] bg-[#0B1120] flex items-center justify-between">
          <h3 className="text-xs font-bold text-slate-300 uppercase tracking-wider font-mono">
            Isolated Threat Register
          </h3>
          <span className="text-xs text-rose-400 font-mono font-bold bg-rose-500/10 border border-rose-500/20 px-2.5 py-0.5 rounded-full">
            {report ? `${report.files_quarantined || 0} Files Quarantined` : 'Awaiting Run'}
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-[#0B1120]/60 text-slate-400 uppercase font-mono text-[10px] border-b border-[#1E293B]">
              <tr>
                <th className="py-3 px-5">Input SHA-256 Hash</th>
                <th className="py-3 px-5">Quarantine Verdict</th>
                <th className="py-3 px-5">Security Violation Reason</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#1E293B] font-mono text-slate-300">
              {quarantinedFiles.length > 0 ? (
                quarantinedFiles.map((f, idx) => (
                  <tr key={idx} className="hover:bg-[#0B1120]/40 transition-colors">
                    <td className="py-3.5 px-5 text-slate-400 truncate max-w-xs">{f.input_sha256}</td>
                    <td className="py-3.5 px-5">
                      <span className="text-[10px] bg-rose-500/15 text-rose-400 border border-rose-500/30 px-2 py-0.5 rounded font-bold uppercase tracking-wider">
                        {f.status}
                      </span>
                    </td>
                    <td className="py-3.5 px-5 text-rose-300 font-medium">
                      {f.reason || 'Security validation rule triggered'}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={3} className="py-12 text-center text-slate-500">
                    No quarantined files recorded. Load Scenario C (Hostile Attack) to inspect quarantine defense.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
