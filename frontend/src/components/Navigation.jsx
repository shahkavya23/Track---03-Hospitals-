import React from 'react';
import {
  Shield,
  Layers,
  Activity,
  SplitSquareVertical,
  Network,
  HeartPulse,
  AlertOctagon,
  FileCheck,
} from 'lucide-react';

const NAV_GROUPS = [
  {
    title: 'Ingest and run',
    items: [
      { id: 'files', label: 'Ingest and presets', icon: Layers },
      { id: 'pipeline', label: 'Firewall pipeline', icon: Activity },
    ],
  },
  {
    title: 'Inspect and verify',
    items: [
      { id: 'diff', label: 'Diff inspector', icon: SplitSquareVertical },
      { id: 'linkage', label: 'Patient linkage', icon: Network },
      { id: 'clinical', label: 'Clinical safety', icon: HeartPulse },
    ],
  },
  {
    title: 'Audit and defense',
    items: [
      { id: 'quarantine', label: 'Quarantine log', icon: AlertOctagon },
      { id: 'report', label: 'Audit report', icon: FileCheck },
    ],
  },
];

export default function Navigation({
  activeTab,
  onSelectTab,
  filesCount,
  hasOutput,
  quarantinedCount = 0,
  clustersCount = 0,
  mobileMenuOpen,
  onCloseMobileMenu,
}) {
  const getCount = (id) => {
    if (id === 'files' && filesCount > 0) return { text: String(filesCount), tone: 'text-zinc-400' };
    if (id === 'quarantine' && quarantinedCount > 0) return { text: String(quarantinedCount), tone: 'text-rose-400' };
    if (id === 'linkage' && clustersCount > 0) return { text: String(clustersCount), tone: 'text-emerald-400' };
    return null;
  };

  const sidebarContent = (
    <div className="flex flex-col h-full bg-[#131417] border-r border-white/[0.08] w-60 select-none">
      {/* Brand */}
      <div className="px-4 h-14 border-b border-white/[0.08] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Shield className="w-4 h-4 text-zinc-100 shrink-0" strokeWidth={1.5} />
          <span className="font-medium text-sm text-zinc-100">RAKSHA</span>
        </div>
        <span className="text-xs font-mono text-zinc-500">v1.0</span>
      </div>

      {/* Navigation Groups */}
      <div className="flex-1 overflow-y-auto px-3 py-4">
        {NAV_GROUPS.map((group, groupIdx) => (
          <div key={group.title} className={groupIdx === 0 ? '' : 'mt-6'}>
            <div className="px-2 mb-2 text-xs font-medium text-zinc-500">
              {group.title}
            </div>
            <div className="space-y-1">
              {group.items.map((item) => {
                const Icon = item.icon;
                const isActive = activeTab === item.id;
                const isDone =
                  (item.id === 'files' && filesCount > 0) ||
                  (item.id !== 'files' && hasOutput);
                const count = getCount(item.id);

                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => {
                      onSelectTab(item.id);
                      onCloseMobileMenu?.();
                    }}
                    className={`w-full h-8 flex items-center justify-between px-2 rounded-lg text-xs font-medium transition-colors duration-150 cursor-pointer focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-emerald-500 ${
                      isActive
                        ? 'bg-[#1E2025] text-zinc-100 border border-white/[0.1]'
                        : 'text-zinc-400 hover:text-zinc-100 hover:bg-white/[0.04] border border-transparent'
                    }`}
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <Icon
                        className={`w-4 h-4 shrink-0 ${
                          isActive ? 'text-zinc-100' : 'text-zinc-500'
                        }`}
                        strokeWidth={1.5}
                      />
                      <span className="truncate">{item.label}</span>
                    </div>

                    {count ? (
                      <span className={`text-xs font-mono tabular-nums ${count.tone}`}>
                        {count.text}
                      </span>
                    ) : isDone && !isActive ? (
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-500/70" />
                    ) : null}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {/* Footer Posture */}
      <div className="p-4 border-t border-white/[0.08] text-xs text-zinc-500 space-y-1">
        <div className="flex items-center justify-between font-mono">
          <span>Mode</span>
          <span className="text-zinc-300">CPU-only · Offline</span>
        </div>
        <div className="flex items-center justify-between font-mono">
          <span>Track</span>
          <span className="text-zinc-300">Secret Wards</span>
        </div>
      </div>
    </div>
  );

  return (
    <>
      <aside className="hidden lg:block shrink-0 sticky top-0 h-screen">
        {sidebarContent}
      </aside>

      {mobileMenuOpen && (
        <div className="fixed inset-0 z-50 lg:hidden flex">
          <div
            className="fixed inset-0 bg-black/60"
            onClick={onCloseMobileMenu}
          />
          <div className="relative z-10 h-full">{sidebarContent}</div>
        </div>
      )}
    </>
  );
}
