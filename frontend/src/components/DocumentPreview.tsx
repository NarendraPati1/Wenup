import React, { useState } from 'react';
import { Download, X, Printer, Copy, CheckCircle2, FileText, Sparkles } from 'lucide-react';
import type { DocumentState } from '../types';

interface DocumentPreviewProps {
  state: DocumentState;
  progress?: { completed: number; total: number; label: string; percentage: number };
}

function generateDocumentText(state: DocumentState): string {
  const lines: string[] = [];
  lines.push('================================================================================');
  lines.push('                     PERSONAL WISHES DOCUMENT & TESTAMENTARY DRAFT              ');
  lines.push('                     PERSONAL WISHES DOCUMENT                                  ');
  lines.push('================================================================================');
  lines.push('');
  lines.push(`Date of Draft: ${new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })}`);
  lines.push('');
  lines.push('ARTICLE I: DECLARATION & TESTATOR IDENTIFICATION');
  lines.push('--------------------------------------------------------------------------------');
  lines.push(`I, ${state.full_name || '[Full Legal Name Not Yet Confirmed]'}, residing at:`);
  lines.push(`   ${state.home_address || '[Residential Address Not Yet Confirmed]'}`);
  lines.push('declare this document to be an expression of my personal wishes and intentions');
  lines.push('concerning the administration and disposition of my estate and affairs.');
  lines.push('');
  lines.push('ARTICLE II: JURISDICTION & TERRITORIAL SCOPE');
  lines.push('--------------------------------------------------------------------------------');
  if (state.covers_worldwide_assets === null) {
    lines.push('   [Asset coverage scope not yet confirmed]');
  } else if (state.covers_worldwide_assets) {
    lines.push('   This document and its instructions are intended to cover and apply to all my');
    lines.push('   real, personal, tangible, and intangible assets situated worldwide, across');
    lines.push('   all territorial jurisdictions and countries.');
  } else {
    lines.push('   This document is restricted in scope and applies exclusively to my assets and');
    lines.push('   interests situated in my domestic/local jurisdiction.');
  }
  lines.push('');
  lines.push('ARTICLE III: FAMILY & DEPENDENTS PROVISIONS');
  lines.push('--------------------------------------------------------------------------------');
  if (state.has_children === null) {
    lines.push('   [Dependent status not yet confirmed]');
  } else if (state.has_children) {
    const childrenList = state.children || state.children_names;
    const names = childrenList && childrenList.length > 0
      ? childrenList.join(', ')
      : '[Children recorded — specific names pending]';
    lines.push(`   I acknowledge that I have children, namely: ${names}.`);
    lines.push('   My executor shall manage and safeguard any benefits intended for my children');
    lines.push('   in accordance with the directives set forth herein.');
  } else {
    lines.push('   I declare that I have no minor or dependent children at the time of executing');
    lines.push('   this document, and accordingly make no provisions for dependent descendants.');
  }
  lines.push('');
  lines.push('ARTICLE IV: APPOINTMENT OF EXECUTOR & FIDUCIARY POWERS');
  lines.push('--------------------------------------------------------------------------------');
  const execName = state.executor?.name || '[Executor Name Not Confirmed]';
  const execRel = state.executor?.relationship || '[Relationship Not Confirmed]';
  lines.push(`   I hereby designate and nominate ${execName} (my ${execRel})`);
  lines.push('   to serve as the primary Executor and personal representative of my estate.');
  lines.push('   My Executor shall possess all customary administrative powers to settle accounts,');
  lines.push('   manage assets, discharge liabilities, and carry out my expressed wishes.');
  lines.push('');
  lines.push('ARTICLE V: SPECIFIC GIFTS & BEQUESTS');
  lines.push('--------------------------------------------------------------------------------');
  if (state.specific_gifts && state.specific_gifts.length > 0) {
    lines.push('   I direct my Executor to distribute the following specific gifts:');
    state.specific_gifts.forEach((gift, idx) => {
      lines.push(`   ${idx + 1}. ${gift}`);
    });
  } else if (state.specific_gifts !== null) {
    lines.push('   I make no specific bequests of personal property at this time;');
    lines.push('   all personal effects shall form part of my general residuary estate.');
  } else {
    lines.push('   [Specific gifts not yet confirmed]');
  }
  lines.push('');
  lines.push('ARTICLE VI: RESIDUARY ESTATE & ADDITIONAL DIRECTIONS');
  lines.push('--------------------------------------------------------------------------------');
  if (state.additional_wishes) {
    const wishes = Array.isArray(state.additional_wishes) ? state.additional_wishes : [state.additional_wishes];
    if (wishes.length > 0 && wishes.some(w => w && w.trim())) {
      wishes.forEach((wish, idx) => {
        if (wish && wish.trim()) {
          lines.push(`   ${idx + 1}. "${wish}"`);
        }
      });
    } else {
      lines.push('   No additional special directives or restrictions were specified.');
    }
  } else if (state.additional_wishes !== null) {
    lines.push('   No additional special directives or restrictions were specified.');
  } else {
    lines.push('   [Additional wishes not yet confirmed]');
  }
  lines.push('');
  lines.push('ARTICLE VII: ATTESTATION & EXECUTION');
  lines.push('--------------------------------------------------------------------------------');
  lines.push('IN WITNESS WHEREOF, I have executed this statement of personal wishes.');
  lines.push('');
  lines.push('Signature: _________________________________    Date: ________________________');
  lines.push(`Printed Name: ${state.full_name || '__________________________'}`);
  lines.push('');
  lines.push('WITNESS 1:                                      WITNESS 2:');
  lines.push('Signature: _________________________________    Signature: ___________________');
  lines.push('Printed Name: ______________________________    Printed Name: ________________');
  lines.push('Address: ___________________________________    Address: _____________________');
  lines.push('');
  lines.push('================================================================================');
  lines.push('Prepared from the details confirmed during your intake.');
  lines.push('================================================================================');
  return lines.join('\n');
}

