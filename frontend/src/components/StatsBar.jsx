import React from 'react';

export default function StatsBar({ filesCount, metrics, report, clustersCount }) {
  const counts = report?.counts || {};
  const sanitizedCount = metrics?.files_sanitized ?? counts.files_sanitized ?? 0;
  const quarantinedCount = metrics?.files_quarantined ?? counts.files_quarantined ?? 0;
  const detectedCount = metrics?.identifiers_detected ?? counts.identifiers_detected ?? 0;
  const seconds = metrics?.seconds ?? report?.timing?.seconds;
  const peakRss = metrics?.peak_rss_mb ?? report?.resources?.peak_rss_mb;

  const runtimeDisplay = seconds !== undefined ? `${Number(seconds).toFixed(2)}s` : '0.00s';
  const rssDisplay = peakRss !== undefined ? `${peakRss} MB` : '0 MB';

  const stats = [
    { label: 'Staged files', value: filesCount, meta: 'In queue', tone: 'text-zinc-100' },
    { label: 'Sanitized', value: sanitizedCount, meta: 'Verified output', tone: sanitizedCount > 0 ? 'text-emerald-400' : 'text-zinc-100' },
    { label: 'Quarantined', value: quarantinedCount, meta: 'Isolated', tone: quarantinedCount > 0 ? 'text-rose-400' : 'text-zinc-400' },
    { label: 'Identifiers', value: detectedCount, meta: 'Direct and quasi', tone: 'text-zinc-100' },
    { label: 'Linked clusters', value: clustersCount, meta: 'Patient IDs', tone: 'text-zinc-100' },
    { label: 'Runtime', value: runtimeDisplay, meta: `Peak ${rssDisplay}`, tone: 'text-zinc-100' },
  ];

  return (
    <section className="border-b border-white/[0.08] bg-[#111214]">
      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 divide-y sm:divide-y-0 sm:divide-x divide-white/[0.08]">
        {stats.map((stat) => (
          <div key={stat.label} className="px-6 py-4 flex flex-col justify-between gap-2">
            <span className="text-xs text-zinc-500">{stat.label}</span>
            <div className="flex items-baseline justify-between gap-2">
              <span className={`text-xl font-semibold tracking-tight tabular-nums ${stat.tone}`}>
                {stat.value}
              </span>
              <span className="text-xs font-mono text-zinc-500 truncate">{stat.meta}</span>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
