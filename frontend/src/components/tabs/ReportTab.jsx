// Purpose: Tab 7 - Formatted report.json viewer and one-click ZIP download button.
import React from 'react';
import { FileCheck, Download, Copy, Check } from 'lucide-react';

export default function ReportTab({ report }) {
  const [copied, setCopied] = React.useState(false);

  const copyToClipboard = () => {
    if (!report) return;
    navigator.clipboard.writeText(JSON.stringify(report, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="space-y-6">
      <div className="bg-[#111C2E] border border-[#1E293B] rounded-xl p-6 shadow-sm flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-teal-500/10 border border-teal-500/20 flex items-center justify-center text-teal-400">
            <FileCheck className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-base font-bold text-white">
              Official Compliance Audit Report (<code className="text-xs text-teal-300 font-mono">report.json</code>)
            </h2>
            <p className="text-xs text-slate-400">
              Compliant with Track 3 specifications: SHA-256 integrity hashes, anonymized references, and zero raw PII leaks.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {report && (
            <button
              onClick={copyToClipboard}
              className="px-3.5 py-2 bg-[#0B1120] hover:bg-[#16243C] border border-[#1E293B] rounded-lg text-xs font-semibold text-slate-300 hover:text-white transition flex items-center gap-1.5"
            >
              {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
              {copied ? 'Copied' : 'Copy JSON'}
            </button>
          )}

          <a
            href="/api/download-zip"
            download="raksha_sanitized_package.zip"
            className="px-4 py-2 bg-gradient-to-r from-teal-500 to-cyan-600 hover:from-teal-400 hover:to-cyan-500 text-slate-950 rounded-lg text-xs font-bold shadow-lg shadow-teal-500/20 transition flex items-center gap-2"
          >
            <Download className="w-4 h-4" />
            Download Sanitized ZIP Package
          </a>
        </div>
      </div>

      <div className="bg-[#111C2E] border border-[#1E293B] rounded-xl overflow-hidden p-5 shadow-sm">
        <pre className="text-xs font-mono text-teal-300/90 bg-[#070B14] p-5 rounded-lg border border-[#1E293B] overflow-auto max-h-[550px] leading-relaxed">
          {report ? JSON.stringify(report, null, 2) : '// Execute the pipeline to view generated report.json'}
        </pre>
      </div>
    </div>
  );
}
