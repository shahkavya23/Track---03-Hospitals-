// Purpose: Tab 2 - 7-Stage Architectural Firewall Pipeline with live progress and execution runner.
import React from 'react';
import { Activity, Play, CheckCircle2, Clock, ShieldCheck, Cpu } from 'lucide-react';

export default function PipelineTab({ filesCount, metrics, running, onRun }) {
  const STAGES = [
    {
      step: 'Stage 1',
      name: 'Universal Ingestion & Sandbox Isolation',
      desc: 'Enforces 200MB directory limits, detects zip bombs & symlinks, isolates parser memory.',
      badge: 'Sandbox Active',
      status: filesCount > 0 ? 'COMPLETE' : 'PENDING',
    },
    {
      step: 'Stage 2',
      name: 'Encoding Detection & Magic Byte Validation',
      desc: 'Auto-detects UTF-8, Latin-1, UTF-16, validates CSV / TSV / JSON / FHIR R4 schemas, and isolates corrupt encodings.',
      badge: 'Multilingual Decode',
      status: filesCount > 0 ? 'COMPLETE' : 'PENDING',
    },
    {
      step: 'Stage 3',
      name: 'Multilingual PII & Quasi-Identifier Detection',
      desc: 'High-recall detection for English & Devanagari names, ABHA, Aadhaar, PAN, phones, dates, and postal codes.',
      badge: 'Zero LLM Detection',
      status: metrics ? 'COMPLETE' : running ? 'PROCESSING' : 'PENDING',
    },
    {
      step: 'Stage 4',
      name: 'Clinical Integrity Guard Override',
      desc: 'Cross-checks detections against medical vocabularies; strictly preserves vital signs, medications, and dosages.',
      badge: '100% Medical Safety',
      status: metrics ? 'COMPLETE' : running ? 'PROCESSING' : 'PENDING',
    },
    {
      step: 'Stage 5',
      name: 'Conservative Patient Record Linkage',
      desc: 'Blocks and matches records on ABHA and deterministic attributes across hospitals without false merges.',
      badge: 'Deterministic Matching',
      status: metrics ? 'COMPLETE' : running ? 'PROCESSING' : 'PENDING',
    },
    {
      step: 'Stage 6',
      name: 'HMAC-SHA256 Pseudonymization & Date Shifting',
      desc: 'Issues secret-keyed pseudonyms (PSN-...) and shifts patient timelines uniformly to preserve longitudinal validity.',
      badge: 'Keyed Pseudonymization',
      status: metrics ? 'COMPLETE' : running ? 'PROCESSING' : 'PENDING',
    },
    {
      step: 'Stage 7',
      name: 'Safe Output Serialization & Audit Telemetry',
      desc: 'Performs reverse-offset text splicing, emits sanitized records, report.json, and records.jsonl with zero canary leaks.',
      badge: 'Verified Clean Output',
      status: metrics ? 'COMPLETE' : running ? 'PROCESSING' : 'PENDING',
    },
  ];

  return (
    <div className="space-y-6">
      <div className="bg-[#111C2E] border border-[#1E293B] rounded-xl p-6 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-4 mb-6 pb-4 border-b border-[#1E293B]">
          <div>
            <h2 className="text-base font-bold text-white flex items-center gap-2">
              <Activity className="w-5 h-5 text-teal-400" />
              RAKSHA 7-Stage Architectural Pipeline
            </h2>
            <p className="text-xs text-slate-400 mt-1">
              Guarantees zero raw PII leaks across offline processing with CPU-friendly execution and HMAC pseudonymization.
            </p>
          </div>

          <button
            onClick={onRun}
            disabled={running || filesCount === 0}
            className={`px-5 py-2.5 rounded-lg text-xs font-bold transition-all flex items-center gap-2 shadow-lg ${
              running || filesCount === 0
                ? 'bg-slate-800 text-slate-500 cursor-not-allowed border border-slate-700'
                : 'bg-gradient-to-r from-teal-500 to-emerald-500 hover:from-teal-400 hover:to-emerald-400 text-slate-950 shadow-teal-500/20'
            }`}
          >
            <Play className={`w-3.5 h-3.5 ${running ? 'animate-spin' : 'fill-slate-950'}`} />
            {running ? 'Processing Pipeline...' : 'Run Full Firewall Pipeline'}
          </button>
        </div>

        <div className="space-y-3">
          {STAGES.map((st, i) => {
            const isDone = st.status === 'COMPLETE';
            const isRunning = st.status === 'PROCESSING';

            return (
              <div
                key={st.step}
                className={`p-4 rounded-xl border transition-all flex flex-col md:flex-row md:items-center justify-between gap-3 ${
                  isDone
                    ? 'bg-[#0B1120] border-[#1E3A5F]'
                    : isRunning
                    ? 'bg-teal-500/5 border-teal-500/40 shadow-inner'
                    : 'bg-[#0B1120]/60 border-[#1E293B] opacity-75'
                }`}
              >
                <div className="flex items-start gap-3.5">
                  <div
                    className={`w-8 h-8 rounded-lg flex items-center justify-center text-xs font-bold font-mono shrink-0 ${
                      isDone
                        ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                        : isRunning
                        ? 'bg-teal-500 text-slate-950 animate-pulse'
                        : 'bg-slate-800 text-slate-500 border border-slate-700'
                    }`}
                  >
                    0{i + 1}
                  </div>
                  <div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <h4 className="text-xs font-bold text-white">{st.name}</h4>
                      <span className="text-[10px] font-mono px-2 py-0.2 rounded bg-[#111C2E] text-slate-400 border border-[#1E293B]">
                        {st.badge}
                      </span>
                    </div>
                    <p className="text-[11px] text-slate-400 mt-1 leading-relaxed">{st.desc}</p>
                  </div>
                </div>

                <div className="shrink-0 flex items-center justify-end">
                  <span
                    className={`text-[11px] font-mono font-bold px-2.5 py-1 rounded-md uppercase tracking-wider flex items-center gap-1.5 ${
                      isDone
                        ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                        : isRunning
                        ? 'bg-teal-500/20 text-teal-300 border border-teal-500/40 animate-pulse'
                        : 'bg-slate-800/80 text-slate-500 border border-slate-700/60'
                    }`}
                  >
                    {isDone && <CheckCircle2 className="w-3.5 h-3.5" />}
                    {isRunning && <Clock className="w-3.5 h-3.5 animate-spin" />}
                    {st.status}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
