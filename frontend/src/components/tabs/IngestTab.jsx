// Purpose: Tab 1 - Redesigned enterprise upload center, 3 scenario cards, and active file queue.
import React, { useState, useRef } from 'react';
import {
  UploadCloud,
  FileSpreadsheet,
  FileCode,
  FileText,
  AlertCircle,
  Trash2,
  Play,
  Sparkles,
  ShieldAlert,
  HeartPulse,
  Network,
  CheckCircle2,
  FolderOpen,
  ArrowRight,
  HardDrive
} from 'lucide-react';

export default function IngestTab({
  files,
  onLoadPreset,
  onFileUpload,
  uploadProgress,
  onDeleteFile,
  onClearQueue,
  onRun,
  running,
}) {
  const [isDragging, setIsDragging] = useState(false);
  const [loadingPreset, setLoadingPreset] = useState(null);
  const fileInputRef = useRef(null);

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

  const formatFileSize = (bytes) => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  };

  const getFormatBadge = (fmt) => {
    switch (fmt) {
      case 'csv':
        return { label: 'CSV', bg: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30', icon: FileSpreadsheet };
      case 'tsv':
        return { label: 'TSV', bg: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30', icon: FileSpreadsheet };
      case 'fhir_r4':
        return { label: 'FHIR R4', bg: 'bg-cyan-500/15 text-cyan-400 border-cyan-500/30', icon: FileCode };
      case 'json':
        return { label: 'JSON', bg: 'bg-blue-500/15 text-blue-400 border-blue-500/30', icon: FileCode };
      case 'text':
        return { label: 'TEXT (Devanagari/UTF-8)', bg: 'bg-purple-500/15 text-purple-400 border-purple-500/30', icon: FileText };
      default:
        return { label: 'UNSUPPORTED', bg: 'bg-rose-500/15 text-rose-400 border-rose-500/30', icon: AlertCircle };
    }
  };

  return (
    <div className="ingest-page space-y-8">
      {/* SECTION 1: 3 SCENARIO DEMONSTRATION CARDS */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-sm font-bold uppercase tracking-wider text-slate-300 flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-amber-400" />
              Pre-Configured Hackathon Demonstration Scenarios
            </h2>
            <p className="text-xs text-slate-400 mt-0.5">
              Instant one-click evaluation suites configured specifically for the Dean and competition judges.
            </p>
          </div>
        </div>

        <div className="grid md:grid-cols-3 gap-4">
          {/* Scenario A */}
          <div className="scenario-card bg-[#111C2E] border border-[#1E293B] hover:border-teal-500/40 rounded-xl p-5 flex flex-col justify-between transition-all duration-200 group hover:shadow-lg hover:shadow-teal-500/5">
            <div>
              <div className="flex items-center justify-between mb-3">
                <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-teal-500/15 text-teal-400 border border-teal-500/30 uppercase tracking-wider">
                  Scenario 01
                </span>
                <div className="w-8 h-8 rounded-lg bg-teal-500/10 border border-teal-500/20 flex items-center justify-center text-teal-400">
                  <Network className="w-4 h-4" />
                </div>
              </div>
              <h3 className="text-sm font-bold text-white group-hover:text-teal-300 transition-colors">
                Cross-Hospital Multilingual Linkage
              </h3>
              <p className="text-xs text-slate-400 mt-2 leading-relaxed">
                Links patient <span className="text-slate-200 font-medium">"Aarav Sharma"</span> across Apollo CSV, AIIMS Hindi ICU Consultation note, and FHIR R4 JSON into the exact same pseudonymous cluster ID.
              </p>
              <div className="flex flex-wrap gap-1.5 mt-3">
                <span className="text-[10px] px-2 py-0.5 rounded bg-[#0B1120] text-slate-300 border border-[#1E293B]">Apollo CSV</span>
                <span className="text-[10px] px-2 py-0.5 rounded bg-[#0B1120] text-slate-300 border border-[#1E293B]">AIIMS Hindi Note</span>
                <span className="text-[10px] px-2 py-0.5 rounded bg-[#0B1120] text-slate-300 border border-[#1E293B]">FHIR R4 JSON</span>
              </div>
            </div>
            <button
              onClick={() => triggerPreset('multilingual-linkage')}
              disabled={loadingPreset !== null}
              className="mt-5 w-full py-2.5 px-4 bg-teal-500/15 hover:bg-teal-500 text-teal-300 hover:text-slate-950 font-semibold rounded-lg text-xs border border-teal-500/30 hover:border-teal-400 transition-all flex items-center justify-center gap-2 group/btn shadow-sm"
            >
              <span>{loadingPreset === 'multilingual-linkage' ? 'Loading Scenario...' : 'Load Scenario A'}</span>
              <ArrowRight className="w-3.5 h-3.5 group-hover/btn:translate-x-0.5 transition-transform" />
            </button>
          </div>

          {/* Scenario B */}
          <div className="scenario-card bg-[#111C2E] border border-[#1E293B] hover:border-cyan-500/40 rounded-xl p-5 flex flex-col justify-between transition-all duration-200 group hover:shadow-lg hover:shadow-cyan-500/5">
            <div>
              <div className="flex items-center justify-between mb-3">
                <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-cyan-500/15 text-cyan-400 border border-cyan-500/30 uppercase tracking-wider">
                  Scenario 02
                </span>
                <div className="w-8 h-8 rounded-lg bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center text-cyan-400">
                  <HeartPulse className="w-4 h-4" />
                </div>
              </div>
              <h3 className="text-sm font-bold text-white group-hover:text-cyan-300 transition-colors">
                ICU Clinical Safety & Dosage Preservation
              </h3>
              <p className="text-xs text-slate-400 mt-2 leading-relaxed">
                Proves zero clinical harm: ICU vitals (<span className="text-slate-200 font-mono">BP 165/95</span>, <span className="text-slate-200 font-mono">SpO2 94%</span>), medications (<span className="text-slate-200">Ramipril</span>, <span className="text-slate-200">Insulin</span>), and exact doses (<span className="text-slate-200 font-mono">14 units</span>) stay 100% untouched.
              </p>
              <div className="flex flex-wrap gap-1.5 mt-3">
                <span className="text-[10px] px-2 py-0.5 rounded bg-[#0B1120] text-slate-300 border border-[#1E293B]">ICU TSV</span>
                <span className="text-[10px] px-2 py-0.5 rounded bg-[#0B1120] text-slate-300 border border-[#1E293B]">Discharge Note</span>
                <span className="text-[10px] px-2 py-0.5 rounded bg-[#0B1120] text-emerald-400 border border-emerald-500/30">100% Integrity</span>
              </div>
            </div>
            <button
              onClick={() => triggerPreset('clinical-preservation')}
              disabled={loadingPreset !== null}
              className="mt-5 w-full py-2.5 px-4 bg-cyan-500/15 hover:bg-cyan-500 text-cyan-300 hover:text-slate-950 font-semibold rounded-lg text-xs border border-cyan-500/30 hover:border-cyan-400 transition-all flex items-center justify-center gap-2 group/btn shadow-sm"
            >
              <span>{loadingPreset === 'clinical-preservation' ? 'Loading Scenario...' : 'Load Scenario B'}</span>
              <ArrowRight className="w-3.5 h-3.5 group-hover/btn:translate-x-0.5 transition-transform" />
            </button>
          </div>

          {/* Scenario C */}
          <div className="scenario-card bg-[#111C2E] border border-[#1E293B] hover:border-rose-500/40 rounded-xl p-5 flex flex-col justify-between transition-all duration-200 group hover:shadow-lg hover:shadow-rose-500/5">
            <div>
              <div className="flex items-center justify-between mb-3">
                <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-rose-500/15 text-rose-400 border border-rose-500/30 uppercase tracking-wider">
                  Scenario 03
                </span>
                <div className="w-8 h-8 rounded-lg bg-rose-500/10 border border-rose-500/20 flex items-center justify-center text-rose-400">
                  <ShieldAlert className="w-4 h-4" />
                </div>
              </div>
              <h3 className="text-sm font-bold text-white group-hover:text-rose-300 transition-colors">
                Hostile Attack & Quarantine Defense
              </h3>
              <p className="text-xs text-slate-400 mt-2 leading-relaxed">
                Stresses firewall defenses with malicious path traversal (<span className="text-rose-300 font-mono">../../etc/passwd</span>), truncated multibyte UTF-8, and raw binary firmware without crashing.
              </p>
              <div className="flex flex-wrap gap-1.5 mt-3">
                <span className="text-[10px] px-2 py-0.5 rounded bg-[#0B1120] text-slate-300 border border-[#1E293B]">Traversal Attack</span>
                <span className="text-[10px] px-2 py-0.5 rounded bg-[#0B1120] text-slate-300 border border-[#1E293B]">Corrupted UTF-8</span>
                <span className="text-[10px] px-2 py-0.5 rounded bg-[#0B1120] text-rose-400 border border-rose-500/30">Auto-Quarantine</span>
              </div>
            </div>
            <button
              onClick={() => triggerPreset('security-quarantine')}
              disabled={loadingPreset !== null}
              className="mt-5 w-full py-2.5 px-4 bg-rose-500/15 hover:bg-rose-500 text-rose-300 hover:text-slate-950 font-semibold rounded-lg text-xs border border-rose-500/30 hover:border-rose-400 transition-all flex items-center justify-center gap-2 group/btn shadow-sm"
            >
              <span>{loadingPreset === 'security-quarantine' ? 'Loading Scenario...' : 'Load Scenario C'}</span>
              <ArrowRight className="w-3.5 h-3.5 group-hover/btn:translate-x-0.5 transition-transform" />
            </button>
          </div>
        </div>
      </div>

      {/* SECTION 2: PROFESSIONAL DRAG-AND-DROP FILE UPLOAD PANEL */}
      <div className="upload-panel bg-[#111C2E] border border-[#1E293B] rounded-xl p-6 shadow-sm">
        <div
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          className={`upload-dropzone border-2 border-dashed rounded-xl p-10 text-center transition-all duration-200 flex flex-col items-center justify-center ${
            isDragging
              ? 'border-teal-400 bg-teal-500/10 scale-[1.005]'
              : 'border-[#1E293B] hover:border-teal-500/40 bg-[#0B1120]/70'
          }`}
        >
          {/* Circular Accent Background Icon */}
          <div className="w-16 h-16 rounded-full bg-gradient-to-br from-teal-500/20 to-cyan-500/10 border border-teal-500/30 flex items-center justify-center mb-4 shadow-inner">
            <UploadCloud className="w-8 h-8 text-teal-400" />
          </div>

          <h3 className="text-base font-bold text-white tracking-tight">
            Upload Healthcare Files
          </h3>
          <p className="text-xs text-slate-400 mt-1.5 max-w-md mx-auto leading-relaxed">
            Drag and drop your clinical datasets here or browse files from your computer. Supports multi-file concurrent ingestion.
          </p>

          {/* Browse Files Button */}
          <div className="mt-5 flex items-center gap-3">
            <input
              type="file"
              ref={fileInputRef}
              multiple
              onClick={(e) => { e.target.value = null; }}
              onChange={onFileUpload}
              className="hidden"
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={running}
              className="px-5 py-2.5 bg-gradient-to-r from-teal-500 to-cyan-600 hover:from-teal-400 hover:to-cyan-500 text-slate-950 font-bold rounded-lg text-xs shadow-lg shadow-teal-500/20 transition-all flex items-center gap-2 cursor-pointer disabled:opacity-60 disabled:cursor-wait"
            >
              <FolderOpen className="w-4 h-4" />
              {running ? 'Processing Pipeline…' : 'Browse Files'}
            </button>
          </div>

          {uploadProgress && (
            <div className="upload-progress" role="status" aria-live="polite">
              <div className="upload-progress-heading">
                <span>{uploadProgress.processing ? 'Creating protected output' : uploadProgress.completed === uploadProgress.total ? 'Finishing upload' : `Uploading ${uploadProgress.currentFile}`}</span>
                <span>{uploadProgress.processing ? 'Redacting sensitive data' : `${uploadProgress.completed} / ${uploadProgress.total} files`}</span>
              </div>
              <div
                className="upload-progress-track"
                role="progressbar"
                aria-label="File upload progress"
                aria-valuemin={0}
                aria-valuemax={uploadProgress.total * 100}
                aria-valuenow={uploadProgress.completed * 100 + uploadProgress.percent}
              >
                <div className="upload-progress-fill" style={{ width: `${((uploadProgress.completed * 100 + uploadProgress.percent) / (uploadProgress.total * 100)) * 100}%` }} />
              </div>
            </div>
          )}

          {/* Supported Format Badges */}
          <div className="mt-6 pt-5 border-t border-[#1E293B]/80 w-full max-w-xl flex flex-wrap items-center justify-center gap-2">
            <span className="text-[11px] font-semibold text-slate-400 mr-1 font-mono uppercase">Supported Formats:</span>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#111C2E] text-emerald-400 border border-emerald-500/30 font-semibold">CSV</span>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#111C2E] text-emerald-400 border border-emerald-500/30 font-semibold">TSV</span>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#111C2E] text-blue-400 border border-blue-500/30 font-semibold">JSON</span>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#111C2E] text-cyan-400 border border-cyan-500/30 font-semibold">FHIR R4 JSON</span>
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#111C2E] text-purple-400 border border-purple-500/30 font-semibold">TXT (UTF-8 / Latin-1 / Devanagari)</span>
          </div>

          {/* Limit and Encoding Notice */}
          <div className="mt-2 text-[11px] text-slate-500 font-mono flex items-center gap-3">
            <span>Max File Size: 200 MB</span>
            <span>•</span>
            <span>Zero Cloud Uploads • Strictly Local & Offline</span>
          </div>
        </div>
      </div>

      {/* SECTION 3: STAGED INGESTION QUEUE */}
      <div className="queue-panel bg-[#111C2E] border border-[#1E293B] rounded-xl p-6 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <div className="flex items-center gap-2.5">
            <HardDrive className="w-4 h-4 text-teal-400" />
            <h3 className="text-sm font-bold text-white uppercase tracking-wider">
              Active Ingestion Queue
            </h3>
            <span className="px-2 py-0.5 rounded-full text-[11px] font-mono font-bold bg-teal-500/15 text-teal-400 border border-teal-500/30">
              {files.length} {files.length === 1 ? 'file' : 'files'}
            </span>
          </div>

          {/* Action Row */}
          <div className="flex items-center gap-2.5">
            {files.length > 0 && (
              <button
                onClick={onClearQueue}
                className="px-3 py-1.5 text-xs font-medium text-slate-400 hover:text-rose-400 bg-[#0B1120] hover:bg-rose-500/10 border border-[#1E293B] hover:border-rose-500/30 rounded-lg transition-all flex items-center gap-1.5"
                title="Remove all files from the queue"
              >
                <Trash2 className="w-3.5 h-3.5" />
                Clear Queue
              </button>
            )}

            <button
              onClick={onRun}
              disabled={running || files.length === 0}
              className={`px-5 py-2 rounded-lg font-bold text-xs transition-all flex items-center gap-2 shadow-lg ${
                running || files.length === 0
                  ? 'bg-slate-800 text-slate-500 cursor-not-allowed border border-slate-700'
                  : 'bg-gradient-to-r from-teal-500 to-emerald-500 hover:from-teal-400 hover:to-emerald-400 text-slate-950 shadow-teal-500/20'
              }`}
            >
              <Play className={`w-3.5 h-3.5 ${running ? 'animate-spin' : 'fill-slate-950'}`} />
              {running ? 'Processing Firewall...' : 'Execute Firewall Pipeline'}
            </button>
          </div>
        </div>

        {/* Queue Rows */}
        {files.length === 0 ? (
          <div className="py-12 px-4 text-center border border-dashed border-[#1E293B] rounded-xl bg-[#0B1120]/40">
            <div className="w-12 h-12 rounded-full bg-slate-800/60 flex items-center justify-center mx-auto mb-3 text-slate-500">
              <FileText className="w-6 h-6" />
            </div>
            <p className="text-xs font-semibold text-slate-300">No Healthcare Files Staged in Queue</p>
            <p className="text-[11px] text-slate-500 mt-1 max-w-sm mx-auto">
              Select one of the three evaluation scenarios above, or drag and drop custom hospital files into the upload zone.
            </p>
          </div>
        ) : (
          <div className="space-y-2.5">
            {files.map((file) => {
              const badge = getFormatBadge(file.format);
              const Icon = badge.icon;
              return (
                <div
                  key={file.name}
                  className="bg-[#0B1120] border border-[#1E293B] hover:border-[#1E3A5F] rounded-lg p-3 flex items-center justify-between gap-4 transition-all"
                >
                  {/* File Info */}
                  <div className="flex items-center gap-3 overflow-hidden">
                    <div className="w-8 h-8 rounded-lg bg-[#111C2E] border border-[#1E293B] flex items-center justify-center shrink-0">
                      <Icon className="w-4 h-4 text-slate-300" />
                    </div>
                    <div className="truncate">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-bold text-white truncate max-w-xs md:max-w-md font-mono" title={file.name}>
                          {file.name}
                        </span>
                        <span className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded border uppercase shrink-0 ${badge.bg}`}>
                          {badge.label}
                        </span>
                      </div>
                      <p className="text-[11px] text-slate-500 font-mono mt-0.5">
                        {formatFileSize(file.size)} • Staged for Ingestion
                      </p>
                    </div>
                  </div>

                  {/* Actions & Status */}
                  <div className="flex items-center gap-3 shrink-0">
                    <span className="text-[11px] font-mono text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-2 py-0.5 rounded hidden sm:inline-flex items-center gap-1">
                      <CheckCircle2 className="w-3 h-3" />
                      Ready
                    </span>

                    <button
                      onClick={() => onDeleteFile(file.name)}
                      className="p-1.5 text-slate-500 hover:text-rose-400 hover:bg-rose-500/10 rounded-md transition-colors"
                      title={`Remove ${file.name} from queue`}
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
