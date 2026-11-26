// Purpose: KPI metric cards displaying live system statistics with refined visual hierarchy.
import React from 'react';
import { FileText, CheckCircle2, AlertTriangle, ShieldAlert, Network, Clock } from 'lucide-react';

export default function StatsBar({ filesCount, metrics, report, clustersCount }) {
  const sanitizedCount = metrics?.files_sanitized ?? (report ? report.files_sanitized : 0);
  const quarantinedCount = metrics?.files_quarantined ?? (report ? report.files_quarantined : 0);
  const detectedCount = metrics?.identifiers_detected ?? 0;
  const runtimeDisplay = metrics ? `${metrics.seconds}s` : '0.00s';
  const rssDisplay = metrics ? `${metrics.peak_rss_mb} MB` : '0 MB';

  const CARDS = [
    {
      label: 'Input Files',
      value: filesCount,
      sublabel: 'Staged in queue',
      icon: FileText,
      accentColor: 'text-cyan-400',
      iconBg: 'bg-cyan-500/10 border-cyan-500/20 text-cyan-400',
    },
    {
      label: 'Sanitized Files',
      value: sanitizedCount,
      sublabel: 'Output de-identified',
      icon: CheckCircle2,
      accentColor: 'text-emerald-400',
      iconBg: 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400',
    },
    {
      label: 'Quarantined Files',
      value: quarantinedCount,
      sublabel: 'Security threats isolated',
      icon: AlertTriangle,
      accentColor: quarantinedCount > 0 ? 'text-rose-400' : 'text-slate-400',
      iconBg: quarantinedCount > 0 ? 'bg-rose-500/10 border-rose-500/20 text-rose-400' : 'bg-slate-800/40 border-slate-700/40 text-slate-400',
    },
    {
      label: 'PII Detected',
      value: detectedCount,
      sublabel: 'Direct & quasi IDs',
      icon: ShieldAlert,
      accentColor: 'text-amber-400',
      iconBg: 'bg-amber-500/10 border-amber-500/20 text-amber-400',
    },
    {
      label: 'Linked Clusters',
      value: clustersCount,
      sublabel: 'Cross-hospital patients',
      icon: Network,
      accentColor: 'text-purple-400',
      iconBg: 'bg-purple-500/10 border-purple-500/20 text-purple-400',
    },
    {
      label: 'Runtime / RSS',
      value: runtimeDisplay,
      sublabel: `Peak RAM: ${rssDisplay}`,
      icon: Clock,
      accentColor: 'text-teal-400',
      iconBg: 'bg-teal-500/10 border-teal-500/20 text-teal-400',
    },
  ];

  return (
    <div className="raksha-stats bg-[#0B1120] border-b border-[#1E293B] py-4 px-6">
      <div className="max-w-7xl mx-auto grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3.5">
        {CARDS.map((card) => {
          const Icon = card.icon;
          return (
            <div
              key={card.label}
              className="raksha-stat-card bg-[#111C2E] border border-[#1E293B] hover:border-[#1E3A5F] rounded-xl p-3.5 transition-all shadow-sm flex flex-col justify-between"
            >
              <div className="flex items-center justify-between mb-2">
                <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
                  {card.label}
                </span>
                <div className={`w-7 h-7 rounded-lg border flex items-center justify-center ${card.iconBg}`}>
                  <Icon className="w-3.5 h-3.5" />
                </div>
              </div>
              <div>
                <p className={`text-2xl font-bold tracking-tight font-sans ${card.accentColor}`}>
                  {card.value}
                </p>
                <p className="text-[11px] text-slate-500 font-mono mt-0.5 truncate">
                  {card.sublabel}
                </p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
