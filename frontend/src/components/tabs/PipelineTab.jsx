import React from 'react';
import { Play, CheckCircle2, Clock } from 'lucide-react';

export default function PipelineTab({ filesCount, metrics, report, running, onRun }) {
  const hasCompleted = Boolean(metrics || report);

  const STAGES = [
    {
      num: '01',
      name: 'Universal ingestion and sandbox isolation',
      desc: 'Enforces 200 MB directory limits, blocks zip bombs and symlinks, and isolates parser memory.',
      role: 'Sandbox',
      status: filesCount > 0 ? 'Complete' : 'Standby',
    },
    {
      num: '02',
      name: 'Encoding detection and schema validation',
      desc: 'Detects UTF-8, Latin-1, and UTF-16 encodings, validates CSV, TSV, JSON, and FHIR R4 schemas, and isolates corrupt bytes.',
      role: 'Decode',
      status: filesCount > 0 ? 'Complete' : 'Standby',
    },
    {
      num: '03',
      name: 'Multilingual PII and quasi-identifier detection',
      desc: 'Rule and context detection for English and Devanagari names, ABHA, Aadhaar, PAN, phones, dates, and PINs.',
      role: 'Detection',
      status: hasCompleted ? 'Complete' : running ? 'Running' : 'Standby',
    },
    {
      num: '04',
      name: 'Clinical integrity guard override',
      desc: 'Cross-checks spans against medical vocabularies so vital signs, medications, and dosages remain untouched.',
      role: 'Clinical guard',
      status: hasCompleted ? 'Complete' : running ? 'Running' : 'Standby',
    },
    {
      num: '05',
      name: 'Conservative patient record linkage',
      desc: 'Blocks and matches records on ABHA and deterministic attributes across hospitals without transitive false merges.',
      role: 'Linkage',
      status: hasCompleted ? 'Complete' : running ? 'Running' : 'Standby',
    },
    {
      num: '06',
      name: 'HMAC-SHA256 pseudonymization and date shifting',
      desc: 'Issues secret-keyed pseudonyms and shifts patient timelines uniformly to preserve clinical intervals.',
      role: 'Pseudonym',
      status: hasCompleted ? 'Complete' : running ? 'Running' : 'Standby',
    },
    {
      num: '07',
      name: 'Fail-closed publication gate and telemetry',
      desc: 'Applies reverse-offset splicing, verifies zero residual identifiers in memory, and writes report.json.',
      role: 'Publish gate',
      status: hasCompleted ? 'Complete' : running ? 'Running' : 'Standby',
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-base font-medium text-zinc-100">
            Seven-stage firewall ledger
          </h2>
          <p className="text-xs text-zinc-400 mt-1">
            Deterministic, CPU-only execution with fail-closed residual verification
          </p>
        </div>

        <button
          type="button"
          onClick={() => onRun('pipeline')}
          disabled={running || filesCount === 0}
          className="h-9 px-4 rounded-lg text-xs font-medium transition-colors duration-150 inline-flex items-center gap-2 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed bg-[#F4F4F5] hover:bg-white text-[#111214] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-emerald-500"
        >
          <Play className="w-4 h-4" strokeWidth={1.5} />
          <span>{running ? 'Running pipeline' : 'Run full pipeline'}</span>
        </button>
      </div>

      <div className="bg-[#17181C] border border-white/[0.08] rounded-xl divide-y divide-white/[0.08] overflow-hidden">
        {STAGES.map((st) => {
          const isDone = st.status === 'Complete';
          const isRunning = st.status === 'Running';

          return (
            <div
              key={st.num}
              className={`p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4 transition-colors duration-150 ${
                isRunning ? 'bg-emerald-500/[0.04]' : 'hover:bg-white/[0.02]'
              }`}
            >
              <div className="flex items-start gap-4">
                <span
                  className={`text-xs font-mono tabular-nums pt-0.5 w-6 shrink-0 ${
                    isDone ? 'text-emerald-400' : isRunning ? 'text-zinc-100' : 'text-zinc-500'
                  }`}
                >
                  {st.num}
                </span>

                <div>
                  <div className="flex items-center gap-3 flex-wrap">
                    <h3 className="text-sm font-medium text-zinc-100">{st.name}</h3>
                    <span className="text-xs font-mono text-zinc-500">
                      {st.role}
                    </span>
                  </div>
                  <p className="text-xs text-zinc-400 mt-1 leading-relaxed">{st.desc}</p>
                </div>
              </div>

              <div className="shrink-0 flex items-center gap-2 text-xs font-mono">
                {isDone && <CheckCircle2 className="w-4 h-4 text-emerald-400" strokeWidth={1.5} />}
                {isRunning && <Clock className="w-4 h-4 text-zinc-300" strokeWidth={1.5} />}
                <span
                  className={
                    isDone
                      ? 'text-emerald-400'
                      : isRunning
                      ? 'text-zinc-100'
                      : 'text-zinc-500'
                  }
                >
                  {st.status}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
