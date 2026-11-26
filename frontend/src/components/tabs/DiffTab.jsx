import React, { useState } from 'react';
import { CheckCircle2, AlertOctagon, Copy, Check, ArrowRight } from 'lucide-react';

const TOKEN_PATTERN = /(\bPSN-[A-Z0-9]+\b|\bREC-[A-Z0-9]+\b|\[(?:PATIENT|RELATIVE|STAFF|PHONE|AADHAAR|PAN|ABHA|DL|EMAIL|IP|USERNAME|CASE_NO|ID_MARK|ADDRESS|IDENTITY_HINT|DATE|AGE|SCHOOL|OCCUPATION|REDACTED(?:-[A-Z_]+)?)\]|[1-8]\d{2}XXX(?:\s+region)?)/g;

function highlightSanitizedText(text) {
  if (!text) return null;
  const parts = text.split(TOKEN_PATTERN);
  return parts.map((part, idx) => {
    if (!part) return null;
    if (part.startsWith('PSN-') || part.startsWith('REC-')) {
      return (
        <span
          key={idx}
          className="px-1 rounded bg-emerald-500/15 text-emerald-300 border border-emerald-500/25 font-medium"
        >
          {part}
        </span>
      );
    }
    if (part.startsWith('[') && part.endsWith(']')) {
      return (
        <span
          key={idx}
          className="px-1 rounded bg-white/[0.07] text-zinc-100 border border-white/[0.12] font-medium"
        >
          {part}
        </span>
      );
    }
    if (part.includes('XXX')) {
      return (
        <span
          key={idx}
          className="px-1 rounded bg-white/[0.07] text-zinc-200 border border-white/[0.12]"
        >
          {part}
        </span>
      );
    }
    return <React.Fragment key={idx}>{part}</React.Fragment>;
  });
}

