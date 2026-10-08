import React, { useState, useEffect, useRef } from 'react';
import { Header } from './components/Header';
import { ChatPanel } from './components/ChatPanel';
import { DocumentPreview } from './components/DocumentPreview';
import { DetailsTracker } from './components/DetailsTracker';
import type { DocumentState, ChatMessage, ChoiceOption } from './types';

const EMPTY_STATE: DocumentState = {
  full_name: null,
  home_address: null,
  covers_worldwide_assets: null,
  has_children: null,
  children: null,
  children_names: null,
  executor: { name: null, relationship: null },
  specific_gifts: null,
  additional_wishes: null,
};

export const App: React.FC = () => {
  const [state, setState] = useState<DocumentState>(EMPTY_STATE);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rateLimitSeconds, setRateLimitSeconds] = useState(0);
  const [progress, setProgress] = useState({ completed: 0, total: 9, label: '0 of 9 completed', percentage: 0 });
  const sending = useRef(false);

  useEffect(() => {
    if (!rateLimitSeconds) return;
    const timer = window.setTimeout(() => setRateLimitSeconds((seconds) => Math.max(0, seconds - 1)), 1000);
    return () => window.clearTimeout(timer);
  }, [rateLimitSeconds]);

  // On mount: fetch initial greeting from backend
  useEffect(() => {
    fetch('/api/initial')
      .then((r) => {
        if (!r.ok) throw new Error(`Backend returned ${r.status}`);
        return r.json();
      })
      .then((data) => {
        const now = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        setMessages([
          {
            id: '1',
            role: 'assistant',
            content: data.assistant_message || "Hi! I'm your document assistant. Let's get started — what is your full name?",
            timestamp: now,
            options: data.options,
          },
        ]);
        // Always ensure state is initialized
        if (data.state) {
          setState(data.state);
        } else {
          setState(EMPTY_STATE);
        }
        if (data.progress) setProgress(data.progress);
      })
      .catch(() => {
        setError('Could not connect to the assistant backend. Start app.py, then reload this page.');
        // Initialize with empty state even on error
        setState(EMPTY_STATE);
      })
      .finally(() => setIsLoading(false));
  }, []);


  const handleSendMessage = async (text: string) => {
    if (sending.current || rateLimitSeconds > 0) return;
    sending.current = true;

    const userTime = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const newMsg: ChatMessage = {
      id: Date.now().toString(),
      role: 'user',
      content: text,
      timestamp: userTime,
    };

    const lastMessage = messages[messages.length - 1];
    const retryingSameMessage = Boolean(error && lastMessage?.role === 'user' && lastMessage.content === text);
    const updatedMessages = (retryingSameMessage ? messages : [...messages, newMsg]).filter((message, index, all) =>
      !(message.role === 'user' && index > 0 && all[index - 1].role === 'user' && all[index - 1].content === message.content)
    );
    setMessages(updatedMessages);
    setIsLoading(true);
    setError(null);
    
    // Safety check: ensure state exists to prevent rendering issues
    if (!state) {
      setState(EMPTY_STATE);
    }

    try {
      const questionJustAsked = [...updatedMessages].reverse().find((message) => message.role === 'assistant')?.content || '';
      const sessionId = state._meta?.session_id;
      if (!sessionId) {
        throw new Error('Session ID not found. Please refresh the page.');
      }
      // 1. Call Backend API
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          session_id: sessionId,
          question_just_asked: questionJustAsked,
          messages: updatedMessages.map(({ role, content }) => ({ role, content })),
          state: state,
        }),
      });

      if (res.ok) {
        const data = await res.json();
        const now = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        const nextMessage: ChatMessage = {
          id: (Date.now() + 1).toString(),
          role: 'assistant',
          content: data.assistant_message || 'I could not generate a reply.',
          timestamp: now,
          options: data.options,
        };
        setMessages((prev) => [...prev, nextMessage]);
        // Always ensure state is set, use EMPTY_STATE as fallback
        if (data.state) {
          setState(data.state);
        } else {
          setState((prevState) => prevState || EMPTY_STATE);
        }
        if (data.progress) setProgress(data.progress);
      } else {
        const data = await res.json().catch(() => ({}));
        if (data.state) setState(data.state);
        if (data.progress) setProgress(data.progress);
        if (res.status === 429) setRateLimitSeconds(Number(data.retry_after) || 30);
        throw new Error(data.error || `Backend returned ${res.status}`);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unable to reach the backend.';
      setError(message);
    } finally {
      sending.current = false;
      setIsLoading(false);
    }
  };

  const handleSelectOption = async (option: ChoiceOption) => {
    const sessionId = state._meta?.session_id;
    if (!sessionId || sending.current) return;
    sending.current = true;
    setIsLoading(true);
    setError(null);
    const now = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    setMessages((previous) => [...previous, { id: Date.now().toString(), role: 'user', content: option.label, timestamp: now }]);
    try {
      const res = await fetch('/api/choice', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, field: option.field, value: option.value }),
      });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'Unable to save that choice.');
      const data = await res.json();
      setMessages((previous) => [...previous, { id: (Date.now() + 1).toString(), role: 'assistant', content: data.assistant_message, timestamp: now, options: data.options }]);
      // Always ensure state is set
      if (data.state) {
        setState(data.state);
      } else {
        setState((prevState) => prevState || EMPTY_STATE);
      }
      if (data.progress) setProgress(data.progress);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to save that choice.');
    } finally {
      sending.current = false;
      setIsLoading(false);
    }
  };

  return (
    <div className="h-screen w-screen bg-[#fafafc] flex flex-col overflow-hidden">
      {/* Top Header */}
      <Header state={state || EMPTY_STATE} progress={progress} />

      {/* Main 2-Column Split Dashboard */}
      <main className="flex-1 min-h-0 max-w-[1720px] w-full mx-auto p-5 grid grid-cols-1 lg:grid-cols-2 gap-5 overflow-hidden">
        {/* Left: Chat (internal scroll) */}
        <section className="h-full min-h-0 overflow-hidden">
          {error && (
            <div className="mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}{rateLimitSeconds > 0 && <span> Retry in {Math.floor(rateLimitSeconds / 60)}m {rateLimitSeconds % 60}s.</span>}
            </div>
          )}
          <ChatPanel
            messages={messages}
            onSendMessage={handleSendMessage}
            onSelectOption={handleSelectOption}
            isLoading={isLoading}
            sendBlocked={rateLimitSeconds > 0}
          />
        </section>

        {/* Right: Document Preview + Details Tracker */}
        <section className="h-full min-h-0 flex flex-col gap-5 overflow-hidden">
          <div className="flex-1 min-h-0 overflow-hidden">
            <DocumentPreview state={state || EMPTY_STATE} progress={progress} />
          </div>
          <div className="shrink-0">
            <DetailsTracker state={state || EMPTY_STATE} />
          </div>
        </section>
      </main>
    </div>
  );
};

export default App;
