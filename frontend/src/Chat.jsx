import { useEffect, useRef, useState } from "react";
import { Bot, KeyRound, LoaderCircle, Send, ShieldCheck, Trash2, UserRound } from "lucide-react";
import "./Chat.css";

const AGENT_API_BASE = import.meta.env.VITE_AGENT_API_BASE || "http://127.0.0.1:8300";

const SUGGESTIONS = [
  "Check inventory for SKU ABC",
  "List the latest WooCommerce orders",
  "What store tools can I use?",
];

export default function Chat() {
  const [apiKey, setApiKey] = useState("");
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState([
    { role: "assistant", content: "Hi! I can help with the read-only WooCommerce and inventory tools available to your API key. What would you like to check?" },
  ]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const endRef = useRef(null);
  const inputRef = useRef(null);

  
    useEffect(() => {
  endRef.current?.scrollIntoView({ behavior: "smooth" });
}, [messages, busy]);


  async function sendMessage(text = draft) {
    const content = text.trim();
    if (!content || busy) return;
    if (!apiKey.trim()) {
      setError("Enter your member MCP API key to connect securely to the Gateway.");
      return;
    }
    const next = [...messages, { role: "user", content }];
    setMessages(next);
    setDraft("");
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`${AGENT_API_BASE}/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-MCP-API-Key": apiKey.trim(),
        },
        body: JSON.stringify({ messages: next.filter((m) => m.role === "user" || m.role === "assistant").slice(-20) }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `Chat request failed (${response.status}).`);
      const assistant = {
        role: "assistant",
        content: data.reply || "No response returned.",
        tools_used: data.tools_used || [],
      };
      setMessages((current) => [...current, assistant]);
    } catch (e) {
      setError(e.message || "Could not reach the chat agent.");
    } finally {
      setBusy(false);
      inputRef.current?.focus();
    }
  }

  function clearChat() {
    setMessages([{ role: "assistant", content: "Chat cleared. What would you like to check?" }]);
    setError("");
  }

  return (
    <section className="agent-page">
      <div className="agent-heading">
        <div>
          <div className="agent-eyebrow"><Bot size={15} /> MCP ASSISTANT</div>
          <h2>Store assistant</h2>
          <p>Ask questions about inventory and WooCommerce using the tools permitted for your API key.</p>
        </div>
        <button type="button" className="agent-clear" onClick={clearChat} disabled={busy}><Trash2 size={15} /> Clear chat</button>
      </div>

      <div className="agent-key-panel">
        <div className="agent-key-icon"><KeyRound size={18} /></div>
        <div className="agent-key-copy">
          <label htmlFor="agent-api-key">Member MCP API key</label>
          <p>Used for this chat session only. It is not saved in browser storage.</p>
        </div>
        <input
          id="agent-api-key"
          type="password"
          autoComplete="off"
          spellCheck="false"
          placeholder="mcp_live_…"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          disabled={busy}
        />
      </div>

      <div className="agent-chat-card">
        <div className="agent-chat-topline"><span><span className="agent-status-dot" /> Gateway-connected workflow</span><span><ShieldCheck size={14} /> Gateway enforces permissions</span></div>
        <div className="agent-messages" aria-live="polite">
          {messages.map((message, index) => (
            <div className={`agent-message-row ${message.role}`} key={`${index}-${message.role}`}>
              <div className="agent-avatar">{message.role === "assistant" ? <Bot size={17} /> : <UserRound size={17} />}</div>
              <div className="agent-message-content">
                <div className="agent-message-role">{message.role === "assistant" ? "Assistant" : "You"}</div>
                <div className="agent-bubble">{message.content}</div>
                {message.tools_used?.length > 0 && <div className="agent-tool-tags">Used: {message.tools_used.map((tool) => <span key={tool}>{tool}</span>)}</div>}
              </div>
            </div>
          ))}
          {busy && <div className="agent-message-row assistant"><div className="agent-avatar"><Bot size={17} /></div><div className="agent-message-content"><div className="agent-message-role">Assistant</div><div className="agent-bubble agent-thinking"><LoaderCircle size={15} className="agent-spin" /> Checking permitted tools…</div></div></div>}
          <div ref={endRef} />
        </div>

        {messages.length <= 1 && <div className="agent-suggestions">{SUGGESTIONS.map((suggestion) => <button key={suggestion} type="button" onClick={() => sendMessage(suggestion)} disabled={busy}>{suggestion}</button>)}</div>}
        {error && <div className="agent-error" role="alert">{error}</div>}
        <form className="agent-composer" onSubmit={(e) => { e.preventDefault(); sendMessage(); }}>
          <textarea ref={inputRef} rows={1} value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } }} placeholder="Ask about inventory or orders…" disabled={busy} maxLength={4000} />
          <button type="submit" aria-label="Send message" disabled={busy || !draft.trim()}><Send size={17} /></button>
        </form>
        <div className="agent-footnote">Read-only MVP · Enter to send · Shift+Enter for a new line</div>
      </div>
    </section>
  );
}
