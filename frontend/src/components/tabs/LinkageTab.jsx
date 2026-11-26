// Purpose: Tab 4 - Cross-hospital patient linkage clusters visualization.
import React from 'react';
import { Network, UserCheck, ShieldCheck, FileText } from 'lucide-react';

export default function LinkageTab({ clusters }) {
  const clusterEntries = Object.entries(clusters);

  return (
    <div className="space-y-6">
      <div className="bg-[#111C2E] border border-[#1E293B] rounded-xl p-6 shadow-sm">
        <div className="flex items-center gap-3 mb-2">
          <div className="w-8 h-8 rounded-lg bg-purple-500/10 border border-purple-500/20 flex items-center justify-center text-purple-400">
            <Network className="w-4 h-4" />
          </div>
          <div>
            <h2 className="text-base font-bold text-white">
              Cross-Hospital Patient Linkage Clusters
            </h2>
            <p className="text-xs text-slate-400">
              Conservative deterministic matching clusters patient records across different wards, hospitals, and languages without false merges.
            </p>
          </div>
        </div>
      </div>

      {clusterEntries.length === 0 ? (
        <div className="text-center py-16 bg-[#111C2E] border border-dashed border-[#1E293B] rounded-xl">
          <div className="w-12 h-12 rounded-full bg-slate-800/60 flex items-center justify-center mx-auto mb-3 text-slate-500">
            <Network className="w-6 h-6" />
          </div>
          <p className="text-xs font-semibold text-slate-300">No Patient Linkage Clusters Formed Yet</p>
          <p className="text-[11px] text-slate-500 mt-1 max-w-sm mx-auto">
            Execute the firewall pipeline with multi-hospital records (such as Scenario A) to inspect linked identities.
          </p>
        </div>
      ) : (
        <div className="grid md:grid-cols-2 gap-4">
          {clusterEntries.map(([psnId, clusterMembers]) => (
            <div
              key={psnId}
              className="bg-[#111C2E] border border-purple-500/30 hover:border-purple-400/50 rounded-xl p-5 shadow-lg transition-all"
            >
              <div className="flex items-center justify-between pb-3.5 border-b border-[#1E293B] mb-3.5">
                <div>
                  <span className="text-[10px] text-purple-400 uppercase font-mono font-bold tracking-wider">
                    Assigned Cluster Pseudonym
                  </span>
                  <h4 className="text-xs font-mono font-bold text-white tracking-wide truncate max-w-xs mt-0.5">
                    {psnId}
                  </h4>
                </div>
                <span className="text-[11px] bg-purple-500/15 text-purple-300 border border-purple-500/30 px-2.5 py-0.5 rounded-full font-mono font-semibold flex items-center gap-1.5">
                  <UserCheck className="w-3.5 h-3.5" />
                  {clusterMembers.length} Linked Record{clusterMembers.length > 1 ? 's' : ''}
                </span>
              </div>

              <div className="space-y-2">
                {clusterMembers.map((m, idx) => (
                  <div
                    key={idx}
                    className="bg-[#0B1120] p-3 rounded-lg border border-[#1E293B] text-xs flex items-center justify-between"
                  >
                    <div className="flex items-center gap-2.5">
                      <span className="w-6 h-6 rounded-full bg-slate-800 text-[10px] text-teal-400 font-mono font-bold flex items-center justify-center border border-slate-700">
                        {idx + 1}
                      </span>
                      <div>
                        <span className="text-slate-200 font-mono text-xs font-semibold block truncate max-w-[220px]" title={m.record_ref}>
                          {m.record_ref}
                        </span>
                        <span className="text-[10px] text-slate-500 font-mono">
                          Source: {m.source_ref}
                        </span>
                      </div>
                    </div>
                    <span className="text-[11px] text-slate-400 font-mono px-2 py-0.5 bg-[#111C2E] rounded border border-[#1E293B]">
                      {m.field_count} fields
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
