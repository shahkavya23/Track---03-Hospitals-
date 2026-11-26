import React from 'react';
import { Shield, RotateCcw, Download, Play } from 'lucide-react';

const TABS = [
  { id: 'sanitize', label: 'Sanitize' },
  { id: 'linkage', label: 'Linkage & safety' },
  { id: 'audit', label: 'Audit & quarantine' },
];

export default function Header({
  activeTab,
  onSelectTab,
  status,
  hasOutput,
  filesCount,
  quarantinedCount,
  clustersCount,
  running,
  onRun,
  onReset,
}) {
  const secretDisplay = status?.secret_hint || 'Active';

  return (
    <header className="sticky top-0 z-30 border-b border-white/[0.08] bg-[#111214]/95 backdrop-blur-sm">
      <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between gap-4">
        {/* Brand */}
        <div className="flex items-center gap-3 shrink-0">
          <div className="w-8 h-8 rounded-lg bg-[#17181C] border border-white/[0.1] flex items-center justify-center">
            <Shield className="w-4 h-4 text-emerald-400" strokeWidth={1.5} />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="font-medium text-sm text-zinc-100">RAKSHA</span>
            <span className="hidden sm:inline text-xs font-mono text-zinc-500">
              Offline · {secretDisplay}
            </span>
          </div>
        </div>

        {/* 3 Clean Segmented Tabs */}
        <nav className="flex items-center gap-1 p-1 rounded-lg bg-[#17181C] border border-white/[0.08]">
          {TABS.map((tab) => {
            const isActive = activeTab === tab.id;
            const badge =
              tab.id === 'linkage' && clustersCount > 0
                ? clustersCount
                : tab.id === 'audit' && quarantinedCount > 0
                ? quarantinedCount
                : null;

            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => onSelectTab(tab.id)}
                className={`h-8 px-3 rounded-md text-xs font-medium transition-colors duration-150 inline-flex items-center gap-2 cursor-pointer focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-emerald-500 ${
                  isActive
                    ? 'bg-[#262830] text-zinc-100'
                    : 'text-zinc-400 hover:text-zinc-200'
                }`}
              >
                <span>{tab.label}</span>
                {badge !== null && (
                  <span
                    className={`text-xs font-mono tabular-nums ${
                      tab.id === 'audit' && quarantinedCount > 0
                        ? 'text-rose-400'
                        : 'text-emerald-400'
                    }`}
                  >
                    {badge}
                  </span>
                )}
              </button>
            );
          })}
        </nav>

        {/* Primary Actions */}
        <div className="flex items-center gap-2 shrink-0">
          {hasOutput && (
            <a
              href="/api/download-zip"
              download="raksha_sanitized_package.zip"
              className="hidden md:inline-flex items-center gap-2 h-8 px-3 rounded-lg border border-white/[0.1] bg-[#17181C] hover:bg-[#1E2025] text-xs font-medium text-zinc-200 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-emerald-500"
            >
              <Download className="w-4 h-4 text-zinc-400" strokeWidth={1.5} />
              <span>Export ZIP</span>
            </a>
          )}

          <button
            type="button"
            onClick={() => onRun()}
            disabled={running || filesCount === 0}
            className="inline-flex items-center gap-2 h-8 px-3 rounded-lg text-xs font-medium transition-colors duration-150 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed bg-[#F4F4F5] text-[#111214] hover:bg-white focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-emerald-500"
          >
            <Play className="w-4 h-4" strokeWidth={1.5} />
            <span>{running ? 'Running' : 'Run firewall'}</span>
          </button>

          <button
            type="button"
            onClick={onReset}
            title="Clear workspace"
            className="inline-flex items-center justify-center w-8 h-8 rounded-lg border border-white/[0.08] bg-[#17181C] hover:bg-[#1E2025] text-zinc-400 hover:text-zinc-100 transition-colors duration-150 cursor-pointer focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-emerald-500"
          >
            <RotateCcw className="w-4 h-4" strokeWidth={1.5} />
          </button>
        </div>
      </div>
    </header>
  );
}
