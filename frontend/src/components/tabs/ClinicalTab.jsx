import React from 'react';
import { CheckCircle2 } from 'lucide-react';

const PRESERVED_ENTITIES = [
  {
    category: 'Blood pressure and vitals',
    example: 'BP 165/95 mmHg, SpO2 94%, Pulse 74/min, Temp 98.4 F',
    role: 'CLINICAL_PROTECTED',
    status: 'Preserved',
  },
  {
    category: 'High-risk medications',
    example: 'Ramipril, Insulin Glargine, Metformin, Dolo 650, Pantoprazole',
    role: 'CLINICAL_PROTECTED',
    status: 'Preserved',
  },
  {
    category: 'Dosages and regimens',
    example: '5mg OD, 14 units SC at bedtime, 500mg BD, 1-0-1, SOS',
    role: 'CLINICAL_PROTECTED',
    status: 'Preserved',
  },
  {
    category: 'Diagnostic codes and labs',
    example: 'HbA1c 7.4% (LOINC 4548-4), Severe Hypertension, T2DM',
    role: 'CLINICAL_PROTECTED',
    status: 'Preserved',
  },
];

export default function ClinicalTab() {
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-baseline justify-between gap-4">
        <div>
          <h2 className="text-base font-medium text-zinc-100">
            Clinical safeguard matrix
          </h2>
          <p className="text-xs text-zinc-400 mt-1">
            ClinicalGuard overrides overlapping PII spans so vitals, drugs, and doses remain verbatim
          </p>
        </div>

        <span className="text-xs font-mono text-emerald-400 inline-flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4" strokeWidth={1.5} />
          <span>Preservation requires verification</span>
        </span>
      </div>

      <div className="bg-[#17181C] border border-white/[0.08] rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-[#131417] text-zinc-400 border-b border-white/[0.08]">
              <tr>
                <th className="py-3 px-4 font-medium">Category</th>
                <th className="py-3 px-4 font-medium">Protected examples</th>
                <th className="py-3 px-4 font-medium">Span role</th>
                <th className="py-3 px-4 font-medium text-right">Outcome</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.06]">
              {PRESERVED_ENTITIES.map((item) => (
                <tr key={item.category} className="hover:bg-white/[0.02] transition-colors duration-150">
                  <td className="py-4 px-4 text-zinc-100 font-medium">{item.category}</td>
                  <td className="py-4 px-4 font-mono text-zinc-300">{item.example}</td>
                  <td className="py-4 px-4 font-mono text-zinc-400">{item.role}</td>
                  <td className="py-4 px-4 font-mono text-emerald-400 text-right">{item.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
