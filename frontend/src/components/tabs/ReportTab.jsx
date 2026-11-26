import React from 'react';
import { Download, Copy, Check, ShieldCheck } from 'lucide-react';

export default function ReportTab({ report }) {
  const [copied, setCopied] = React.useState(false);

  const quarantinedFiles = report?.files ? report.files.filter((f) => f.status === 'quarantined') : [];
  const quarantinedCount = report?.counts?.files_quarantined ?? quarantinedFiles.length;

  const copyToClipboard = () => {
    if (!report) return;
    navigator.clipboard.writeText(JSON.stringify(report, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="space-y-8">
      {/* Quarantine Register */}
      <section className="space-y-4">
        <div className="flex flex-wrap items-baseline justify-between gap-4">
          <div>
            <h2 className="text-base font-medium text-zinc-100">
              Quarantine log
            </h2>
            <p className="text-xs text-zinc-400 mt-1">
              Files isolated due to path traversal, corrupt encodings, or residual verification failures
            </p>
          </div>
          <span className={`text-xs font-mono tabular-nums ${quarantinedCount > 0 ? 'text-rose-400' : 'text-zinc-400'}`}>
            {report ? `${quarantinedCount} quarantined` : 'Awaiting run'}
          </span>
        </div>

        <div className="bg-[#17181C] border border-white/[0.08] rounded-xl overflow-hidden">
          {quarantinedFiles.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-[#131417] text-zinc-400 border-b border-white/[0.08]">
                  <tr>
                    <th className="py-3 px-4 font-medium">Input SHA-256</th>
                    <th className="py-3 px-4 font-medium">Status</th>
                    <th className="py-3 px-4 font-medium">Reason</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.06] font-mono">
                  {quarantinedFiles.map((f, idx) => (
                    <tr key={idx} className="hover:bg-white/[0.02] transition-colors duration-150">
                      <td className="py-3 px-4 text-zinc-400 truncate max-w-xs" title={f.input_sha256}>
                        {f.input_sha256}
                      </td>
                      <td className="py-3 px-4 text-rose-400">{f.status}</td>
                      <td className="py-3 px-4 text-zinc-200">
                        {f.reason || 'Security validation rule triggered'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="py-8 px-4 flex items-center justify-center gap-2 text-xs text-zinc-500">
              <ShieldCheck className="w-4 h-4 text-zinc-600" strokeWidth={1.5} />
              <span>No quarantined files recorded</span>
            </div>
          )}
        </div>
      </section>

      {/* Official report.json */}
      <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="text-base font-medium text-zinc-100">
              Compliance audit report (<code className="text-xs font-mono text-zinc-300">report.json</code>)
            </h2>
            <p className="text-xs text-zinc-400 mt-1">
              SHA-256 integrity hashes and anonymized telemetry
            </p>
          </div>

          <div className="flex items-center gap-2">
            {report && (
              <button
                type="button"
                onClick={copyToClipboard}
                className="h-8 px-3 bg-[#1E2025] hover:bg-[#262830] border border-white/[0.08] rounded-lg text-xs font-medium text-zinc-200 transition-colors duration-150 inline-flex items-center gap-2 cursor-pointer"
              >
                {copied ? <Check className="w-4 h-4 text-emerald-400" strokeWidth={1.5} /> : <Copy className="w-4 h-4 text-zinc-400" strokeWidth={1.5} />}
                <span>{copied ? 'Copied' : 'Copy JSON'}</span>
              </button>
            )}

            <a
              href="/api/download-zip"
              download="raksha_sanitized_package.zip"
              className="h-8 px-3 bg-[#F4F4F5] hover:bg-white text-[#111214] rounded-lg text-xs font-medium transition-colors duration-150 inline-flex items-center gap-2"
            >
              <Download className="w-4 h-4" strokeWidth={1.5} />
              <span>Download ZIP</span>
            </a>
          </div>
        </div>

        <div className="bg-[#17181C] border border-white/[0.08] rounded-xl overflow-hidden p-2">
          <pre className="text-xs font-mono text-zinc-300 bg-[#0D0E10] p-5 rounded-lg border border-white/[0.06] overflow-auto max-h-[480px] leading-relaxed select-text">
            {report ? JSON.stringify(report, null, 2) : '// Run the firewall to generate report.json'}
          </pre>
        </div>
      </section>
    </div>
  );
}