export const DocumentPreview: React.FC<DocumentPreviewProps> = ({ state, progress: _progress }) => {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const isComplete = Boolean(
    state.full_name &&
    state.home_address &&
    state.covers_worldwide_assets !== null &&
    state.has_children !== null &&
    state.executor.name &&
    state.specific_gifts !== null &&
    state.additional_wishes !== null
  );

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3000);
  };

  const handleDownload = () => {
    const text = generateDocumentText(state);
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${(state.full_name || 'personal-wishes').toLowerCase().replace(/\s+/g, '_')}_document.txt`;
    a.click();
    URL.revokeObjectURL(url);
    showToast('Document downloaded as .txt');
  };

  const handleCopy = () => {
    const text = generateDocumentText(state);
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
    showToast('Document copied to clipboard!');
  };

  const handlePrint = () => {
    window.print();
  };

  return (
    <div className="flex flex-col h-full bg-white rounded-2xl border border-slate-100 p-5 shadow-sm overflow-hidden relative">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="absolute top-3 left-1/2 -translate-x-1/2 z-30 bg-slate-900 text-white text-xs font-medium px-4 py-2 rounded-full shadow-lg flex items-center gap-2 animate-fade-in">
          <Sparkles className="w-3.5 h-3.5 text-[#ccff00]" />
          <span>{toastMessage}</span>
        </div>
      )}

      {/* Action Header */}
      <div className="flex items-center justify-between mb-4 shrink-0">
        <div className="flex items-center gap-2">
          <h2 className="text-xl font-serif-title font-semibold text-[#1e1b4b]">
            Document preview
          </h2>
          {isComplete && (
            <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-200">
              <CheckCircle2 className="w-3 h-3 text-emerald-600" />
              Complete
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handleDownload}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-700 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors shadow-xs"
            title="Download document text file"
          >
            <Download className="w-3.5 h-3.5 text-slate-600" />
            <span>Download</span>
          </button>

        </div>
      </div>

      {/* Complete Banner Prompt */}
      {isComplete && (
        <div className="mb-3 shrink-0 p-2.5 bg-gradient-to-r from-[#f6f3fe] to-[#ecfccb] border border-[#d9f99d] rounded-xl flex items-center">
          <div className="flex items-center gap-2 text-xs text-slate-800">
            <span className="text-base">🎉</span>
            <span className="font-semibold">All details recorded!</span>
            <span className="text-slate-600 hidden md:inline">Your document preview is up to date.</span>
          </div>
        </div>
      )}

      {/* Document Sheet Card */}
      <div className="flex-1 min-h-0 bg-white border border-slate-200/80 rounded-xl p-6 sm:p-7 overflow-y-auto shadow-xs text-slate-800">
        {/* Document Header */}
        <div className="flex items-start justify-between mb-5">
          <div className="text-xl font-bold font-brand text-[#2d1b69]">
            Wenup
          </div>
        </div>

        {/* Title */}
        <h3 className="text-2xl font-serif-title font-bold text-[#2d1b69] mb-1.5 tracking-tight">
          Personal Wishes Document
        </h3>

        <div className="h-px bg-slate-200 mb-6" />

        {/* Section 1: Personal Details */}
        <div className="mb-6">
          <h4 className="text-sm font-serif-title font-bold text-[#1e1b4b] mb-3">
            1. Personal Details
          </h4>
          <div className="grid grid-cols-[110px_1fr] text-xs gap-y-2 text-slate-700">
            <span className="text-slate-500">Full name:</span>
            <span className="font-medium text-slate-900">
              {state.full_name || <span className="text-slate-300 italic">Not yet confirmed</span>}
            </span>

            <span className="text-slate-500">Home address:</span>
            <span className="font-medium text-slate-900">
              {state.home_address || <span className="text-slate-300 italic">Not yet confirmed</span>}
            </span>
          </div>
        </div>

        {/* Section 2: Assets */}
        <div className="mb-6">
          <h4 className="text-sm font-serif-title font-bold text-[#1e1b4b] mb-3">
            2. Assets
          </h4>
          {state.covers_worldwide_assets !== null ? (
            <div className="grid grid-cols-[110px_1fr] text-xs gap-y-2 text-slate-700">
              <span className="text-slate-500">Scope:</span>
              <span className="font-medium text-slate-900">
                {state.covers_worldwide_assets ? 'Covers assets worldwide across all jurisdictions' : 'Restricted to local assets only'}
              </span>
            </div>
          ) : (
            <div className="space-y-2 max-w-sm">
              <div className="h-2.5 bg-slate-100 rounded-full w-full animate-pulse" />
              <div className="h-2.5 bg-slate-100 rounded-full w-4/5 animate-pulse" />
            </div>
          )}
        </div>

        {/* Section 3: Children */}
        <div className="mb-6">
          <h4 className="text-sm font-serif-title font-bold text-[#1e1b4b] mb-3">
            3. Children
          </h4>
          {state.has_children !== null ? (
            <div className="grid grid-cols-[110px_1fr] text-xs gap-y-2 text-slate-700">
              <span className="text-slate-500">Dependents:</span>
              <span className="font-medium text-slate-900">
                {state.has_children
                  ? (((state.children || state.children_names) && (state.children || state.children_names)!.length > 0)
                      ? (state.children || state.children_names)!.join(', ')
                      : 'Yes (names pending)')
                  : 'No children recorded'}
              </span>
            </div>
          ) : (
            <div className="space-y-2 max-w-sm">
              <div className="h-2.5 bg-slate-100 rounded-full w-full animate-pulse" />
              <div className="h-2.5 bg-slate-100 rounded-full w-3/4 animate-pulse" />
            </div>
          )}
        </div>

        {/* Section 4: Executor */}
        {(state.executor.name || state.executor.relationship) ? (
          <div className="mb-6">
            <h4 className="text-sm font-serif-title font-bold text-[#1e1b4b] mb-3">
              4. Appointed Executor
            </h4>
            <div className="grid grid-cols-[110px_1fr] text-xs gap-y-2 text-slate-700">
              <span className="text-slate-500">Name:</span>
              <span className="font-medium text-slate-900">{state.executor.name || 'Pending'}</span>
              <span className="text-slate-500">Relationship:</span>
              <span className="font-medium text-slate-900">{state.executor.relationship || 'Pending'}</span>
            </div>
          </div>
        ) : (
          <div className="mb-6">
            <h4 className="text-sm font-serif-title font-bold text-[#1e1b4b] mb-3">
              4. Appointed Executor
            </h4>
            <div className="space-y-2 max-w-sm">
              <div className="h-2.5 bg-slate-100 rounded-full w-full animate-pulse" />
              <div className="h-2.5 bg-slate-100 rounded-full w-2/3 animate-pulse" />
            </div>
          </div>
        )}

        {/* Section 5: Specific Gifts & Additional Wishes */}
        {(state.specific_gifts !== null || state.additional_wishes !== null) && (
          <div className="mb-4">
            <h4 className="text-sm font-serif-title font-bold text-[#1e1b4b] mb-3">
              5. Gifts & Additional Wishes
            </h4>
            <div className="text-xs space-y-2 text-slate-700">
              <div>
                <span className="text-slate-500">Specific gifts:</span>{' '}
                <span className="font-medium text-slate-900">
                  {state.specific_gifts && state.specific_gifts.length > 0
                    ? state.specific_gifts.join(', ')
                    : state.specific_gifts !== null ? 'None specified' : 'Pending'}
                </span>
              </div>
              <div>
                <span className="text-slate-500">Additional wishes:</span>{' '}
                <span className="font-medium text-slate-900">
                  {state.additional_wishes
                    ? (Array.isArray(state.additional_wishes)
                        ? (state.additional_wishes.length > 0 ? state.additional_wishes.join(', ') : 'None specified')
                        : state.additional_wishes)
                    : (state.additional_wishes !== null ? 'None specified' : 'Pending')}
                </span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* FULL DOCUMENT MODAL */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-fade-in">
          <div className="bg-white w-full max-w-4xl h-[90vh] rounded-2xl shadow-2xl flex flex-col overflow-hidden border border-slate-200">
            {/* Modal Header */}
            <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between bg-slate-50/70 shrink-0">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-xl bg-[#351c75] text-[#ccff00] flex items-center justify-center font-bold">
                  <FileText className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-lg font-serif-title font-bold text-[#1e1b4b]">
                    Personal Wishes Document — Full Formal Draft
                  </h3>
                  <p className="text-xs text-slate-500">
                    Complete transcript and formal declarations prepared from your session.
                  </p>
                </div>
              </div>

              {/* Actions & Close */}
              <div className="flex items-center gap-2">
                <button
                  onClick={handleCopy}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-700 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors shadow-xs"
                >
                  {copied ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />}
                  <span>{copied ? 'Copied!' : 'Copy'}</span>
                </button>

                <button
                  onClick={handlePrint}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-700 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors shadow-xs"
                >
                  <Printer className="w-3.5 h-3.5" />
                  <span>Print / PDF</span>
                </button>

                <button
                  onClick={handleDownload}
                  className="flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold text-slate-900 bg-[#ccff00] hover:bg-[#b8e600] rounded-lg transition-colors shadow-xs"
                >
                  <Download className="w-3.5 h-3.5" />
                  <span>Download .txt</span>
                </button>

                <button
                  onClick={() => setIsModalOpen(false)}
                  className="p-1.5 text-slate-400 hover:text-slate-700 hover:bg-slate-100 rounded-lg transition-colors ml-2"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>

            {/* Modal Body: Parchment Document Sheet */}
            <div className="flex-1 overflow-y-auto p-8 sm:p-12 bg-[#faf9f6]">
              <div className="max-w-2xl mx-auto bg-white p-8 sm:p-12 rounded-xl border border-slate-200/90 shadow-sm text-slate-800 font-serif-body">
                {/* Official Crest Header */}
                <div className="text-center pb-6 border-b border-slate-200 mb-8">
                  <div className="text-xs uppercase tracking-widest text-slate-400 font-semibold mb-1">
                    Private Declaration of Intent
                  </div>
                  <h1 className="text-2xl sm:text-3xl font-serif-title font-bold text-[#2d1b69] tracking-tight">
                    PERSONAL WISHES DOCUMENT
                  </h1>
                  <p className="text-xs text-slate-500 mt-1 italic">
                    Personal Wishes Document &bull; Prepared via Wenup Document Intake
                  </p>
                </div>

                {/* Article I */}
                <div className="mb-6 text-sm leading-relaxed">
                  <h2 className="text-xs uppercase tracking-wider font-bold text-slate-900 mb-2 border-b border-slate-100 pb-1">
                    Article I: Testator Identification
                  </h2>
                  <p className="mb-2">
                    I, <strong className="font-semibold text-slate-950">{state.full_name || '[Full Name Pending]'}</strong>, presently residing at{' '}
                    <strong className="font-semibold text-slate-950">{state.home_address || '[Address Pending]'}</strong>, declare this document to reflect my sincere wishes and directives regarding the administration of my personal affairs and estate.
                  </p>
                </div>

                {/* Article II */}
                <div className="mb-6 text-sm leading-relaxed">
                  <h2 className="text-xs uppercase tracking-wider font-bold text-slate-900 mb-2 border-b border-slate-100 pb-1">
                    Article II: Jurisdiction and Scope of Assets
                  </h2>
                  <p>
                    {state.covers_worldwide_assets === true ? (
                      'The provisions of this document are intended to govern and encompass all property, assets, accounts, and rights held by me worldwide, irrespective of jurisdiction.'
                    ) : state.covers_worldwide_assets === false ? (
                      'The directives expressed herein are limited in scope and apply strictly to my domestic assets and interests situated within my primary residential jurisdiction.'
                    ) : (
                      <span className="text-slate-400 italic">[Territorial coverage scope pending confirmation.]</span>
                    )}
                  </p>
                </div>

                {/* Article III */}
                <div className="mb-6 text-sm leading-relaxed">
                  <h2 className="text-xs uppercase tracking-wider font-bold text-slate-900 mb-2 border-b border-slate-100 pb-1">
                    Article III: Family and Dependent Status
                  </h2>
                  <p>
                    {state.has_children === false ? (
                      'I declare that I have no minor or dependent children at the date of execution hereof, and accordingly no custodial or guardianship appointments are required hereunder.'
                    ) : state.has_children === true ? (
                      <>
                        I declare that I have the following children:{' '}
                        <strong>{(state.children || state.children_names)?.length ? (state.children || state.children_names)!.join(', ') : 'Yes (names recorded)'}</strong>. My Executor shall safeguard their interests in accordance with the provisions herein.
                      </>
                    ) : (
                      <span className="text-slate-400 italic">[Dependent status pending confirmation.]</span>
                    )}
                  </p>
                </div>

                {/* Article IV */}
                <div className="mb-6 text-sm leading-relaxed">
                  <h2 className="text-xs uppercase tracking-wider font-bold text-slate-900 mb-2 border-b border-slate-100 pb-1">
                    Article IV: Appointment of Executor
                  </h2>
                  <p>
                    I hereby appoint <strong className="font-semibold text-slate-950">{state.executor?.name || '[Executor Name Pending]'}</strong>
                    {state.executor?.relationship ? ` (${state.executor.relationship})` : ''} as the sole Executor and personal representative of this document. My Executor is granted full discretionary authority to execute these directives faithfully and without undue hindrance.
                  </p>
                </div>

                {/* Article V */}
                <div className="mb-6 text-sm leading-relaxed">
                  <h2 className="text-xs uppercase tracking-wider font-bold text-slate-900 mb-2 border-b border-slate-100 pb-1">
                    Article V: Specific Gifts and Bequests
                  </h2>
                  {state.specific_gifts && state.specific_gifts.length > 0 ? (
                    <ul className="list-disc pl-5 space-y-1.5 text-slate-800">
                      {state.specific_gifts.map((item, idx) => (
                        <li key={idx}><strong>{item}</strong></li>
                      ))}
                    </ul>
                  ) : state.specific_gifts !== null ? (
                    <p className="text-slate-700">
                      I make no specific bequests of personal chattels or financial gifts at this time; all personal effects shall fall into the general estate.
                    </p>
                  ) : (
                    <p className="text-slate-400 italic">[Specific gifts pending confirmation.]</p>
                  )}
                </div>

                {/* Article VI */}
                <div className="mb-6 text-sm leading-relaxed">
                  <h2 className="text-xs uppercase tracking-wider font-bold text-slate-900 mb-2 border-b border-slate-100 pb-1">
                    Article VI: Residuary Estate & Special Wishes
                  </h2>
                  {state.additional_wishes ? (
                    (() => {
                      const wishes = Array.isArray(state.additional_wishes) ? state.additional_wishes : [state.additional_wishes];
                      const hasContent = wishes.length > 0 && wishes.some(w => w && w.trim());
                      return hasContent ? (
                        <div className="p-3.5 bg-slate-50 rounded-lg border border-slate-200/80 text-slate-800 space-y-2">
                          {wishes.filter(w => w && w.trim()).map((wish, idx) => (
                            <p key={idx} className="italic">
                              &ldquo;{wish}&rdquo;
                            </p>
                          ))}
                        </div>
                      ) : (
                        <p className="text-slate-700">No additional special wishes or directives were recorded.</p>
                      );
                    })()
                  ) : state.additional_wishes !== null ? (
                    <p className="text-slate-700">No additional special wishes or directives were recorded.</p>
                  ) : (
                    <p className="text-slate-400 italic">[Additional wishes pending confirmation.]</p>
                  )}
                </div>

                {/* Article VII: Execution Block */}
                <div className="mt-10 pt-6 border-t border-slate-300 text-xs leading-relaxed text-slate-700">
                  <h2 className="text-xs uppercase tracking-wider font-bold text-slate-900 mb-4">
                    Article VII: Attestation and Execution
                  </h2>
                  <p className="mb-6">
                    IN WITNESS WHEREOF, I have subscribed my name to this Personal Wishes Document on this{' '}
                    {new Date().toLocaleDateString('en-US', { day: 'numeric', month: 'long', year: 'numeric' })}.
                  </p>

                  {/* Signatures */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-8 mb-8">
                    <div>
                      <div className="border-b border-slate-400 h-8 mb-1.5" />
                      <div className="text-slate-500 font-medium">Signature of Testator</div>
                      <div className="font-semibold text-slate-900">{state.full_name || 'Testator'}</div>
                    </div>
                    <div>
                      <div className="border-b border-slate-400 h-8 mb-1.5" />
                      <div className="text-slate-500 font-medium">Date</div>
                      <div className="font-semibold text-slate-900">{new Date().toLocaleDateString()}</div>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-8 pt-4 border-t border-slate-200">
                    <div>
                      <div className="border-b border-slate-400 h-8 mb-1.5" />
                      <div className="text-slate-500 font-medium">Signature of Witness 1</div>
                      <div className="text-slate-400">Name & Address</div>
                    </div>
                    <div>
                      <div className="border-b border-slate-400 h-8 mb-1.5" />
                      <div className="text-slate-500 font-medium">Signature of Witness 2</div>
                      <div className="text-slate-400">Name & Address</div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
