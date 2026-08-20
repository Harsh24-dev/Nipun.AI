import React, { useState, useEffect, useRef, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import { Settings, FileText, Wrench, Zap, Loader2, Pencil, Check } from "lucide-react";
import WorkspaceSidebar from "@/components/workspace/WorkspaceSidebar";
import Composer from "@/components/workspace/Composer";
import RightRail from "@/components/workspace/RightRail";
import ResponseCardRenderer from "@/components/workspace/ResponseCardRenderer";
import ThinkingIndicator from "@/components/workspace/ThinkingIndicator";
import { useApp } from "@/lib/AppContext";
import { sessions as sessionsApi, query as queryApi } from "@/lib/api";
import { parseResponseCard } from "@/lib/parseCard";
import { createWebSocket } from "@/lib/api";
import NipunLogo from "@/components/nipun/NipunLogo";

export default function Workspace() {
  const { sessionId: urlSessionId } = useParams();
  const navigate = useNavigate();
  const { token, user, profile, activeSessionId, setActiveSessionId } = useApp();

  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [streamText, setStreamText] = useState("");
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [rightRailOpen, setRightRailOpen] = useState(false);
  const [rightRailTab, setRightRailTab] = useState("documents");
  const [sessionTitle, setSessionTitle] = useState("New conversation");
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleVal, setTitleVal] = useState("");
  const [documentScope, setDocumentScope] = useState(null);

  const messagesEndRef = useRef(null);
  const wsRef = useRef(null);
  const currentSessionId = urlSessionId || activeSessionId;

  // Load session messages
  useEffect(() => {
    if (currentSessionId) {
      loadSession(currentSessionId);
    } else {
      setMessages([]);
      setSessionTitle("New conversation");
    }
    return () => { if (wsRef.current) wsRef.current.close(); };
  }, [currentSessionId]);

  // Scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, thinking, streamText]);

  const loadSession = async (id) => {
    setSessionsLoading(true);
    try {
      const [meta, msgs] = await Promise.all([
        sessionsApi.get(id),
        sessionsApi.getMessages(id),
      ]);
      setSessionTitle(meta?.title || "Conversation");
      // Assistant content is stored as a JSON-serialized ResponseCard (see backend
      // conversation_store.persist_turn). Parse it back so rich cards (steps, schemes,
      // sources) survive a reload; fall back to a plain answer card for legacy/plain text.
      const toCard = (raw) => {
        let data = raw;
        if (typeof raw === "string") {
          try { data = JSON.parse(raw); } catch { data = { cardType: "answer", summary: raw }; }
        }
        return parseResponseCard(data);
      };
      const parsed = (Array.isArray(msgs) ? msgs : []).map(m => ({
        role: m.role,
        content: m.content,
        created_at: m.created_at,
        card: m.role === "assistant" ? toCard(m.content) : null,
      }));
      setMessages(parsed);
    } catch (err) {
      // A brand-new session (first turn just navigated here) has no persisted history
      // yet, or the read failed — don't wipe whatever is already on screen.
      if (err?.status === 404) setSessionTitle("New conversation");
    }
    setSessionsLoading(false);
  };

  const handleSend = useCallback(async (text) => {
    if (!text.trim()) return;

    // Add user message
    setMessages(prev => [...prev, { role: "user", content: text }]);
    setLoading(true);
    setThinking(true);
    setStreamText("");

    try {
      // Try WebSocket first if we have a session
      if (currentSessionId && token) {
        try {
          await sendViaWebSocket(text, currentSessionId);
          return;
        } catch {}
      }

      // REST fallback
      const body = { query: text };
      if (currentSessionId) body.session_id = currentSessionId;
      if (documentScope) body.document_id = documentScope.id;

      const res = await queryApi.send(body);

      if (res?.session_id && !currentSessionId) {
        setActiveSessionId(res.session_id);
        navigate(`/workspace/${res.session_id}`, { replace: true });
      }

      if (res?.response_card) {
        const card = parseResponseCard(res.response_card);
        setMessages(prev => [...prev, { role: "assistant", content: res.response_card, card }]);
      }
    } catch (err) {
      const errorCard = parseResponseCard({ cardType: "error", summary: err.message || "Failed to get response" });
      setMessages(prev => [...prev, { role: "assistant", content: {}, card: errorCard }]);
    } finally {
      setLoading(false);
      setThinking(false);
      setStreamText("");
    }
  }, [currentSessionId, token, documentScope]);

  // Answers to a `clarify` form come back here. The backend contract (see
  // agents/clarify.py + QueryRequest.clarifications) is: RESEND the original query
  // together with {field_name: value} in `clarifications` — it's folded into that
  // one turn's context, not stored. This must use the REST /query path because the
  // WebSocket stream endpoint doesn't accept the clarifications field.
  const handleSubmitClarification = useCallback(async (originalQuery, values) => {
    if (!originalQuery) return;
    const answered = values && Object.keys(values).length > 0;

    // Echo the user's choice as a message bubble so the turn reads naturally.
    const bubble = answered
      ? Object.values(values)
          .map(v => (Array.isArray(v) ? v.join(", ") : v))
          .filter(v => v !== "" && v != null)
          .join(" · ")
      : "Skip — get a general answer";
    setMessages(prev => [...prev, { role: "user", content: bubble }]);
    setLoading(true);
    setThinking(true);

    try {
      const body = { query: originalQuery, clarifications: answered ? values : {} };
      if (currentSessionId) body.session_id = currentSessionId;
      if (documentScope) body.document_id = documentScope.id;

      const res = await queryApi.send(body);

      if (res?.session_id && !currentSessionId) {
        setActiveSessionId(res.session_id);
        navigate(`/workspace/${res.session_id}`, { replace: true });
      }
      if (res?.response_card) {
        const card = parseResponseCard(res.response_card);
        setMessages(prev => [...prev, { role: "assistant", content: res.response_card, card }]);
      }
    } catch (err) {
      const errorCard = parseResponseCard({ cardType: "error", summary: err.message || "Failed to get response" });
      setMessages(prev => [...prev, { role: "assistant", content: {}, card: errorCard }]);
    } finally {
      setLoading(false);
      setThinking(false);
    }
  }, [currentSessionId, documentScope, navigate, setActiveSessionId]);

  const sendViaWebSocket = (text, sid) => {
    return new Promise((resolve, reject) => {
      const ws = createWebSocket(sid);
      wsRef.current = ws;
      // Whether we've received a terminal frame (done/error) or at least a rendered card.
      // If the socket closes without any delivery, the Promise must still settle (below) so
      // the caller's REST fallback / finally runs and the turn never silently hangs.
      let gotTerminal = false;
      let gotCard = false;

      ws.onopen = () => {
        ws.send(JSON.stringify({ token }));
        ws.send(JSON.stringify({ query: text }));
      };

      ws.onmessage = (event) => {
        // A malformed frame must not throw uncaught and kill the message loop — guard the
        // parse (mirrors the guarded parse in the task runner) and ignore bad frames.
        let data;
        try {
          data = JSON.parse(event.data);
        } catch (err) {
          console.error("WebSocket: could not parse frame, ignoring", err);
          return;
        }
        try {
          if (data.type === "thinking") {
            setThinking(true);
          } else if (data.type === "token") {
            // Your spec uses "content" for token chunks
            setThinking(false);
            setStreamText(prev => prev + (data.content || data.text || ""));
          } else if (data.type === "card") {
            // Your spec uses "data" for the ResponseCard object
            setThinking(false);
            setStreamText("");
            const cardData = data.data || data.card || data;
            const card = parseResponseCard(cardData);
            gotCard = true;
            setMessages(prev => [...prev, { role: "assistant", content: cardData, card }]);
          } else if (data.type === "card_patch") {
            // The answer streamed first; this carries the deferred sources/reliability/citations.
            // Merge it into the LAST assistant card IN PLACE so the card upgrades smoothly without
            // a re-render or losing the already-shown answer.
            const patch = data.data || {};
            setMessages(prev => {
              const next = [...prev];
              for (let i = next.length - 1; i >= 0; i--) {
                if (next[i].role === "assistant" && next[i].content) {
                  const mergedRaw = { ...next[i].content, ...patch };
                  next[i] = { ...next[i], content: mergedRaw, card: parseResponseCard(mergedRaw) };
                  break;
                }
              }
              return next;
            });
          } else if (data.type === "done") {
            gotTerminal = true;
            setLoading(false);
            setThinking(false);
            ws.close();
            resolve();
          } else if (data.type === "error") {
            gotTerminal = true;
            const errorCard = parseResponseCard({ cardType: "error", summary: data.message || "Stream error" });
            setMessages(prev => [...prev, { role: "assistant", content: {}, card: errorCard }]);
            setLoading(false);
            setThinking(false);
            ws.close();
            resolve();
          }
        } catch (err) {
          console.error("WebSocket: error handling frame", err);
        }
      };

      ws.onerror = () => { if (!gotTerminal && !gotCard) reject(new Error("WebSocket failed")); };
      ws.onclose = () => {
        setLoading(false);
        setThinking(false);
        // Socket closed without a done/error frame — settle so the caller doesn't hang
        // forever. If a card already arrived, treat the turn as delivered (resolve) to avoid
        // a duplicate REST request; otherwise reject to trigger the REST fallback.
        if (gotTerminal) return;
        if (gotCard) resolve();
        else reject(new Error("WebSocket closed before completion"));
      };
    });
  };

  const handleRenameTitle = async () => {
    if (titleVal.trim() && currentSessionId) {
      try {
        await sessionsApi.update(currentSessionId, { title: titleVal });
        setSessionTitle(titleVal);
      } catch {}
    }
    setEditingTitle(false);
  };

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e) => {
      if (e.key === "n" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setActiveSessionId(null);
        navigate("/workspace");
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  return (
    <div className="h-screen flex" style={{ background: "var(--background)" }}>
      <WorkspaceSidebar collapsed={sidebarCollapsed} onToggle={() => setSidebarCollapsed(!sidebarCollapsed)} />

      <div className="flex-1 flex flex-col min-w-0">
        <div className="flex items-center justify-between px-4 py-2 border-b" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
          <div className="flex items-center gap-3 min-w-0">
            <NipunLogo size="sm" />
            <span className="text-xs px-1" style={{ color: "var(--border)" }}>|</span>
            {editingTitle ? (
              <div className="flex items-center gap-1">
                <input value={titleVal} onChange={e => setTitleVal(e.target.value)}
                  onBlur={handleRenameTitle} onKeyDown={e => e.key === "Enter" && handleRenameTitle()}
                  className="text-sm bg-transparent border-b outline-none" style={{ borderColor: "var(--accent)", color: "var(--text)" }}
                  autoFocus />
                <button onClick={handleRenameTitle} className="p-1" style={{ color: "var(--accent)" }}><Check size={12} /></button>
              </div>
            ) : (
              <button onClick={() => { setEditingTitle(true); setTitleVal(sessionTitle); }}
                className="text-sm truncate max-w-[300px] flex items-center gap-1 hover:opacity-80"
                style={{ color: "var(--text)" }}>
                {sessionTitle} <Pencil size={10} style={{ color: "var(--text-muted)" }} />
              </button>
            )}
          </div>
          <div className="flex items-center gap-1">
            <button onClick={() => { setRightRailTab("documents"); setRightRailOpen(!rightRailOpen); }}
              className="p-2 rounded-lg hover:opacity-80" style={{ color: "var(--text-muted)" }} aria-label="Documents">
              <FileText size={16} />
            </button>
            <button onClick={() => { setRightRailTab("tools"); setRightRailOpen(!rightRailOpen); }}
              className="p-2 rounded-lg hover:opacity-80" style={{ color: "var(--text-muted)" }} aria-label="Tools">
              <Wrench size={16} />
            </button>
            <button onClick={() => { setRightRailTab("tasks"); setRightRailOpen(!rightRailOpen); }}
              className="p-2 rounded-lg hover:opacity-80" style={{ color: "var(--text-muted)" }} aria-label="Tasks">
              <Zap size={16} />
            </button>
            <button onClick={() => navigate("/settings")} className="p-2 rounded-lg hover:opacity-80" style={{ color: "var(--text-muted)" }} aria-label="Settings">
              <Settings size={16} />
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          <div className="max-w-3xl mx-auto px-4 py-6 space-y-4">
            {sessionsLoading ? (
              <div className="flex justify-center py-12">
                <Loader2 size={24} className="animate-spin" style={{ color: "var(--text-muted)" }} />
              </div>
            ) : messages.length === 0 && !thinking ? (
              <div className="flex flex-col items-center justify-center py-20">
                <NipunLogo size="lg" className="opacity-20 mb-4" />
                <p className="text-sm" style={{ color: "var(--text-muted)" }}>Start a conversation</p>
              </div>
            ) : (
              messages.map((m, i) => (
                <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                  <div className={`max-w-[85%] ${m.role === "user" ? "text-right" : ""}`}>
                    {m.role === "user" ? (
                      <div className="inline-block px-4 py-3 rounded-2xl rounded-br-sm text-sm"
                        style={{ background: "var(--accent)", color: "var(--accent-text)" }}>
                        {typeof m.content === "string" ? m.content : JSON.stringify(m.content)}
                      </div>
                    ) : m.card ? (
                      <div className="p-4 rounded-2xl rounded-bl-sm border" style={{ background: "var(--surface)", borderColor: "var(--border)" }}>
                        <ResponseCardRenderer
                          card={m.card}
                          onSendQuery={handleSend}
                          onSubmitClarification={(values) => {
                            // Resend the original under-specified query — the nearest
                            // preceding user message — with the collected answers.
                            const prevUser = messages.slice(0, i).reverse().find(x => x.role === "user");
                            handleSubmitClarification(
                              typeof prevUser?.content === "string" ? prevUser.content : "",
                              values,
                            );
                          }}
                        />
                      </div>
                    ) : null}
                  </div>
                </div>
              ))
            )}

            {thinking && <ThinkingIndicator />}

            {streamText && !thinking && (
              <div className="flex justify-start">
                <div className="p-4 rounded-2xl rounded-bl-sm border max-w-[85%]" style={{ background: "var(--surface)", borderColor: "var(--border)" }}>
                  {/* Same Markdown rendering as the final AnswerCard, so the streamed
                      answer types out looking exactly like the card it solidifies into. */}
                  <div className="prose prose-sm max-w-none text-sm" style={{ color: "var(--text)" }}>
                    <ReactMarkdown>{streamText}</ReactMarkdown>
                  </div>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        </div>

        <Composer onSend={handleSend} loading={loading} documentScope={documentScope} onClearDocScope={() => setDocumentScope(null)} />
      </div>

      <RightRail open={rightRailOpen} onClose={() => setRightRailOpen(false)} activeTab={rightRailTab} sessionId={currentSessionId} />
    </div>
  );
}