export default function DiffTab({
  files,
  selectedFile,
  onSelectFile,
  diffData,
  report,
  onOpenQuarantine,
}) {
  const [copied, setCopied] = useState(false);
  const isQuarantined = diffData?.status === 'quarantined';

  const quarantineReason = React.useMemo(() => {
    if (!isQuarantined) return null;
    const entry = report?.files?.find((f) => f.status === 'quarantined');
    return entry?.reason || 'output verification failed';
  }, [isQuarantined, report]);

  const handleCopySanitized = () => {
    if (!diffData?.sanitized) return;
    navigator.clipboard.writeText(diffData.sanitized);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="space-y-4">
      {/* Control Bar */}
      <div className="bg-[#17181C] border border-white/[0.08] rounded-xl p-4 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3 flex-wrap">
          <label htmlFor="diff-file-select" className="text-xs font-medium text-zinc-400">
            Inspect file
          </label>
          <select
            id="diff-file-select"
            value={selectedFile}
            onChange={(e) => onSelectFile(e.target.value)}
            disabled={files.length === 0}
            className="h-8 bg-[#111214] border border-white/[0.12] text-zinc-100 text-xs font-mono rounded-lg px-3 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-emerald-500 cursor-pointer"
          >
            {files.length === 0 ? (
              <option value="">No files staged</option>
            ) : (
              files.map((f) => (
                <option key={f.name} value={f.name}>
                  {f.name} ({f.format})
                </option>
              ))
            )}
          </select>
        </div>

        <div className="flex items-center gap-3">
          {diffData?.sanitized && (
            <button
              type="button"
              onClick={handleCopySanitized}
              className="h-8 px-3 rounded-lg bg-[#1E2025] hover:bg-[#262830] border border-white/[0.08] text-xs font-medium text-zinc-200 inline-flex items-center gap-2 cursor-pointer transition-colors duration-150 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-emerald-500"
            >
              {copied ? <Check className="w-4 h-4 text-emerald-400" strokeWidth={1.5} /> : <Copy className="w-4 h-4 text-zinc-400" strokeWidth={1.5} />}
              <span>{copied ? 'Copied' : 'Copy output'}</span>
            </button>
          )}

          {diffData && (
            <span
              className={`text-xs font-mono inline-flex items-center gap-2 ${
                isQuarantined ? 'text-rose-400' : 'text-emerald-400'
              }`}
            >
              {isQuarantined ? (
                <AlertOctagon className="w-4 h-4" strokeWidth={1.5} />
              ) : (
                <CheckCircle2 className="w-4 h-4" strokeWidth={1.5} />
              )}
              <span>{isQuarantined ? `Quarantined · ${quarantineReason}` : 'Verified clean'}</span>
            </span>
          )}
        </div>
      </div>

      {/* Side-by-Side Ledger */}
      <div className="grid md:grid-cols-2 gap-4">
        <div className="bg-[#17181C] border border-white/[0.08] rounded-xl overflow-hidden flex flex-col">
          <div className="px-4 h-10 border-b border-white/[0.08] flex items-center justify-between">
            <span className="text-xs font-medium text-zinc-200">Original raw input</span>
            <span className="text-xs font-mono text-zinc-500">Unredacted source</span>
          </div>

          <div className="p-4 flex-1 bg-[#0D0E10] overflow-auto max-h-[560px]">
            <pre className="text-xs font-mono text-zinc-300 whitespace-pre-wrap leading-relaxed select-text">
              {diffData?.original || '// Select a staged file to inspect raw input'}
            </pre>
          </div>
        </div>

        <div className="bg-[#17181C] border border-white/[0.08] rounded-xl overflow-hidden flex flex-col">
          <div className="px-4 h-10 border-b border-white/[0.08] flex items-center justify-between">
            <span className="text-xs font-medium text-zinc-200">RAKSHA protected output</span>
            <span className={`text-xs font-mono ${isQuarantined ? 'text-rose-400' : 'text-emerald-400'}`}>
              {isQuarantined ? 'Blocked by gate' : 'De-identified'}
            </span>
          </div>

          <div className="p-4 flex-1 bg-[#0D0E10] overflow-auto max-h-[560px]">
            {diffData?.sanitized ? (
              <pre className="text-xs font-mono text-zinc-300 whitespace-pre-wrap leading-relaxed select-text">
                {highlightSanitizedText(diffData.sanitized)}
              </pre>
            ) : isQuarantined ? (
              <div className="h-full min-h-[280px] flex flex-col items-center justify-center text-center p-6">
                <AlertOctagon className="w-5 h-5 text-rose-400 mb-3" strokeWidth={1.5} />
                <p className="text-sm font-medium text-zinc-100">
                  File quarantined before publication
                </p>
                <p className="text-xs text-zinc-400 mt-2 max-w-md leading-relaxed">
                  Reason: <span className="text-zinc-200 font-mono">{quarantineReason}</span>.
                  RAKSHA blocked this file from being written to <code className="text-zinc-300">sanitized/</code> because it failed ingestion security checks or residual identifier verification.
                </p>
                {onOpenQuarantine && (
                  <button
                    type="button"
                    onClick={onOpenQuarantine}
                    className="mt-4 h-8 px-3 rounded-lg bg-[#1E2025] hover:bg-[#262830] border border-white/[0.08] text-xs font-medium text-zinc-200 inline-flex items-center gap-2 cursor-pointer transition-colors duration-150 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-emerald-500"
                  >
                    <span>Open quarantine log</span>
                    <ArrowRight className="w-4 h-4 text-zinc-400" strokeWidth={1.5} />
                  </button>
                )}
              </div>
            ) : (
              <pre className="text-xs font-mono text-zinc-500 whitespace-pre-wrap leading-relaxed">
                {'// Execute the firewall pipeline to inspect sanitized output'}
              </pre>
            )}
          </div>
        </div>
      </div>

      {/* Quiet Key */}
      <div className="flex flex-wrap items-center gap-6 px-2 text-xs font-mono text-zinc-500">
        <span className="inline-flex items-center gap-2">
          <span className="px-1 rounded bg-emerald-500/15 text-emerald-300 border border-emerald-500/25">PSN-XXXX</span>
          <span>Keyed pseudonym</span>
        </span>
        <span className="inline-flex items-center gap-2">
          <span className="px-1 rounded bg-white/[0.07] text-zinc-100 border border-white/[0.12]">[REDACTED]</span>
          <span>Direct or quasi-identifier</span>
        </span>
        <span>Clinical vitals and dosages remain verbatim</span>
      </div>
    </div>
  );
}
