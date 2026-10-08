import React from 'react';
import { Check, User, Home, Globe, Users, Gift, FileText, Shield, ChevronRight } from 'lucide-react';
import type { DocumentState } from '../types';

interface DetailsTrackerProps {
  state: DocumentState;
}

export const DetailsTracker: React.FC<DetailsTrackerProps> = ({ state }) => {
  const steps = [
    {
      id: 'full_name',
      label: 'Full name',
      icon: User,
      value: state.full_name,
      isDone: Boolean(state.full_name),
    },
    {
      id: 'home_address',
      label: 'Home address',
      icon: Home,
      value: state.home_address,
      isDone: Boolean(state.home_address),
    },
    {
      id: 'worldwide',
      label: 'Worldwide assets',
      icon: Globe,
      value: state.covers_worldwide_assets === null ? null : (state.covers_worldwide_assets ? 'Worldwide' : 'Local only'),
      isDone: state.covers_worldwide_assets !== null,
    },
    {
      id: 'children',
      label: 'Children',
      icon: Users,
      value: state.has_children === null ? null : (state.has_children ? `${((state.children || state.children_names) || []).length || 1} recorded` : 'No children'),
      isDone: state.has_children !== null,
    },
    {
      id: 'executor',
      label: 'Executor',
      icon: Shield,
      value: state.executor.name ? `${state.executor.name} (${state.executor.relationship || 'Exec'})` : null,
      isDone: Boolean(state.executor.name),
    },
    {
      id: 'gifts',
      label: 'Specific gifts',
      icon: Gift,
      value: state.specific_gifts && state.specific_gifts.length > 0 ? `${state.specific_gifts.length} items` : (state.specific_gifts !== null ? 'None' : null),
      isDone: state.specific_gifts !== null,
    },
    {
      id: 'wishes',
      label: 'Additional wishes',
      icon: FileText,
      value: state.additional_wishes
        ? (Array.isArray(state.additional_wishes)
            ? (state.additional_wishes.length > 0 ? `${state.additional_wishes.length} items` : 'None')
            : 'Recorded')
        : (state.additional_wishes !== null ? 'None' : null),
      isDone: state.additional_wishes !== null,
    },
  ];

  const completedCount = steps.filter(s => s.isDone).length;
  const totalCount = steps.length;
  const progressPercent = Math.round((completedCount / totalCount) * 100);

  return (
    <div className="bg-white rounded-2xl border border-slate-100 p-6 shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-serif-title font-semibold text-[#1e1b4b]">
          Your details
        </h2>
      </div>

      {/* Progress Bar */}
      <div className="mb-6">
        <div className="flex items-center justify-between text-xs text-slate-500 font-medium mb-2">
          <div className="w-full bg-slate-100 h-2 rounded-full overflow-hidden mr-4">
            <div
              className="h-full bg-[#ccff00] transition-all duration-500 rounded-full"
              style={{ width: `${Math.max(progressPercent, 8)}%` }}
            />
          </div>
          <span className="shrink-0 text-slate-600 font-semibold">{completedCount} of {totalCount} completed</span>
        </div>
      </div>

      {/* Horizontal Steps Cards List */}
      <div className="relative flex items-center">
        <div className="flex items-center gap-4 overflow-x-auto pb-1 w-full no-scrollbar">
          {steps.map(step => {
            const Icon = step.icon;
            return (
              <div
                key={step.id}
                className="flex items-center gap-3 min-w-[170px] max-w-[210px] p-2 rounded-xl transition-all"
              >
                {/* Status Indicator circle / checkmark */}
                <div className="shrink-0">
                  {step.isDone ? (
                    <div className="w-5 h-5 rounded-full bg-[#a3e635] flex items-center justify-center text-slate-900 shadow-xs">
                      <Check className="w-3.5 h-3.5 stroke-[3]" />
                    </div>
                  ) : (
                    <div className="w-5 h-5 rounded-full border-2 border-slate-200 flex items-center justify-center" />
                  )}
                </div>

                {/* Icon */}
                <div className="text-slate-500 shrink-0">
                  <Icon className="w-4 h-4" />
                </div>

                {/* Text Labels */}
                <div className="min-w-0">
                  <div className="text-xs font-medium text-slate-700 truncate">
                    {step.label}
                  </div>
                  <div className="text-[11px] text-slate-500 truncate">
                    {step.value ? (
                      <span className="text-slate-900 font-medium">{step.value}</span>
                    ) : (
                      <span className="text-slate-400">Not specified</span>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {/* Scroll forward chevron button */}
        <button className="shrink-0 ml-2 w-8 h-8 rounded-full border border-slate-200 bg-white hover:bg-slate-50 flex items-center justify-center text-slate-500 shadow-xs transition-colors">
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
};
