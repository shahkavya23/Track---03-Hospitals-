import React from 'react';
import { ShieldCheck } from 'lucide-react';

export default function QuarantineTab({ report }) {
  const quarantinedFiles = report?.files ? report.files.filter((f) => f.status === 'quarantined') : [];
  const quarantinedCount = report?.counts?.files_quarantined ?? quarantinedFiles.length;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-baseline justify-between gap-4">
        <div>
          <h2 className="text-base font-medium text-zinc-100">
            Quarantine register
          </h2>
          <p className="text-xs text-zinc-400 mt-1">
            Files isolated due to path traversal, corrupt encodings, unsupported formats, or residual verification failures
          </p>
        </div>

        <span className={`text-xs font-mono tabular-nums ${quarantinedCount > 0 ? 'text-rose-400' : 'text-zinc-400'}`}>
          {report ? `${quarantinedCount} quarantined` : 'Awaiting run'}
        </span>
      </div>

      <div className="bg-[#17181C] border border-white/[0.08] rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-[#131417] text-zinc-400 border-b border-white/[0.08]">
              <tr>
                <th className="py-3 px-4 font-medium">Input SHA-256</th>
                <th className="py-3 px-4 font-medium">Status</th>
                <th className="py-3 px-4 font-medium">Reason</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.06] font-mono">
              {quarantinedFiles.length > 0 ? (
                quarantinedFiles.map((f, idx) => (
                  <tr key={idx} className="hover:bg-white/[0.02] transition-colors duration-150">
                    <td className="py-4 px-4 text-zinc-400 truncate max-w-xs" title={f.input_sha256}>
                      {f.input_sha256}
                    </td>
                    <td className="py-4 px-4 text-rose-400">{f.status}</td>
                    <td className="py-4 px-4 text-zinc-200">
                      {f.reason || 'Security validation rule triggered'}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={3} className="py-16 text-center text-zinc-500 font-sans">
                    <div className="flex flex-col items-center gap-2">
                      <ShieldCheck className="w-5 h-5 text-zinc-600" strokeWidth={1.5} />
                      <span>No quarantined files recorded. Load Suite 03 to test quarantine defense</span>
                    </div>
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
