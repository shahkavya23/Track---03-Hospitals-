import React from 'react';
import { Network, CheckCircle2, ArrowRight } from 'lucide-react';

const PRESERVED_ENTITIES = [
  {
    category: 'Blood pressure and vitals',
    example: 'BP 165/95 mmHg, SpO2 94%, Pulse 74/min, Temp 98.4 F',
    role: 'CLINICAL_PROTECTED',
  },
  {
    category: 'High-risk medications',
    example: 'Ramipril, Insulin Glargine, Metformin, Dolo 650, Pantoprazole',
    role: 'CLINICAL_PROTECTED',
  },
  {
    category: 'Dosages and regimens',
    example: '5mg OD, 14 units SC at bedtime, 500mg BD, 1-0-1, SOS',
    role: 'CLINICAL_PROTECTED',
  },
  {
    category: 'Diagnostic codes and labs',
    example: 'HbA1c 7.4% (LOINC 4548-4), Severe Hypertension, T2DM',
    role: 'CLINICAL_PROTECTED',
  },
];

export default function LinkageTab({ clusters, onGoSanitize }) {
  const clusterEntries = Object.entries(clusters);

  return (
    <div className="space-y-8">
      {/* Patient Linkage Clusters */}
      <section className="space-y-4">
        <div className="flex flex-wrap items-baseline justify-between gap-4">
          <div>
            <h2 className="text-base font-medium text-zinc-100">
              Patient identity clusters
            </h2>
            <p className="text-xs text-zinc-400 mt-1">
              Records matched deterministically across hospitals without transitive false merges
            </p>
          </div>
          <span className="text-xs font-mono text-zinc-400 tabular-nums">
            {clusterEntries.length} cluster{clusterEntries.length === 1 ? '' : 's'}
          </span>
        </div>

        {clusterEntries.length === 0 ? (
          <div className="bg-[#17181C] border border-dashed border-white/[0.12] rounded-xl py-12 px-6 text-center">
            <Network className="w-5 h-5 text-zinc-500 mx-auto mb-3" strokeWidth={1.5} />
            <p className="text-sm font-medium text-zinc-200">No patient clusters yet</p>
            <p className="text-xs text-zinc-400 mt-1">
              Run the Multilingual linkage scenario or upload multi-hospital files to inspect linked records
            </p>
            {onGoSanitize && (
              <button
                type="button"
                onClick={onGoSanitize}
                className="mt-4 h-8 px-3 rounded-lg bg-[#1E2025] hover:bg-[#262830] border border-white/[0.08] text-xs font-medium text-zinc-200 inline-flex items-center gap-2 cursor-pointer transition-colors duration-150"
              >
                <span>Go to Sanitize</span>
                <ArrowRight className="w-4 h-4 text-zinc-400" strokeWidth={1.5} />
              </button>
            )}
          </div>
        ) : (
          <div className="grid md:grid-cols-2 gap-4">
            {clusterEntries.map(([psnId, members]) => (
              <div
                key={psnId}
                className="bg-[#17181C] border border-white/[0.08] rounded-xl p-5"
              >
                <div className="flex items-center justify-between pb-3 border-b border-white/[0.08] mb-3 gap-3">
                  <span className="text-xs font-mono font-medium text-emerald-400 truncate">
                    {psnId}
                  </span>
                  <span className="text-xs font-mono text-zinc-400 tabular-nums shrink-0">
                    {members.length} record{members.length > 1 ? 's' : ''}
                  </span>
                </div>

                <div className="divide-y divide-white/[0.06]">
                  {members.map((m, idx) => (
                    <div
                      key={idx}
                      className="py-2 flex items-center justify-between gap-3 text-xs"
                    >
                      <div className="flex items-center gap-3 min-w-0">
                        <span className="font-mono text-zinc-500 tabular-nums w-4 shrink-0">
                          {idx + 1}
                        </span>
                        <span className="text-zinc-200 font-mono truncate" title={m.record_ref}>
                          {m.record_ref || 'record'}
                        </span>
                      </div>
                      <span className="font-mono text-zinc-500 truncate max-w-[160px]">
                        {m.source_ref || 'source'}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Clinical Integrity Safeguard */}
      <section className="space-y-4">
        <div className="flex flex-wrap items-baseline justify-between gap-4">
          <div>
            <h2 className="text-base font-medium text-zinc-100">
              Clinical integrity guard
            </h2>
            <p className="text-xs text-zinc-400 mt-1">
              Medical terms override overlapping PII spans so vitals and dosages remain verbatim
            </p>
          </div>
          <span className="text-xs font-mono text-emerald-400 inline-flex items-center gap-1.5">
            <CheckCircle2 className="w-4 h-4" strokeWidth={1.5} />
            <span>100% preserved</span>
          </span>
        </div>

        <div className="bg-[#17181C] border border-white/[0.08] rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-[#131417] text-zinc-400 border-b border-white/[0.08]">
                <tr>
                  <th className="py-3 px-4 font-medium">Category</th>
                  <th className="py-3 px-4 font-medium">Protected examples</th>
                  <th className="py-3 px-4 font-medium text-right">Span role</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.06]">
                {PRESERVED_ENTITIES.map((item) => (
                  <tr key={item.category} className="hover:bg-white/[0.02] transition-colors duration-150">
                    <td className="py-3 px-4 text-zinc-100 font-medium">{item.category}</td>
                    <td className="py-3 px-4 font-mono text-zinc-300">{item.example}</td>
                    <td className="py-3 px-4 font-mono text-emerald-400 text-right">{item.role}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </div>
  );
}
