import React, { useState, useRef } from 'react';
import {
  UploadCloud,
  Plus,
  X,
  CheckCircle2,
  AlertOctagon,
  Copy,
  Check,
  ArrowRight,
  Play,
} from 'lucide-react';

const SCENARIOS = [
  {
    key: 'multilingual-linkage',
    title: 'Multilingual linkage',
    subtitle: 'Apollo CSV + AIIMS Hindi + FHIR R4',
  },
  {
    key: 'clinical-preservation',
    title: 'Clinical safety guard',
    subtitle: 'ICU vitals, Ramipril, Insulin doses',
  },
  {
    key: 'security-quarantine',
    title: 'Quarantine defense',
    subtitle: 'Path traversal + corrupt binary',
  },
];

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
    if ((part.startsWith('[') && part.endsWith(']')) || part.includes('XXX')) {
      return (
        <span
          key={idx}
          className="px-1 rounded bg-white/[0.08] text-zinc-100 border border-white/[0.12] font-medium"
        >
          {part}
        </span>
      );
    }
    return <React.Fragment key={idx}>{part}</React.Fragment>;
  });
}

export default function IngestTab({
  files,
  metrics,
  report,
  running,
  uploadProgress,
  selectedFile,
  diffData,
  onSelectFile,
  onLoadPreset,
  onFileUpload,
  onDeleteFile,
  onRun,
  onOpenAudit,
}) {
  const [isDragging, setIsDragging] = useState(false);
  const [loadingPreset, setLoadingPreset] = useState(null);
  const [viewMode, setViewMode] = useState('split'); // 'split' | 'sanitized' | 'original'
  const [copied, setCopied] = useState(false);
  const fileInputRef = useRef(null);

  const counts = report?.counts || {};
  const sanitizedCount = metrics?.files_sanitized ?? counts.files_sanitized ?? 0;
  const quarantinedCount = metrics?.files_quarantined ?? counts.files_quarantined ?? 0;
  const detectedCount = metrics?.identifiers_detected ?? counts.identifiers_detected ?? 0;
  const seconds = metrics?.seconds ?? report?.timing?.seconds;
  const hasRun = Boolean(metrics || report);

  const isQuarantined = diffData?.status === 'quarantined';
  const quarantineReason = React.useMemo(() => {
    if (!isQuarantined) return null;
    const entry = report?.files?.find((f) => f.status === 'quarantined');
    return entry?.reason || 'output verification failed';
  }, [isQuarantined, report]);

  const handleDragOver = (e) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      onFileUpload({ target: { files: e.dataTransfer.files } });
    }
  };

  const triggerPreset = async (key) => {
    setLoadingPreset(key);
    try {
      await onLoadPreset(key);
    } finally {
      setLoadingPreset(null);
    }
  };

  const handleCopy = () => {
    if (!diffData?.sanitized) return;
    navigator.clipboard.writeText(diffData.sanitized);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const fileInput = (
    <input
      type="file"
      ref={fileInputRef}
      multiple
      accept=".csv,.tsv,.json,.txt,.fhir.json,text/plain,text/csv,text/tab-separated-values,application/json"
      onChange={onFileUpload}
      className="hidden"
    />
  );

  // Empty State: Clean, focused dropzone + 1-click sample runners
  if (files.length === 0) {
    return (
      <div className="max-w-3xl mx-auto py-8 space-y-8">
        {fileInput}

        <div className="text-center space-y-2">
          <h1 className="text-xl font-medium text-zinc-100">
            De-identify hospital records locally
          </h1>
          <p className="text-sm text-zinc-400">
            Upload English, Hindi, or Hinglish clinical files. Vitals and dosages stay intact; patient identity is replaced with keyed HMAC pseudonyms.
          </p>
        </div>

        <div className="bg-[#17181C] border border-white/[0.08] rounded-xl p-2">
          <div
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => !uploadProgress && fileInputRef.current?.click()}
            className={`min-h-[240px] rounded-lg border border-dashed p-8 flex flex-col items-center justify-center text-center transition-colors duration-150 cursor-pointer ${
              isDragging
                ? 'border-emerald-500 bg-emerald-500/[0.04]'
                : 'border-white/[0.12] bg-[#111214] hover:border-white/25'
            }`}
          >
            <UploadCloud className="w-6 h-6 text-zinc-400 mb-3" strokeWidth={1.5} />
            <p className="text-sm font-medium text-zinc-100">
              {uploadProgress ? 'Processing uploaded files' : 'Drop files here or click to browse'}
            </p>
            <p className="text-xs font-mono text-zinc-500 mt-2">
              CSV · TSV · JSON · FHIR R4 · TXT · Max 200 MB
            </p>

            {uploadProgress && (
              <div className="w-full max-w-sm mt-6" role="status" aria-live="polite">
                <div className="flex items-center justify-between text-xs font-mono mb-2">
                  <span className="text-zinc-300 truncate pr-3">
                    {uploadProgress.processing ? 'Running firewall' : uploadProgress.currentFile}
                  </span>
                  <span className="text-emerald-400 tabular-nums">
                    {uploadProgress.processing ? 'Sanitizing' : `${uploadProgress.completed}/${uploadProgress.total}`}
                  </span>
                </div>
                <div className="h-1 w-full rounded bg-white/[0.08] overflow-hidden">
                  <div
                    className="h-full bg-emerald-500 transition-[width] duration-150"
                    style={{
                      width: `${
                        ((uploadProgress.completed * 100 + uploadProgress.percent) /
                          (uploadProgress.total * 100)) *
                        100
                      }%`,
                    }}
                  />
                </div>
              </div>
            )}
          </div>
        </div>

        {/* 1-click Sample Scenarios */}
        <div className="space-y-3">
          <div className="flex items-center justify-between text-xs text-zinc-500">
            <span>Or run a sample scenario</span>
            <span className="font-mono">Loads and sanitizes in one click</span>
          </div>

          <div className="grid sm:grid-cols-3 gap-3">
            {SCENARIOS.map((sc) => {
              const isLoading = loadingPreset === sc.key;
              return (
                <button
                  key={sc.key}
                  type="button"
                  onClick={() => triggerPreset(sc.key)}
                  disabled={loadingPreset !== null || running}
                  className="text-left p-4 rounded-xl bg-[#17181C] hover:bg-[#1E2025] border border-white/[0.08] hover:border-white/[0.16] transition-colors duration-150 cursor-pointer disabled:opacity-50 group focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-emerald-500"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-medium text-zinc-100">{sc.title}</span>
                    <ArrowRight className="w-4 h-4 text-zinc-500 group-hover:text-zinc-200 transition-colors duration-150 shrink-0" strokeWidth={1.5} />
                  </div>
                  <p className="text-xs text-zinc-500 mt-1 truncate">
                    {isLoading ? 'Running scenario' : sc.subtitle}
                  </p>
                </button>
              );
            })}
          </div>
        </div>
      </div>
    );
  }

  // Active Workspace: File Strip + Live Diff Inspector
  return (
    <div className="space-y-4">
      {fileInput}

      {/* Compact File Strip & Run Summary */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-2 flex-wrap">
          {files.map((file) => {
            const isSelected = selectedFile === file.name;
            return (
              <div
                key={file.name}
                className={`h-8 rounded-lg border inline-flex items-center transition-colors duration-150 ${
                  isSelected
                    ? 'bg-[#1E2025] border-white/[0.16] text-zinc-100'
                    : 'bg-[#17181C] border-white/[0.08] text-zinc-400 hover:text-zinc-200'
                }`}
              >
                <button
                  type="button"
                  onClick={() => onSelectFile(file.name)}
                  className="px-3 h-full text-xs font-mono cursor-pointer truncate max-w-[200px]"
                  title={file.name}
                >
                  {file.name}
                </button>
                <button
                  type="button"
                  onClick={() => onDeleteFile(file.name)}
                  className="pr-2 pl-1 h-full text-zinc-500 hover:text-rose-400 cursor-pointer"
                  title={`Remove ${file.name}`}
                >
                  <X className="w-3 h-3" strokeWidth={1.5} />
                </button>
              </div>
            );
          })}

          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={Boolean(uploadProgress)}
            className="h-8 px-3 rounded-lg border border-dashed border-white/[0.16] hover:border-white/30 text-xs text-zinc-400 hover:text-zinc-100 inline-flex items-center gap-1.5 cursor-pointer transition-colors duration-150"
          >
            <Plus className="w-4 h-4" strokeWidth={1.5} />
            <span>Add file</span>
          </button>
        </div>

        {/* Inline Summary Telemetry */}
        {hasRun && (
          <div className="flex items-center gap-4 text-xs font-mono tabular-nums text-zinc-400">
            <span className="text-emerald-400">{sanitizedCount} sanitized</span>
            {quarantinedCount > 0 && (
              <button
                type="button"
                onClick={onOpenAudit}
                className="text-rose-400 hover:underline cursor-pointer"
              >
                {quarantinedCount} quarantined
              </button>
            )}
            <span>{detectedCount} PII spans</span>
            {seconds !== undefined && <span>{Number(seconds).toFixed(2)}s</span>}
          </div>
        )}
      </div>

      {/* Upload / Run Progress */}
      {(uploadProgress || running) && (
        <div className="p-3 rounded-lg bg-[#17181C] border border-white/[0.08] flex items-center justify-between text-xs font-mono">
          <span className="text-zinc-300">
            {uploadProgress ? `Uploading ${uploadProgress.currentFile}` : 'Executing seven-stage privacy firewall'}
          </span>
          <span className="text-emerald-400">Processing</span>
        </div>
      )}

      {/* Diff Inspector Controls */}
      <div className="bg-[#17181C] border border-white/[0.08] rounded-xl overflow-hidden">
        <div className="px-4 h-12 border-b border-white/[0.08] flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            {/* View Mode Switcher */}
            <div className="flex items-center gap-1 p-1 rounded-lg bg-[#111214] border border-white/[0.08]">
              {[
                { id: 'split', label: 'Split' },
                { id: 'sanitized', label: 'Protected' },
                { id: 'original', label: 'Original' },
              ].map((mode) => (
                <button
                  key={mode.id}
                  type="button"
                  onClick={() => setViewMode(mode.id)}
                  className={`px-2.5 h-6 rounded text-xs font-medium transition-colors duration-150 cursor-pointer ${
                    viewMode === mode.id
                      ? 'bg-[#262830] text-zinc-100'
                      : 'text-zinc-500 hover:text-zinc-300'
                  }`}
                >
                  {mode.label}
                </button>
              ))}
            </div>

            {diffData && (
              <span
                className={`text-xs font-mono inline-flex items-center gap-1.5 ${
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

          <div className="flex items-center gap-2">
            {!hasRun && (
              <button
                type="button"
                onClick={onRun}
                disabled={running}
                className="h-8 px-3 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-[#111214] text-xs font-medium inline-flex items-center gap-1.5 cursor-pointer transition-colors duration-150"
              >
                <Play className="w-4 h-4" strokeWidth={1.5} />
                <span>Sanitize now</span>
              </button>
            )}

            {diffData?.sanitized && (
              <button
                type="button"
                onClick={handleCopy}
                className="h-8 px-3 rounded-lg bg-[#1E2025] hover:bg-[#262830] border border-white/[0.08] text-xs font-medium text-zinc-200 inline-flex items-center gap-2 cursor-pointer transition-colors duration-150"
              >
                {copied ? (
                  <Check className="w-4 h-4 text-emerald-400" strokeWidth={1.5} />
                ) : (
                  <Copy className="w-4 h-4 text-zinc-400" strokeWidth={1.5} />
                )}
                <span>{copied ? 'Copied' : 'Copy output'}</span>
              </button>
            )}
          </div>
        </div>

        {/* Diff Body */}
        <div
          className={`grid divide-y md:divide-y-0 md:divide-x divide-white/[0.08] ${
            viewMode === 'split' ? 'md:grid-cols-2' : 'grid-cols-1'
          }`}
        >
          {(viewMode === 'split' || viewMode === 'original') && (
            <div className="flex flex-col min-w-0">
              <div className="px-4 py-2 bg-[#131417] border-b border-white/[0.06] flex items-center justify-between text-xs text-zinc-500">
                <span>Original raw input</span>
                <span className="font-mono">Source</span>
              </div>
              <div className="p-4 bg-[#0D0E10] overflow-auto max-h-[540px]">
                <pre className="text-xs font-mono text-zinc-300 whitespace-pre-wrap leading-relaxed select-text">
                  {diffData?.original || '// Select a file to inspect'}
                </pre>
              </div>
            </div>
          )}

          {(viewMode === 'split' || viewMode === 'sanitized') && (
            <div className="flex flex-col min-w-0">
              <div className="px-4 py-2 bg-[#131417] border-b border-white/[0.06] flex items-center justify-between text-xs text-zinc-500">
                <span>Protected output</span>
                <span className={`font-mono ${isQuarantined ? 'text-rose-400' : 'text-emerald-400'}`}>
                  {isQuarantined ? 'Quarantined' : 'De-identified'}
                </span>
              </div>
              <div className="p-4 bg-[#0D0E10] overflow-auto max-h-[540px] flex-1">
                {diffData?.sanitized ? (
                  <pre className="text-xs font-mono text-zinc-300 whitespace-pre-wrap leading-relaxed select-text">
                    {highlightSanitizedText(diffData.sanitized)}
                  </pre>
                ) : isQuarantined ? (
                  <div className="h-full min-h-[260px] flex flex-col items-center justify-center text-center p-6">
                    <AlertOctagon className="w-5 h-5 text-rose-400 mb-3" strokeWidth={1.5} />
                    <p className="text-sm font-medium text-zinc-100">
                      File blocked by publication gate
                    </p>
                    <p className="text-xs text-zinc-400 mt-2 max-w-md leading-relaxed">
                      Reason: <span className="text-zinc-200 font-mono">{quarantineReason}</span>.
                      RAKSHA excluded this file from <code className="text-zinc-300">sanitized/</code> because it failed security checks or residual identifier verification.
                    </p>
                    <button
                      type="button"
                      onClick={onOpenAudit}
                      className="mt-4 h-8 px-3 rounded-lg bg-[#1E2025] hover:bg-[#262830] border border-white/[0.08] text-xs font-medium text-zinc-200 inline-flex items-center gap-2 cursor-pointer transition-colors duration-150"
                    >
                      <span>View quarantine log</span>
                      <ArrowRight className="w-4 h-4 text-zinc-400" strokeWidth={1.5} />
                    </button>
                  </div>
                ) : (
                  <pre className="text-xs font-mono text-zinc-500 whitespace-pre-wrap leading-relaxed">
                    {'// Click "Run firewall" to generate protected output'}
                  </pre>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
