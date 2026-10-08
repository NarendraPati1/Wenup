import React, { useState, useRef, useEffect } from 'react';
import { ArrowUp, ChevronLeft } from 'lucide-react';
import type { ChatMessage, ChoiceOption } from '../types';

interface ChatPanelProps {
  messages: ChatMessage[];
  onSendMessage: (text: string) => void;
  onSelectOption: (option: ChoiceOption) => void;
  isLoading?: boolean;
  sendBlocked?: boolean;
}

function renderMessage(text: string): React.ReactNode {
  return text.split(/(\*\*[^*]+\*\*|__[^_]+__|`[^`]+`)/g).map((part, index) => {
    if ((part.startsWith('**') && part.endsWith('**')) || (part.startsWith('__') && part.endsWith('__'))) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith('`') && part.endsWith('`')) {
      return <code key={index} className="rounded bg-white/70 px-1">{part.slice(1, -1)}</code>;
    }
    return <React.Fragment key={index}>{part}</React.Fragment>;
  });
}

export const ChatPanel: React.FC<ChatPanelProps> = ({ messages, onSendMessage, onSelectOption, isLoading, sendBlocked }) => {
  const [inputValue, setInputValue] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const sendDisabled = Boolean(isLoading || sendBlocked);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  useEffect(() => {
    if (!isLoading && !sendBlocked) inputRef.current?.focus();
  }, [isLoading, sendBlocked]);

  const handleSend = () => {
    const trimmed = inputValue.trim();
    if (!trimmed || isLoading) return;
    onSendMessage(trimmed);
    setInputValue('');
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex flex-col h-full bg-[#fdfcff] rounded-2xl border border-slate-100/80 p-5 shadow-sm overflow-hidden">
      {/* Messages Scroll Area - Restricted with internal scroll */}
      <div className="flex-1 min-h-0 overflow-y-auto space-y-5 pr-2 mb-3">
        {messages.map((msg) => {
          if (msg.role === 'assistant') {
            return (
              <div key={msg.id} className="flex items-start gap-3.5 max-w-[92%]">
                {/* W Avatar */}
                <div className="w-8 h-8 rounded-full bg-[#351c75] text-white flex items-center justify-center font-brand font-bold text-sm shrink-0 shadow-xs mt-0.5">
                  W
                </div>

                <div className="flex flex-col space-y-2">
                  {/* Main Bubble */}
                  <div className="bg-[#f6f3fe] border border-[#ebe5fa] text-[#1e1b4b] text-sm leading-relaxed p-4 rounded-2xl rounded-tl-sm shadow-xs whitespace-pre-line">
                    {renderMessage(msg.content)}
                  </div>

                  {/* Optional Sub-bubble Question */}
                  {msg.subContent && (
                    <div className="bg-[#f6f3fe] border border-[#ebe5fa] text-[#1e1b4b] text-sm font-medium leading-relaxed px-4 py-3 rounded-2xl shadow-xs">
                      {msg.subContent}
                    </div>
                  )}

                  {/* Interactive Option Pills */}
                  {msg.options && msg.options.length > 0 && (
                    <div className="flex flex-wrap gap-2.5 pt-1">
                      {msg.options.map((opt, idx) => {
                        const isPrimary = idx === 0;
                        return (
                          <button
                            key={opt.label}
                            onClick={() => onSelectOption(opt)}
                            disabled={sendDisabled}
                            className={`px-4 py-2 text-xs font-semibold rounded-xl transition-all shadow-xs ${
                              isPrimary
                                ? 'bg-[#ccff00] hover:bg-[#b8e600] text-slate-900'
                                : 'bg-white hover:bg-slate-50 text-slate-800 border border-slate-200'
                            } disabled:opacity-50 disabled:cursor-not-allowed`}
                          >
                            {opt.label}
                          </button>
                        );
                      })}
                    </div>
                  )}

                  {/* Timestamp */}
                  <span className="text-[11px] text-slate-400 pl-1">
                    {msg.timestamp}
                  </span>
                </div>
              </div>
            );
          } else {
            return (
              <div key={msg.id} className="flex flex-col items-end space-y-1">
                {/* User Bubble */}
                <div className="bg-[#edeaf8] text-slate-800 text-sm font-medium px-4 py-2.5 rounded-2xl rounded-tr-sm shadow-xs max-w-[80%]">
                  {msg.content}
                </div>
                <span className="text-[11px] text-slate-400 pr-1">
                  {msg.timestamp}
                </span>
              </div>
            );
          }
        })}

        {isLoading && (
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-[#351c75] text-white flex items-center justify-center font-brand font-bold text-sm shrink-0">
              W
            </div>
            <div className="bg-[#f6f3fe] border border-[#ebe5fa] text-slate-500 text-xs px-4 py-3 rounded-2xl flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-[#351c75] animate-bounce" />
              <span className="w-1.5 h-1.5 rounded-full bg-[#351c75] animate-bounce [animation-delay:0.2s]" />
              <span className="w-1.5 h-1.5 rounded-full bg-[#351c75] animate-bounce [animation-delay:0.4s]" />
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Fixed Bottom Input Area */}
      <div className="shrink-0 space-y-2.5 pt-2 border-t border-slate-100/60">
        {/* Rounded Input Container with Arrow Send Button */}
        <div className="relative flex items-center">
          <input
            type="text"
            ref={inputRef}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type your answer here..."
            disabled={sendDisabled}
            className="w-full bg-white border border-slate-200 hover:border-slate-300 focus:border-[#4f2db6] focus:outline-none rounded-full py-3 pl-5 pr-14 text-sm text-slate-800 placeholder-slate-400 shadow-xs transition-colors"
          />

          <button
            onClick={handleSend}
            disabled={!inputValue.trim() || sendDisabled}
            className="absolute right-1.5 top-1/2 -translate-y-1/2 w-8 h-8 rounded-full bg-[#ccff00] hover:bg-[#b8e600] disabled:bg-slate-100 disabled:text-slate-300 text-slate-900 flex items-center justify-center shadow-xs transition-all"
          >
            <ArrowUp className="w-4 h-4 stroke-[2.5]" />
          </button>
        </div>

        {/* Bottom Helper Action Buttons */}
        <div className="flex items-center gap-2 text-xs">
          <button
            onClick={() => onSendMessage("Go back to previous question")}
            disabled={sendDisabled}
            className="flex items-center gap-1 px-3 py-1 bg-white hover:bg-slate-50 border border-slate-200 text-slate-600 rounded-lg transition-colors shadow-xs disabled:opacity-50"
          >
            <ChevronLeft className="w-3.5 h-3.5 text-slate-400" />
            <span>Go back</span>
          </button>
        </div>
      </div>
    </div>
  );
};
