import { useState, useRef, useCallback, useEffect } from "react";

// In production (Fly.io), frontend and backend share the same origin,
// so "/api" works as a relative path. In local dev, Vite proxies /api → localhost:8000.
const API_BASE = "/api";

const TABS = [
  { id: "qa", label: "Document Q&A", icon: "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" },
  { id: "translate", label: "Translation", icon: "M3 5h12M9 3v2m1.048 9.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10M12.751 5C11.783 10.77 8.07 15.61 3 18.129" },
  { id: "timeline", label: "Case Timeline", icon: "M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" },
  { id: "rfe", label: "RFE Tracker", icon: "M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" },
];

const LANGUAGES = { tr: "Turkish", es: "Spanish", zh: "Chinese", ar: "Arabic", en: "English" };

/** Look up a client record by display name (case-insensitive). Used by Timeline to bridge into Q&A data. */
function getClientByName(name) {
  if (!name) return null;
  try {
    const clients = JSON.parse(localStorage.getItem("imm_clients") || "[]");
    return clients.find(c => c.name.toLowerCase().trim() === name.toLowerCase().trim()) || null;
  } catch { return null; }
}

function Icon({ path, size = 20 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d={path} />
    </svg>
  );
}

function StatusBadge({ type, children }) {
  const colors = {
    success: { bg: "#EAF3DE", text: "#27500A", border: "#97C459" },
    warning: { bg: "#FAEEDA", text: "#633806", border: "#EF9F27" },
    info: { bg: "#E6F1FB", text: "#0C447C", border: "#85B7EB" },
    error: { bg: "#FCEBEB", text: "#791F1F", border: "#F09595" },
  };
  const c = colors[type] || colors.info;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 11, fontWeight: 500, padding: "2px 10px", borderRadius: 100, background: c.bg, color: c.text, border: `1px solid ${c.border}` }}>
      {children}
    </span>
  );
}

function FileUploadZone({ onFilesSelected, accept = ".pdf,.txt,.docx", multiple = false, label }) {
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef(null);
  return (
    <div
      onClick={() => inputRef.current?.click()}
      onDragOver={e => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={e => {
        e.preventDefault(); setDragOver(false);
        const files = Array.from(e.dataTransfer.files);
        if (files.length) onFilesSelected(files);
      }}
      style={{
        border: `2px dashed ${dragOver ? "#378ADD" : "rgba(0,0,0,0.15)"}`,
        borderRadius: 12, padding: "2rem", textAlign: "center", cursor: "pointer",
        background: dragOver ? "rgba(55,138,221,0.04)" : "transparent",
        transition: "all 0.2s",
      }}
    >
      <input ref={inputRef} type="file" accept={accept} multiple={multiple} hidden
        onChange={e => { if (e.target.files?.length) onFilesSelected(Array.from(e.target.files)); }} />
      <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="rgba(0,0,0,0.3)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ margin: "0 auto 8px" }}>
        <path d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
      </svg>
      <p style={{ fontSize: 14, color: "rgba(0,0,0,0.5)", margin: 0 }}>{label || "Drop a PDF, TXT, or DOCX file here or click to upload"}</p>
    </div>
  );
}

/**
 * Renders LLM-generated text with basic markdown support:
 * **bold**, paragraph breaks (\n\n), and line breaks (\n).
 * No external dependencies — avoids the asterisk-as-literal problem.
 */
function MarkdownText({ text }) {
  if (!text) return null;

  const renderInline = (str) => {
    const parts = str.split(/(\*\*[^*\n]+\*\*)/g);
    return parts.map((part, i) =>
      part.startsWith("**") && part.endsWith("**")
        ? <strong key={i}>{part.slice(2, -2)}</strong>
        : <span key={i}>{part}</span>
    );
  };

  const blocks = text.split(/\n\n+/);
  return (
    <>
      {blocks.map((block, bi) => {
        const lines = block.split("\n");
        return (
          <p key={bi} style={{ margin: bi === 0 ? 0 : "10px 0 0", lineHeight: 1.65 }}>
            {lines.map((line, li) => (
              <span key={li}>{li > 0 && <br />}{renderInline(line)}</span>
            ))}
          </p>
        );
      })}
    </>
  );
}

function DocumentQA() {
  // ─── Client management (localStorage-persisted) ───────────────────
  const [clients, setClients] = useState(() => {
    try { return JSON.parse(localStorage.getItem("imm_clients") || "[]"); } catch { return []; }
  });
  const [selectedClientId, setSelectedClientId] = useState(
    () => localStorage.getItem("imm_selected_client") || null
  );
  const [showNewClient, setShowNewClient] = useState(false);
  const [newClientName, setNewClientName] = useState("");

  const selectedClient = clients.find(c => c.id === selectedClientId) || null;
  const clientName = selectedClient?.name || null;

  // ─── Per-client state ─────────────────────────────────────────────
  const [messages, setMessages] = useState(() => {
    const cid = localStorage.getItem("imm_selected_client");
    if (!cid) return [];
    try { return JSON.parse(localStorage.getItem(`imm_msgs_${cid}`) || "[]"); } catch { return []; }
  });
  const [notes, setNotes] = useState(() => {
    const cid = localStorage.getItem("imm_selected_client");
    return cid ? (localStorage.getItem(`imm_notes_${cid}`) || "") : "";
  });
  // serverDocs = full list fetched from vector store for selected client
  const [serverDocs, setServerDocs] = useState([]);
  const [question, setQuestion] = useState("");
  const [uploading, setUploading] = useState(false);
  const [asking, setAsking] = useState(false);
  const [deletingClient, setDeletingClient] = useState(false);
  const chatEndRef = useRef(null);

  // Fetch all stored docs for a client from the server
  const fetchServerDocs = useCallback(async (name) => {
    if (!name) { setServerDocs([]); return; }
    try {
      const res = await fetch(`${API_BASE}/documents/client/${encodeURIComponent(name)}`);
      if (res.ok) {
        const data = await res.json();
        setServerDocs(data.documents || []);
      }
    } catch { setServerDocs([]); }
  }, []);

  // Delete a single doc for the current client
  const deleteDoc = useCallback(async (filename) => {
    if (!clientName) return;
    try {
      const res = await fetch(
        `${API_BASE}/documents/client/${encodeURIComponent(clientName)}/${encodeURIComponent(filename)}`,
        { method: "DELETE" }
      );
      if (res.ok) {
        setServerDocs(prev => prev.filter(f => f !== filename));
        setMessages(prev => [...prev, { role: "system", text: `Removed "${filename}" from this client's document store.` }]);
      }
    } catch (e) {
      setMessages(prev => [...prev, { role: "system", text: `Delete failed: ${e.message}`, error: true }]);
    }
  }, [clientName]);

  // Persist messages when they change
  useEffect(() => {
    if (selectedClientId) localStorage.setItem(`imm_msgs_${selectedClientId}`, JSON.stringify(messages));
  }, [messages, selectedClientId]);

  // Persist notes when they change
  useEffect(() => {
    if (selectedClientId) localStorage.setItem(`imm_notes_${selectedClientId}`, notes);
  }, [notes, selectedClientId]);

  // On mount, load server docs for the initially-selected client
  useEffect(() => {
    if (clientName) fetchServerDocs(clientName);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  // Switch client — load its persisted messages + notes + server docs
  const selectClient = useCallback((cid) => {
    setSelectedClientId(cid);
    localStorage.setItem("imm_selected_client", cid || "");
    const name = clients.find(c => c.id === cid)?.name || null;
    if (cid) {
      try { setMessages(JSON.parse(localStorage.getItem(`imm_msgs_${cid}`) || "[]")); } catch { setMessages([]); }
      setNotes(localStorage.getItem(`imm_notes_${cid}`) || "");
    } else {
      setMessages([]);
      setNotes("");
    }
    fetchServerDocs(name);
  }, [clients, fetchServerDocs]);

  // Create a new client and immediately select it
  const addClient = useCallback(() => {
    const name = newClientName.trim();
    if (!name) return;
    const id = `client_${Date.now()}`;
    const updated = [...clients, { id, name, createdAt: new Date().toISOString() }];
    setClients(updated);
    localStorage.setItem("imm_clients", JSON.stringify(updated));
    setNewClientName("");
    setShowNewClient(false);
    selectClient(id);
  }, [clients, newClientName, selectClient]);

  // Delete the currently selected client: wipe server docs + localStorage data
  const deleteClient = useCallback(async () => {
    if (!selectedClient) return;
    if (!window.confirm(`Delete client "${selectedClient.name}" and all their documents? This cannot be undone.`)) return;
    setDeletingClient(true);
    try {
      // Remove all server-side document chunks for this client
      await fetch(`${API_BASE}/documents/client/${encodeURIComponent(selectedClient.name)}`, { method: "DELETE" });
    } catch (e) {
      console.error("Failed to delete server documents:", e);
    }
    // Clean up all localStorage keys for this client
    localStorage.removeItem(`imm_msgs_${selectedClient.id}`);
    localStorage.removeItem(`imm_notes_${selectedClient.id}`);
    const updated = clients.filter(c => c.id !== selectedClient.id);
    localStorage.setItem("imm_clients", JSON.stringify(updated));
    localStorage.removeItem("imm_selected_client");
    setClients(updated);
    setSelectedClientId(null);
    setMessages([]);
    setNotes("");
    setServerDocs([]);
    setDeletingClient(false);
  }, [selectedClient, clients]);

  const uploadFile = useCallback(async (files) => {
    if (!clientName) {
      setMessages(prev => [...prev, { role: "system", text: "Please select or create a client before uploading.", error: true }]);
      return;
    }
    setUploading(true);
    for (const file of files) {
      const form = new FormData();
      form.append("file", file);
      form.append("client_name", clientName);
      try {
        const res = await fetch(`${API_BASE}/documents/upload`, { method: "POST", body: form });
        const data = await res.json();
        if (res.ok) {
          const caseType = data.extracted_metadata?.case_type;
          // Refresh the stored-docs list from the server
          fetchServerDocs(clientName);
          setMessages(prev => [...prev, {
            role: "system",
            text: `✓ Uploaded ${file.name} — ${data.pages_processed} page${data.pages_processed !== 1 ? "s" : ""}, ${data.chunks_created} chunks indexed.`
              + (caseType ? ` Detected: ${caseType}.` : ""),
          }]);
        } else {
          setMessages(prev => [...prev, { role: "system", text: `Failed to upload ${file.name}: ${data.detail || "Unknown error"}`, error: true }]);
        }
      } catch (e) {
        setMessages(prev => [...prev, { role: "system", text: `Upload error: ${e.message}`, error: true }]);
      }
    }
    setUploading(false);
  }, [clientName, fetchServerDocs]);

  /**
   * Demo-mode shortcut: creates a "Demo Client" (or reuses an existing one),
   * selects it, then fetches /sample-i797-notice.txt from the static assets
   * and uploads it through the real upload pipeline. Lets reviewers hit a
   * working Q&A flow in one click without having a USCIS document on hand.
   */
  const loadSampleDemo = useCallback(async () => {
    const sampleClientName = "Demo Client";
    let demoClient = clients.find(c => c.name === sampleClientName);
    let demoClientId = demoClient?.id;
    if (!demoClient) {
      demoClientId = `client_demo_${Date.now()}`;
      const updated = [...clients, { id: demoClientId, name: sampleClientName, createdAt: new Date().toISOString() }];
      setClients(updated);
      localStorage.setItem("imm_clients", JSON.stringify(updated));
    }
    setSelectedClientId(demoClientId);
    localStorage.setItem("imm_selected_client", demoClientId);
    setMessages([{ role: "system", text: "Loading sample I-797 receipt notice…" }]);
    setUploading(true);
    try {
      const resp = await fetch("/sample-i797-notice.txt");
      if (!resp.ok) throw new Error(`Could not load sample file (HTTP ${resp.status}).`);
      const blob = await resp.blob();
      const file = new File([blob], "sample-i797-notice.txt", { type: "text/plain" });
      const form = new FormData();
      form.append("file", file);
      form.append("client_name", sampleClientName);
      const uploadRes = await fetch(`${API_BASE}/documents/upload`, { method: "POST", body: form });
      const data = await uploadRes.json();
      if (uploadRes.ok) {
        fetchServerDocs(sampleClientName);
        const caseType = data.extracted_metadata?.case_type;
        setMessages([
          {
            role: "system",
            text: `✓ Loaded sample I-797 notice — ${data.pages_processed} page${data.pages_processed !== 1 ? "s" : ""}, ${data.chunks_created} chunks indexed.`
              + (caseType ? ` Detected case type: ${caseType}.` : ""),
          },
          {
            role: "system",
            text: 'Try asking: "What is the receipt number?" or "When was this notice issued?" or "What is the priority date?"',
          },
        ]);
      } else {
        setMessages([{ role: "system", text: `Sample load failed: ${data.detail || "Unknown error"}`, error: true }]);
      }
    } catch (e) {
      setMessages([{ role: "system", text: `Sample load error: ${e.message}`, error: true }]);
    }
    setUploading(false);
  }, [clients, fetchServerDocs]);

  const askQuestion = useCallback(async () => {
    if (!question.trim()) return;
    const q = question.trim();
    setQuestion("");
    setMessages(prev => [...prev, { role: "user", text: q }]);
    setAsking(true);
    try {
      // Always scope queries to the selected client — prevents cross-client bleed
      const body = { question: q, top_k: 5, ...(clientName ? { client_name: clientName } : {}) };
      const res = await fetch(`${API_BASE}/documents/ask`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      const data = await res.json();
      setMessages(prev => [...prev, {
        role: "assistant", text: data.answer, confidence: data.confidence,
        sources: data.sources, disclaimer: data.disclaimer,
      }]);
    } catch (e) {
      setMessages(prev => [...prev, { role: "system", text: `Error: ${e.message}`, error: true }]);
    }
    setAsking(false);
  }, [question, clientName]);

  const inputStyle = { padding: "6px 12px", border: "1px solid rgba(0,0,0,0.15)", borderRadius: 8, fontSize: 13, outline: "none", fontFamily: "inherit" };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* ── Client bar ─────────────────────────────────────────────── */}
      <div style={{ borderBottom: "1px solid rgba(0,0,0,0.08)", background: "#fff" }}>
        {/* Row 1: selector + new-client */}
        <div style={{ padding: "10px 1.5rem", display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: "rgba(0,0,0,0.4)", whiteSpace: "nowrap" }}>Client</span>
          <select
            value={selectedClientId || ""}
            onChange={e => selectClient(e.target.value || null)}
            style={{ ...inputStyle, minWidth: 200, background: "#fff" }}
          >
            <option value="">— choose existing —</option>
            {clients.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>

          {!showNewClient ? (
            <>
              <button
                onClick={() => setShowNewClient(true)}
                style={{ ...inputStyle, cursor: "pointer", background: "transparent", border: "1px dashed rgba(0,0,0,0.22)", color: "rgba(0,0,0,0.5)", display: "flex", alignItems: "center", gap: 4 }}
              >
                + New client
              </button>
              <button
                onClick={loadSampleDemo}
                disabled={uploading}
                title="Creates a Demo Client and loads a synthetic I-797 receipt notice so you can try Q&A in one click."
                style={{
                  ...inputStyle,
                  cursor: uploading ? "default" : "pointer",
                  background: uploading ? "rgba(15,110,86,0.08)" : "#EAF3DE",
                  border: "1px solid #97C459",
                  color: "#27500A",
                  fontWeight: 500,
                  display: "flex", alignItems: "center", gap: 4,
                  opacity: uploading ? 0.6 : 1,
                }}
              >
                ✨ Try with sample document
              </button>
            </>
          ) : (
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <input
                autoFocus
                type="text"
                placeholder="Client name..."
                value={newClientName}
                onChange={e => setNewClientName(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter") addClient(); if (e.key === "Escape") { setShowNewClient(false); setNewClientName(""); } }}
                style={{ ...inputStyle, border: "1px solid #0F6E56", width: 160 }}
              />
              <button onClick={addClient} disabled={!newClientName.trim()} style={{ ...inputStyle, border: "none", background: newClientName.trim() ? "#0F6E56" : "rgba(0,0,0,0.08)", color: newClientName.trim() ? "#fff" : "rgba(0,0,0,0.3)", fontWeight: 500, cursor: "pointer" }}>Save</button>
              <button onClick={() => { setShowNewClient(false); setNewClientName(""); }} style={{ ...inputStyle, background: "transparent", cursor: "pointer", color: "rgba(0,0,0,0.45)" }}>✕</button>
            </div>
          )}

          {/* Delete client — only shown when a client is selected */}
          {selectedClient && !showNewClient && (
            <button
              onClick={deleteClient}
              disabled={deletingClient}
              title={`Delete "${selectedClient.name}" and all their documents`}
              style={{
                padding: "4px 12px", border: "1px solid rgba(226,75,74,0.35)", borderRadius: 8,
                background: "transparent", color: "#E24B4A", fontSize: 12, fontWeight: 500,
                cursor: "pointer", marginLeft: "auto", opacity: deletingClient ? 0.5 : 1,
              }}
            >
              {deletingClient ? "Deleting…" : "Delete client"}
            </button>
          )}

          {uploading && <StatusBadge type="warning">Processing...</StatusBadge>}
        </div>

        {/* Row 2: stored docs for selected client */}
        {selectedClient && serverDocs.length > 0 && (
          <div style={{ padding: "6px 1.5rem 10px", display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
            <span style={{ fontSize: 11, color: "rgba(0,0,0,0.35)", fontWeight: 500, marginRight: 2 }}>Stored docs:</span>
            {serverDocs.map(filename => (
              <span key={filename} style={{
                display: "inline-flex", alignItems: "center", gap: 4, fontSize: 11, fontWeight: 500,
                padding: "2px 6px 2px 10px", borderRadius: 100,
                background: "#E1F5EE", color: "#085041", border: "1px solid #9FE1CB",
              }}>
                {filename}
                <button
                  onClick={() => deleteDoc(filename)}
                  title={`Remove "${filename}" from this client`}
                  style={{
                    background: "none", border: "none", cursor: "pointer", padding: "0 2px",
                    color: "#085041", fontSize: 12, lineHeight: 1, opacity: 0.6,
                    display: "flex", alignItems: "center",
                  }}
                >✕</button>
              </span>
            ))}
          </div>
        )}
      </div>

      {/* ── Body: chat + notes sidebar ──────────────────────────────── */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>

        {/* Main chat column */}
        <div style={{ display: "flex", flexDirection: "column", flex: 1, overflow: "hidden" }}>
          <div style={{ flex: 1, overflow: "auto", padding: "1.5rem" }}>
            {!selectedClient ? (
              <div style={{ textAlign: "center", padding: "5rem 2rem" }}>
                <div style={{ fontSize: 36, marginBottom: 16 }}>👤</div>
                <p style={{ fontSize: 15, fontWeight: 600, marginBottom: 8, color: "#2C2C2A" }}>Select or create a client to get started</p>
                <p style={{ fontSize: 13, color: "rgba(0,0,0,0.4)", maxWidth: 360, margin: "0 auto", lineHeight: 1.6 }}>
                  Documents and conversations are stored per client so cases never mix.
                </p>
              </div>
            ) : messages.length === 0 ? (
              <div style={{ textAlign: "center", padding: "3rem 1rem" }}>
                <FileUploadZone onFilesSelected={uploadFile} multiple label="Upload immigration documents (PDF, TXT, or DOCX) to get started" />
                <p style={{ marginTop: 16, fontSize: 13, color: "rgba(0,0,0,0.4)" }}>
                  Upload USCIS notices, petitions, support letters, or any case documents
                </p>
              </div>
            ) : (
              <>
                {messages.map((msg, i) => (
                  <div key={i} style={{ marginBottom: 16, display: "flex", justifyContent: msg.role === "user" ? "flex-end" : "flex-start" }}>
                    <div style={{
                      maxWidth: "80%", padding: "12px 16px", borderRadius: 12, fontSize: 14, lineHeight: 1.6,
                      background: msg.role === "user" ? "#0F6E56" : msg.error ? "#FCEBEB" : "#F6F5F0",
                      color: msg.role === "user" ? "#fff" : msg.error ? "#791F1F" : "#2C2C2A",
                      borderBottomRightRadius: msg.role === "user" ? 4 : 12,
                      borderBottomLeftRadius: msg.role !== "user" ? 4 : 12,
                    }}>
                      {msg.role === "assistant"
                        ? <MarkdownText text={msg.text} />
                        : <div style={{ whiteSpace: "pre-wrap" }}>{msg.text}</div>
                      }
                      {msg.confidence !== undefined && (
                        <div style={{ marginTop: 8, display: "flex", gap: 8, flexWrap: "wrap" }}>
                          <StatusBadge type={msg.confidence > 0.7 ? "success" : msg.confidence > 0.4 ? "warning" : "error"}>
                            Confidence: {Math.round(msg.confidence * 100)}%
                          </StatusBadge>
                          {msg.sources?.length > 0 && <StatusBadge type="info">{msg.sources.length} sources</StatusBadge>}
                        </div>
                      )}
                      {msg.disclaimer && (
                        <p style={{ fontSize: 11, color: "rgba(0,0,0,0.4)", marginTop: 8, marginBottom: 0, fontStyle: "italic" }}>{msg.disclaimer}</p>
                      )}
                    </div>
                  </div>
                ))}
                {asking && (
                  <div style={{ display: "flex", gap: 4, padding: 12 }}>
                    {[0, 1, 2].map(i => (
                      <div key={i} style={{ width: 8, height: 8, borderRadius: "50%", background: "#0F6E56", animation: `pulse 1s ease-in-out ${i * 0.15}s infinite` }} />
                    ))}
                  </div>
                )}
              </>
            )}
            <div ref={chatEndRef} />
          </div>

          {selectedClient && (
            <div style={{ padding: "1rem 1.5rem", borderTop: "1px solid rgba(0,0,0,0.08)", display: "flex", gap: 8 }}>
              {messages.length > 0 && (
                <label style={{ padding: "8px 12px", border: "1px solid rgba(0,0,0,0.15)", borderRadius: 8, background: "transparent", cursor: "pointer", fontSize: 14, display: "flex", alignItems: "center" }}>
                  +
                  <input type="file" accept=".pdf,.txt,.docx" multiple hidden
                    onChange={e => { if (e.target.files?.length) uploadFile(Array.from(e.target.files)); }} />
                </label>
              )}
              <input
                type="text" value={question} onChange={e => setQuestion(e.target.value)}
                onKeyDown={e => e.key === "Enter" && askQuestion()}
                placeholder="Ask about your immigration documents..."
                style={{ flex: 1, padding: "8px 14px", border: "1px solid rgba(0,0,0,0.15)", borderRadius: 8, fontSize: 14, outline: "none" }}
              />
              <button onClick={askQuestion} disabled={asking || !question.trim()}
                style={{
                  padding: "8px 20px", borderRadius: 8, border: "none", cursor: "pointer", fontSize: 14, fontWeight: 500,
                  background: question.trim() ? "#0F6E56" : "rgba(0,0,0,0.08)", color: question.trim() ? "#fff" : "rgba(0,0,0,0.3)",
                  transition: "all 0.15s",
                }}>
                Ask
              </button>
            </div>
          )}
        </div>

        {/* Notes sidebar — only visible when a client is selected */}
        {selectedClient && (
          <div style={{
            width: 270, flexShrink: 0, borderLeft: "1px solid rgba(0,0,0,0.08)",
            display: "flex", flexDirection: "column", background: "#FFFEF5",
          }}>
            <div style={{ padding: "10px 14px", borderBottom: "1px solid rgba(0,0,0,0.06)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: "rgba(0,0,0,0.4)", textTransform: "uppercase", letterSpacing: "0.07em" }}>
                📌 Notes
              </span>
              <span style={{ fontSize: 11, color: "rgba(0,0,0,0.3)", maxWidth: 120, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {selectedClient.name}
              </span>
            </div>
            <textarea
              value={notes}
              onChange={e => setNotes(e.target.value)}
              placeholder={`Notes for ${selectedClient.name}…\n\nDeadlines, reminders, case details…`}
              style={{
                flex: 1, padding: "14px", border: "none", outline: "none", resize: "none",
                fontSize: 13, lineHeight: 1.75, background: "transparent", fontFamily: "inherit",
                color: "#2C2C2A",
              }}
            />
            <div style={{ padding: "6px 14px", borderTop: "1px solid rgba(0,0,0,0.05)", fontSize: 10, color: "rgba(0,0,0,0.22)", textAlign: "right" }}>
              auto-saved
            </div>
          </div>
        )}
      </div>

      <style>{`
        @keyframes pulse { 0%, 100% { opacity: 0.3; transform: scale(0.8); } 50% { opacity: 1; transform: scale(1); } }
        @keyframes progressIndeterminate { 0% { transform: translateX(-100%); } 100% { transform: translateX(350%); } }
      `}</style>
    </div>
  );
}

function LoadingBar({ label }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ height: 3, background: "rgba(0,0,0,0.06)", borderRadius: 2, overflow: "hidden" }}>
        <div style={{ height: "100%", background: "#0F6E56", borderRadius: 2, animation: "progressIndeterminate 1.5s ease-in-out infinite", width: "40%" }} />
      </div>
      <p style={{ fontSize: 12, color: "rgba(0,0,0,0.45)", marginTop: 6 }}>{label}</p>
    </div>
  );
}

function TranslationPanel() {
  const [sourceText, setSourceText] = useState("");
  const [translatedText, setTranslatedText] = useState("");
  const [sourceLang, setSourceLang] = useState("tr");
  const [targetLang, setTargetLang] = useState("en");
  const [certification, setCertification] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingFile, setLoadingFile] = useState(null); // filename being translated
  const [meta, setMeta] = useState(null);   // { model, words, pages, success, confidence }
  const [mode, setMode] = useState("text");
  const [generateCert, setGenerateCert] = useState(false);

  const DownloadIcon = () => (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3" />
    </svg>
  );

  const downloadTxt = () => {
    const textToSave = certification ? `${translatedText}\n\n${certification}` : translatedText;
    const blob = new Blob([textToSave], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "immigration_translation.txt"; a.click();
    URL.revokeObjectURL(url);
  };

  const downloadAs = async (fmt) => {
    const form = new FormData();
    form.append("translated_text", translatedText);
    form.append("certification", certification || "");
    form.append("original_filename", loadingFile || "translation");
    form.append("fmt", fmt);
    try {
      const res = await fetch(`${API_BASE}/translation/export`, { method: "POST", body: form });
      if (!res.ok) { alert("Export failed. Please try again."); return; }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = `immigration_translation.${fmt}`; a.click();
      URL.revokeObjectURL(url);
    } catch (e) { alert(`Export error: ${e.message}`); }
  };

  const translateText = async () => {
    if (!sourceText.trim()) return;
    setLoading(true); setTranslatedText(""); setCertification(""); setMeta(null);
    try {
      const res = await fetch(`${API_BASE}/translation/text`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: sourceText, source_lang: sourceLang, target_lang: targetLang, generate_certification: generateCert }),
      });
      const data = await res.json();
      if (res.ok) {
        setTranslatedText(data.translated_text);
        setCertification(data.certification_statement || "");
        setMeta({ model: data.model_used, words: data.word_count, success: true, confidence: data.confidence ?? null });
      } else {
        setTranslatedText(`Error: ${data.detail || "Translation failed"}`);
        setMeta({ success: false });
      }
    } catch (e) { setTranslatedText(`Error: ${e.message}`); setMeta({ success: false }); }
    setLoading(false);
  };

  const translateDocument = async (files) => {
    if (!files.length) return;
    const file = files[0];
    setLoadingFile(file.name);
    setLoading(true); setTranslatedText(""); setCertification(""); setMeta(null);
    const form = new FormData();
    form.append("file", file);
    form.append("source_lang", sourceLang);
    form.append("target_lang", targetLang);
    form.append("generate_certification", generateCert ? "true" : "false");
    try {
      const res = await fetch(`${API_BASE}/translation/document`, { method: "POST", body: form });
      const data = await res.json();
      if (res.ok) {
        const allText = data.translated_pages.map(p => `--- Page ${p.page_number} ---\n${p.translated_text}`).join("\n\n");
        setTranslatedText(allText);
        setCertification(data.certification_statement || "");
        setMeta({ pages: data.total_pages, model: data.model_used, success: true, confidence: data.confidence ?? null });
      } else {
        setTranslatedText(`Error: ${data.detail}`);
        setMeta({ success: false });
      }
    } catch (e) { setTranslatedText(`Error: ${e.message}`); setMeta({ success: false }); }
    setLoading(false);
  };

  const langOptions = Object.entries(LANGUAGES).filter(([k]) => k !== (mode === "text" ? targetLang : ""));

  return (
    <div style={{ padding: "1.5rem", maxWidth: 900, margin: "0 auto" }}>

      {/* ── Alert banner ─────────────────────────────────────────── */}
      <div style={{
        display: "flex", gap: 10, alignItems: "flex-start",
        background: "#FFF8E1", border: "1px solid #FFD54F",
        borderRadius: 10, padding: "12px 16px", marginBottom: 20,
      }}>
        <span style={{ fontSize: 18, flexShrink: 0 }}>⚠️</span>
        <p style={{ margin: 0, fontSize: 13, color: "#5D4037", lineHeight: 1.6 }}>
          <strong>For assistance only.</strong> AI-generated translations are drafts and must be reviewed and certified by a qualified human translator before submission to USCIS or any government authority. Do not submit this output directly — treat it as a starting point for professional review.
        </p>
      </div>

      {/* ── Mode toggle ──────────────────────────────────────────── */}
      <div style={{ display: "flex", gap: 8, marginBottom: 20 }}>
        {["text", "document"].map(m => (
          <button key={m} onClick={() => setMode(m)} style={{
            padding: "6px 16px", borderRadius: 8, fontSize: 13, fontWeight: 500, cursor: "pointer",
            border: mode === m ? "1.5px solid #0F6E56" : "1px solid rgba(0,0,0,0.12)",
            background: mode === m ? "#E1F5EE" : "transparent",
            color: mode === m ? "#085041" : "rgba(0,0,0,0.5)",
          }}>{m === "text" ? "Text" : "Document"}</button>
        ))}
      </div>

      {/* ── Certification toggle ─────────────────────────────────── */}
      <label style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16, cursor: "pointer", userSelect: "none" }}>
        <input
          type="checkbox"
          checked={generateCert}
          onChange={e => setGenerateCert(e.target.checked)}
          style={{ width: 15, height: 15, accentColor: "#0F6E56", cursor: "pointer" }}
        />
        <span style={{ fontSize: 13, color: "rgba(0,0,0,0.6)" }}>
          Generate USCIS certification statement
        </span>
      </label>

      {/* ── Language pair ────────────────────────────────────────── */}
      <div style={{ display: "flex", gap: 12, marginBottom: 16, alignItems: "center" }}>
        <select value={sourceLang} onChange={e => setSourceLang(e.target.value)}
          style={{ padding: "6px 12px", border: "1px solid rgba(0,0,0,0.15)", borderRadius: 8, fontSize: 13 }}>
          {langOptions.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <span style={{ fontSize: 18, color: "rgba(0,0,0,0.25)" }}>→</span>
        <select value={targetLang} onChange={e => setTargetLang(e.target.value)}
          style={{ padding: "6px 12px", border: "1px solid rgba(0,0,0,0.15)", borderRadius: 8, fontSize: 13 }}>
          {Object.entries(LANGUAGES).filter(([k]) => k !== sourceLang).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </div>

      {/* ── Main content area ────────────────────────────────────── */}
      {mode === "text" ? (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          <div>
            <label style={{ fontSize: 12, color: "rgba(0,0,0,0.4)", display: "block", marginBottom: 6, fontWeight: 500 }}>
              Source ({LANGUAGES[sourceLang]})
            </label>
            <textarea value={sourceText} onChange={e => setSourceText(e.target.value)}
              rows={10} placeholder={`Enter ${LANGUAGES[sourceLang]} text...`}
              style={{ width: "100%", padding: 12, border: "1px solid rgba(0,0,0,0.12)", borderRadius: 10, fontSize: 14, resize: "vertical", lineHeight: 1.6, fontFamily: "inherit", outline: "none", boxSizing: "border-box" }} />
            <button onClick={translateText} disabled={loading || !sourceText.trim()}
              style={{
                marginTop: 10, width: "100%", padding: "10px", borderRadius: 8, border: "none", fontSize: 14, fontWeight: 500, cursor: "pointer",
                background: sourceText.trim() ? "#0F6E56" : "rgba(0,0,0,0.08)", color: sourceText.trim() ? "#fff" : "rgba(0,0,0,0.3)",
              }}>
              {loading ? "Translating…" : "Translate"}
            </button>
          </div>
          <div>
            <label style={{ fontSize: 12, color: "rgba(0,0,0,0.4)", display: "block", marginBottom: 6, fontWeight: 500 }}>
              Translation ({LANGUAGES[targetLang]})
            </label>
            {loading && <LoadingBar label="Translating with Gemini 2.5 Flash…" />}
            <textarea value={translatedText} readOnly rows={10}
              placeholder="Translation will appear here…"
              style={{ width: "100%", padding: 12, border: "1px solid rgba(0,0,0,0.12)", borderRadius: 10, fontSize: 14, resize: "vertical", lineHeight: 1.6, fontFamily: "inherit", background: "#FAFAF7", outline: "none", boxSizing: "border-box" }} />
          </div>
        </div>
      ) : (
        <div>
          <FileUploadZone onFilesSelected={translateDocument} label={`Upload ${LANGUAGES[sourceLang]} PDF, TXT, or DOCX for translation`} />
          {loading && (
            <div style={{ marginTop: 16 }}>
              <LoadingBar label={`Translating "${loadingFile}" — this may take a moment for longer documents…`} />
            </div>
          )}
          {!loading && translatedText && (
            <div style={{ marginTop: 16, padding: 16, background: "#FAFAF7", borderRadius: 10, border: "1px solid rgba(0,0,0,0.08)" }}>
              <pre style={{ whiteSpace: "pre-wrap", fontSize: 13, lineHeight: 1.7, margin: 0, fontFamily: "inherit" }}>{translatedText}</pre>
            </div>
          )}
        </div>
      )}

      {/* ── Download buttons ─────────────────────────────────────── */}
      {translatedText && !loading && (
        <div style={{ marginTop: 14, display: "flex", gap: 8, flexWrap: "wrap" }}>
          {[
            { fmt: "txt",  label: ".txt",  action: downloadTxt },
            { fmt: "docx", label: ".docx", action: () => downloadAs("docx") },
            { fmt: "pdf",  label: ".pdf",  action: () => downloadAs("pdf") },
          ].map(({ fmt, label, action }) => (
            <button key={fmt} onClick={action}
              style={{
                padding: "6px 14px", borderRadius: 8, fontSize: 13, fontWeight: 500, cursor: "pointer",
                background: "#fff", border: "1px solid rgba(0,0,0,0.15)", color: "#2C2C2A",
                display: "flex", alignItems: "center", gap: 5,
              }}>
              <DownloadIcon /> Download {label}
            </button>
          ))}
        </div>
      )}

      {/* ── Meta badges ──────────────────────────────────────────── */}
      {meta && (
        <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap", alignItems: "center" }}>
          {meta.success === true && <StatusBadge type="success">✓ Translation complete</StatusBadge>}
          {meta.success === false && <StatusBadge type="error">✗ Translation failed</StatusBadge>}
          {meta.confidence != null && (
            <StatusBadge type={meta.confidence > 0.8 ? "success" : meta.confidence > 0.6 ? "warning" : "error"}>
              Confidence: {Math.round(meta.confidence * 100)}%
            </StatusBadge>
          )}
          {meta.confidence != null && meta.confidence < 0.85 && (
            <StatusBadge type="warning">⚑ Attorney review recommended</StatusBadge>
          )}
          {meta.model && <StatusBadge type="info">
            {meta.model.includes("gemini") ? "Gemini 2.5 Flash" : meta.model.split("/").pop()}
          </StatusBadge>}
          {meta.words && <StatusBadge type="info">{meta.words} words</StatusBadge>}
          {meta.pages && <StatusBadge type="info">{meta.pages} pages</StatusBadge>}
        </div>
      )}

      {/* ── Certification ────────────────────────────────────────── */}
      {certification && (
        <details style={{ marginTop: 20 }}>
          <summary style={{ fontSize: 13, fontWeight: 500, color: "#0F6E56", cursor: "pointer" }}>
            View USCIS certification statement
          </summary>
          <pre style={{
            marginTop: 8, padding: 16, background: "#FAFAF7", borderRadius: 10,
            border: "1px solid rgba(0,0,0,0.08)", fontSize: 12, lineHeight: 1.6,
            whiteSpace: "pre-wrap", fontFamily: "'DM Mono', monospace",
          }}>{certification}</pre>
        </details>
      )}
    </div>
  );
}

function TimelinePanel() {
  const [events, setEvents] = useState([]);
  const [caseInfo, setCaseInfo] = useState(null);
  const [loading, setLoading] = useState(false);
  const [clientName, setClientName] = useState("");
  const [showAddForm, setShowAddForm] = useState(false);
  const [newEvent, setNewEvent] = useState({
    event_type: "filing", date: "", description: "", receipt_number: "", form_type: "",
  });
  const [deadlineCalc, setDeadlineCalc] = useState({ type: "rfe_issued", date: "" });

  // Context sidebar state
  const [contextDocs, setContextDocs] = useState([]);
  const [contextNotes, setContextNotes] = useState(null);
  const [quickQ, setQuickQ] = useState("");
  const [quickA, setQuickA] = useState(null);
  const [quickAsking, setQuickAsking] = useState(false);
  const [sidebarTab, setSidebarTab] = useState("docs");

  // ─── USCIS hard-deadline rules ────────────────────────────────────
  // These are response windows where missing the deadline means denial
  const DEADLINE_RULES = {
    rfe_issued:    { days: 87, label: "RFE (Request for Evidence) Issued" },
    noid:          { days: 30, label: "NOID — Notice of Intent to Deny" },
    noir:          { days: 33, label: "NOIR — Notice of Intent to Revoke" },
    denial_appeal: { days: 30, label: "Denial — Appeal (AAO / BIA)" },
    denial_motion: { days: 30, label: "Denial — Motion to Reopen/Reconsider" },
  };

  const EVENT_LABELS = {
    filing:       "Filed",
    receipt:      "Receipt Notice Received",
    biometrics:   "Biometrics Appointment",
    rfe_issued:   "RFE Issued",
    rfe_response: "RFE Response Submitted",
    noid:         "NOID — Intent to Deny",
    interview:    "Interview",
    approval:     "Approved ✓",
    denial:       "Denied",
    transfer:     "Case Transferred",
    other:        "Note / Other",
  };

  const EVENT_TYPES = Object.keys(EVENT_LABELS);

  // ─── Date helpers ─────────────────────────────────────────────────
  // Parse both MM/DD/YYYY and ISO formats; returns days from today (+ future, - past)
  const daysFromNow = (dateStr) => {
    if (!dateStr) return null;
    const normalized = dateStr.replace(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/, "$3-$1-$2");
    const d = new Date(normalized);
    if (isNaN(d.getTime())) return null;
    const today = new Date(); today.setHours(0, 0, 0, 0);
    return Math.ceil((d - today) / 86400000);
  };

  const addDaysToDate = (dateStr, n) => {
    if (!dateStr) return null;
    const normalized = dateStr.replace(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/, "$3-$1-$2");
    const d = new Date(normalized);
    if (isNaN(d.getTime())) return null;
    d.setDate(d.getDate() + n);
    return d;
  };

  const urgencyBadgeType = (days) => {
    if (days === null) return "info";
    if (days < 0) return "error";
    if (days <= 30) return "error";
    if (days <= 90) return "warning";
    return "success";
  };

  // Pre-compute the deadline calculator result
  const calcResult = (() => {
    if (!deadlineCalc.date) return null;
    const rule = DEADLINE_RULES[deadlineCalc.type];
    if (!rule) return null;
    const deadline = addDaysToDate(deadlineCalc.date, rule.days);
    if (!deadline) return null;
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const daysLeft = Math.ceil((deadline - today) / 86400000);
    return { deadline, daysLeft, rule };
  })();

  // ─── Data fetching ────────────────────────────────────────────────
  const loadClientContext = useCallback(async (name) => {
    if (!name.trim()) return;
    try {
      const res = await fetch(`${API_BASE}/documents/client/${encodeURIComponent(name.trim())}`);
      if (res.ok) { const d = await res.json(); setContextDocs(d.documents || []); }
    } catch { setContextDocs([]); }
    const client = getClientByName(name.trim());
    setContextNotes(client ? (localStorage.getItem(`imm_notes_${client.id}`) || null) : null);
    setQuickA(null);
  }, []);

  const askQuick = async () => {
    if (!quickQ.trim() || !clientName.trim()) return;
    setQuickAsking(true); setQuickA(null);
    try {
      const res = await fetch(`${API_BASE}/documents/ask`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: quickQ.trim(), client_name: clientName.trim(), top_k: 3 }),
      });
      const d = await res.json();
      setQuickA({ text: d.answer, confidence: d.confidence });
    } catch (e) { setQuickA({ text: `Error: ${e.message}`, error: true }); }
    setQuickAsking(false);
  };

  const fetchClientTimeline = async (name) => {
    if (!name.trim()) return;
    try {
      const res = await fetch(`${API_BASE}/timeline/events/${encodeURIComponent(name.trim())}`);
      const data = await res.json();
      if (res.ok && data.events?.length) { setEvents(data.events); setCaseInfo(data); }
    } catch (e) { console.error(e); }
    loadClientContext(name);
  };

  const addManualEvent = async () => {
    if (!clientName.trim() || !newEvent.description.trim()) return;
    setLoading(true);
    try {
      const body = {
        client_name: clientName.trim(),
        event_type: newEvent.event_type,
        description: newEvent.description,
        date: newEvent.date || null,
        receipt_number: newEvent.receipt_number || null,
        form_type: newEvent.form_type || null,
      };
      const res = await fetch(`${API_BASE}/timeline/events/add`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (res.ok) {
        setEvents(data.events); setCaseInfo(data);
        setNewEvent({ event_type: "filing", date: "", description: "", receipt_number: "", form_type: "" });
        setShowAddForm(false);
      }
    } catch (e) { console.error(e); }
    setLoading(false);
  };

  const extractTimeline = async (files) => {
    setLoading(true);
    const form = new FormData();
    if (files.length === 1) {
      form.append("file", files[0]);
      if (clientName) form.append("client_name", clientName);
      try {
        const res = await fetch(`${API_BASE}/timeline/extract`, { method: "POST", body: form });
        const data = await res.json();
        if (res.ok) { setEvents(prev => [...prev, ...data.events]); setCaseInfo(data); }
      } catch (e) { console.error(e); }
    } else {
      files.forEach(f => form.append("files", f));
      if (clientName) form.append("client_name", clientName);
      try {
        const res = await fetch(`${API_BASE}/timeline/extract-multiple`, { method: "POST", body: form });
        const data = await res.json();
        if (res.ok) { setEvents(prev => [...prev, ...data.events]); setCaseInfo(data); }
      } catch (e) { console.error(e); }
    }
    setLoading(false);
  };

  const eventColors = {
    filing:       { bg: "#E6F1FB", dot: "#378ADD", text: "#0C447C" },
    receipt:      { bg: "#E1F5EE", dot: "#1D9E75", text: "#085041" },
    biometrics:   { bg: "#EEEDFE", dot: "#7F77DD", text: "#3C3489" },
    rfe_issued:   { bg: "#FAEEDA", dot: "#EF9F27", text: "#633806" },
    rfe_response: { bg: "#FFF8E1", dot: "#BA7517", text: "#633806" },
    noid:         { bg: "#FCEBEB", dot: "#E24B4A", text: "#501313" },
    interview:    { bg: "#EEEDFE", dot: "#534AB7", text: "#26215C" },
    approval:     { bg: "#EAF3DE", dot: "#639922", text: "#173404" },
    denial:       { bg: "#FCEBEB", dot: "#E24B4A", text: "#501313" },
    transfer:     { bg: "#F1EFE8", dot: "#888780", text: "#2C2C2A" },
    other:        { bg: "#F1EFE8", dot: "#888780", text: "#2C2C2A" },
  };

  const inputStyle = {
    padding: "6px 12px", border: "1px solid rgba(0,0,0,0.15)", borderRadius: 8,
    fontSize: 13, outline: "none", fontFamily: "inherit",
  };

  const hasSidebar = clientName.trim() && (contextDocs.length > 0 || contextNotes);

  return (
    <div style={{ display: "flex", height: "100%", overflow: "hidden" }}>

      {/* ── Main timeline column ────────────────────────────────── */}
      <div style={{ flex: 1, overflow: "auto", padding: "1.5rem", maxWidth: hasSidebar ? "none" : 720, margin: hasSidebar ? 0 : "0 auto" }}>

        {/* Client name + action buttons */}
        <div style={{ display: "flex", gap: 8, marginBottom: 16, alignItems: "center", flexWrap: "wrap" }}>
          <input type="text" placeholder="Client name" value={clientName}
            onChange={e => setClientName(e.target.value)}
            onKeyDown={e => e.key === "Enter" && fetchClientTimeline(clientName)}
            style={{ ...inputStyle, width: 220 }} />
          <button onClick={() => fetchClientTimeline(clientName)}
            style={{ ...inputStyle, cursor: "pointer", background: "#E1F5EE", color: "#085041", border: "1px solid #9FE1CB", fontWeight: 500 }}>
            Load
          </button>
          <button onClick={() => setShowAddForm(!showAddForm)}
            style={{ ...inputStyle, cursor: "pointer", background: "#0F6E56", color: "#fff", border: "none", fontWeight: 500, padding: "6px 16px" }}>
            + Add event
          </button>
        </div>

        {/* ── USCIS Deadline Calculator ───────────────────────────── */}
        <div style={{
          marginBottom: 20, padding: "14px 16px",
          background: "#F0F7FF", border: "1px solid #BEDAF7", borderRadius: 12,
        }}>
          <p style={{ margin: "0 0 10px", fontSize: 12, fontWeight: 700, color: "#0C447C", letterSpacing: "0.05em", textTransform: "uppercase" }}>
            ⏱ USCIS Deadline Calculator
          </p>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <div>
              <label style={{ fontSize: 11, color: "rgba(0,0,0,0.45)", display: "block", marginBottom: 4 }}>Trigger event</label>
              <select value={deadlineCalc.type}
                onChange={e => setDeadlineCalc(p => ({ ...p, type: e.target.value }))}
                style={{ ...inputStyle, width: "100%", boxSizing: "border-box" }}>
                {Object.entries(DEADLINE_RULES).map(([k, v]) => (
                  <option key={k} value={k}>{v.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label style={{ fontSize: 11, color: "rgba(0,0,0,0.45)", display: "block", marginBottom: 4 }}>
                Date issued / received
              </label>
              <input type="date" value={deadlineCalc.date}
                onChange={e => setDeadlineCalc(p => ({ ...p, date: e.target.value }))}
                style={{ ...inputStyle, width: "100%", boxSizing: "border-box" }} />
            </div>
          </div>
          {calcResult && (
            <div style={{
              marginTop: 12, padding: "10px 14px", borderRadius: 8, display: "flex",
              gap: 12, alignItems: "center", flexWrap: "wrap",
              background: calcResult.daysLeft < 0 ? "#FCEBEB" : calcResult.daysLeft <= 30 ? "#FAEEDA" : "#EAF3DE",
              border: `1px solid ${calcResult.daysLeft < 0 ? "#F09595" : calcResult.daysLeft <= 30 ? "#EF9F27" : "#97C459"}`,
            }}>
              <span style={{ fontSize: 14, fontWeight: 700, color: calcResult.daysLeft < 0 ? "#791F1F" : calcResult.daysLeft <= 30 ? "#633806" : "#27500A" }}>
                {calcResult.daysLeft < 0
                  ? `⚠ OVERDUE by ${-calcResult.daysLeft} days`
                  : calcResult.daysLeft === 0 ? "⚠ DUE TODAY"
                  : `${calcResult.daysLeft} days remaining`}
              </span>
              <span style={{ fontSize: 12, color: "rgba(0,0,0,0.55)" }}>
                Response due:{" "}
                <strong style={{ color: "#2C2C2A" }}>
                  {calcResult.deadline.toLocaleDateString("en-US", { weekday: "short", month: "long", day: "numeric", year: "numeric" })}
                </strong>
              </span>
              <span style={{ fontSize: 11, color: "rgba(0,0,0,0.35)" }}>
                ({calcResult.rule.days}-day window)
              </span>
            </div>
          )}
        </div>

        {/* ── Add event form ──────────────────────────────────────── */}
        {showAddForm && (
          <div style={{ padding: 16, background: "#fff", border: "1px solid rgba(0,0,0,0.1)", borderRadius: 12, marginBottom: 16 }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 10 }}>
              <div>
                <label style={{ fontSize: 11, color: "rgba(0,0,0,0.4)", display: "block", marginBottom: 4 }}>Event type</label>
                <select value={newEvent.event_type}
                  onChange={e => setNewEvent(p => ({ ...p, event_type: e.target.value }))}
                  style={{ ...inputStyle, width: "100%" }}>
                  {EVENT_TYPES.map(t => <option key={t} value={t}>{EVENT_LABELS[t] || t}</option>)}
                </select>
              </div>
              <div>
                <label style={{ fontSize: 11, color: "rgba(0,0,0,0.4)", display: "block", marginBottom: 4 }}>Date</label>
                <input type="date" value={newEvent.date}
                  onChange={e => setNewEvent(p => ({ ...p, date: e.target.value }))}
                  style={{ ...inputStyle, width: "100%", boxSizing: "border-box" }} />
              </div>
            </div>
            <div style={{ marginBottom: 10 }}>
              <label style={{ fontSize: 11, color: "rgba(0,0,0,0.4)", display: "block", marginBottom: 4 }}>Description</label>
              <textarea value={newEvent.description}
                onChange={e => setNewEvent(p => ({ ...p, description: e.target.value }))}
                rows={2} placeholder="What happened in this case event..."
                style={{ ...inputStyle, width: "100%", resize: "vertical", boxSizing: "border-box" }} />
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 12 }}>
              <div>
                <label style={{ fontSize: 11, color: "rgba(0,0,0,0.4)", display: "block", marginBottom: 4 }}>Receipt number</label>
                <input type="text" placeholder="e.g. EAC2390012345" value={newEvent.receipt_number}
                  onChange={e => setNewEvent(p => ({ ...p, receipt_number: e.target.value }))}
                  style={{ ...inputStyle, width: "100%", boxSizing: "border-box" }} />
              </div>
              <div>
                <label style={{ fontSize: 11, color: "rgba(0,0,0,0.4)", display: "block", marginBottom: 4 }}>Form type</label>
                <input type="text" placeholder="e.g. I-485" value={newEvent.form_type}
                  onChange={e => setNewEvent(p => ({ ...p, form_type: e.target.value }))}
                  style={{ ...inputStyle, width: "100%", boxSizing: "border-box" }} />
              </div>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button onClick={addManualEvent}
                disabled={!clientName.trim() || !newEvent.description.trim()}
                style={{
                  padding: "8px 20px", borderRadius: 8, border: "none", fontSize: 13, fontWeight: 500, cursor: "pointer",
                  background: clientName.trim() && newEvent.description.trim() ? "#0F6E56" : "rgba(0,0,0,0.08)",
                  color: clientName.trim() && newEvent.description.trim() ? "#fff" : "rgba(0,0,0,0.3)",
                }}>Save event</button>
              <button onClick={() => setShowAddForm(false)}
                style={{ padding: "8px 16px", borderRadius: 8, border: "1px solid rgba(0,0,0,0.12)", background: "transparent", fontSize: 13, cursor: "pointer", color: "rgba(0,0,0,0.5)" }}>
                Cancel
              </button>
            </div>
          </div>
        )}

        <FileUploadZone onFilesSelected={extractTimeline} multiple
          label="Or upload USCIS notices (PDF, TXT, or DOCX) to auto-extract timeline" />
        {loading && <p style={{ textAlign: "center", color: "rgba(0,0,0,0.4)", fontSize: 14, marginTop: 16 }}>Processing…</p>}

        {events.length > 0 && (
          <>
            <div style={{ display: "flex", gap: 8, margin: "20px 0", flexWrap: "wrap", alignItems: "center" }}>
              {clientName && <StatusBadge type="info">{clientName}</StatusBadge>}
              {caseInfo?.case_type && <StatusBadge type="info">{caseInfo.case_type}</StatusBadge>}
              {caseInfo?.receipt_number && <StatusBadge type="success">{caseInfo.receipt_number}</StatusBadge>}
              <StatusBadge type="info">{events.length} events</StatusBadge>
            </div>

            <div style={{ position: "relative", paddingLeft: 28 }}>
              <div style={{ position: "absolute", left: 9, top: 8, bottom: 8, width: 2, background: "rgba(0,0,0,0.08)", borderRadius: 1 }} />

              {events.map((evt, i) => {
                const c = eventColors[evt.event_type] || eventColors.other;
                const days = daysFromNow(evt.date);

                // Auto-calculate response deadline for events that trigger hard deadlines
                const deadlineRule = DEADLINE_RULES[evt.event_type];
                const responseDeadline = deadlineRule ? addDaysToDate(evt.date, deadlineRule.days) : null;
                const deadlineDaysLeft = responseDeadline
                  ? (() => { const today = new Date(); today.setHours(0,0,0,0); return Math.ceil((responseDeadline - today) / 86400000); })()
                  : null;

                return (
                  <div key={i} style={{ position: "relative", marginBottom: 16 }}>
                    <div style={{
                      position: "absolute", left: -22, top: 6, width: 12, height: 12,
                      borderRadius: "50%", background: c.dot,
                      border: "2px solid #fff", boxShadow: "0 0 0 2px rgba(0,0,0,0.06)",
                    }} />
                    <div style={{ padding: "10px 14px", background: c.bg, borderRadius: 10, borderLeft: `3px solid ${c.dot}` }}>

                      {/* Event header row */}
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4, gap: 8, flexWrap: "wrap" }}>
                        <span style={{ fontSize: 12, fontWeight: 600, color: c.text }}>
                          {EVENT_LABELS[evt.event_type] || evt.event_type.replace(/_/g, " ")}
                        </span>
                        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                          {evt.date && (
                            <span style={{ fontSize: 11, color: "rgba(0,0,0,0.4)" }}>
                              {new Date(evt.date.replace(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/, "$3-$1-$2")).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) || evt.date}
                            </span>
                          )}
                          {days !== null && (
                            <StatusBadge type={days >= 0 ? "info" : "info"}>
                              {days === 0 ? "Today" : days > 0 ? `in ${days}d` : `${-days}d ago`}
                            </StatusBadge>
                          )}
                        </div>
                      </div>

                      <p style={{ fontSize: 13, color: "#2C2C2A", lineHeight: 1.5, margin: 0 }}>{evt.description}</p>

                      {/* Auto deadline row — shown for RFE, NOID, NOIR events */}
                      {responseDeadline && (
                        <div style={{
                          marginTop: 8, padding: "6px 10px", borderRadius: 6, display: "flex",
                          gap: 8, alignItems: "center", flexWrap: "wrap",
                          background: deadlineDaysLeft !== null && deadlineDaysLeft <= 30
                            ? "rgba(226,75,74,0.08)" : "rgba(0,0,0,0.04)",
                        }}>
                          <span style={{ fontSize: 11, color: "rgba(0,0,0,0.5)" }}>⏰ Response deadline:</span>
                          <strong style={{ fontSize: 11, color: "#2C2C2A" }}>
                            {responseDeadline.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
                          </strong>
                          {deadlineDaysLeft !== null && (
                            <StatusBadge type={urgencyBadgeType(deadlineDaysLeft)}>
                              {deadlineDaysLeft < 0
                                ? `Overdue ${-deadlineDaysLeft}d`
                                : deadlineDaysLeft === 0 ? "Due today"
                                : `${deadlineDaysLeft}d left`}
                            </StatusBadge>
                          )}
                        </div>
                      )}

                      {(evt.receipt_number || evt.form_type) && (
                        <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
                          {evt.receipt_number && <StatusBadge type="info">{evt.receipt_number}</StatusBadge>}
                          {evt.form_type && <StatusBadge type="info">{evt.form_type}</StatusBadge>}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        )}

        {!loading && events.length === 0 && !showAddForm && (
          <p style={{ textAlign: "center", fontSize: 13, color: "rgba(0,0,0,0.35)", marginTop: 24 }}>
            Enter a client name and press Load, add events manually, or upload USCIS documents.
          </p>
        )}
      </div>

      {/* ── Client context sidebar ────────────────────────────── */}
      {hasSidebar && (
        <div style={{ width: 300, flexShrink: 0, borderLeft: "1px solid rgba(0,0,0,0.08)", display: "flex", flexDirection: "column", background: "#FAFAF7" }}>
          <div style={{ padding: "10px 14px", borderBottom: "1px solid rgba(0,0,0,0.08)", background: "#fff" }}>
            <p style={{ margin: "0 0 6px", fontSize: 12, fontWeight: 600, color: "rgba(0,0,0,0.5)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
              Client Profile — {clientName}
            </p>
            <div style={{ display: "flex", gap: 4 }}>
              {[{ key: "docs", label: "📄 Docs" }, { key: "notes", label: "📌 Notes" }, { key: "ask", label: "💬 Ask" }].map(t => (
                <button key={t.key} onClick={() => setSidebarTab(t.key)} style={{
                  padding: "3px 10px", borderRadius: 6, fontSize: 12, fontWeight: 500, cursor: "pointer",
                  border: sidebarTab === t.key ? "1.5px solid #0F6E56" : "1px solid rgba(0,0,0,0.12)",
                  background: sidebarTab === t.key ? "#E1F5EE" : "transparent",
                  color: sidebarTab === t.key ? "#085041" : "rgba(0,0,0,0.45)",
                }}>{t.label}</button>
              ))}
            </div>
          </div>

          <div style={{ flex: 1, overflow: "auto", padding: "12px 14px" }}>
            {sidebarTab === "docs" && (
              <div>
                <p style={{ fontSize: 11, color: "rgba(0,0,0,0.4)", marginBottom: 10 }}>
                  Documents stored for <strong>{clientName}</strong>:
                </p>
                {contextDocs.length > 0 ? contextDocs.map(fn => (
                  <div key={fn} style={{ padding: "8px 10px", marginBottom: 6, background: "#E1F5EE", borderRadius: 8, fontSize: 12, color: "#085041", borderLeft: "3px solid #1D9E75" }}>
                    📄 {fn}
                  </div>
                )) : (
                  <p style={{ fontSize: 12, color: "rgba(0,0,0,0.35)" }}>
                    No documents yet. Go to <strong>Document Q&amp;A</strong> to upload.
                  </p>
                )}
              </div>
            )}

            {sidebarTab === "notes" && (
              <div>
                {contextNotes ? (
                  <>
                    <p style={{ fontSize: 11, color: "rgba(0,0,0,0.4)", marginBottom: 8 }}>
                      Notes from Document Q&amp;A for {clientName}:
                    </p>
                    <div style={{ whiteSpace: "pre-wrap", fontSize: 13, lineHeight: 1.7, color: "#2C2C2A", background: "#FFFEF5", padding: 12, borderRadius: 8, border: "1px solid rgba(0,0,0,0.08)" }}>
                      {contextNotes}
                    </div>
                  </>
                ) : (
                  <p style={{ fontSize: 12, color: "rgba(0,0,0,0.35)" }}>
                    No notes yet. Open <strong>Document Q&amp;A</strong>, select this client, and add notes there.
                  </p>
                )}
              </div>
            )}

            {sidebarTab === "ask" && (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <p style={{ fontSize: 11, color: "rgba(0,0,0,0.4)", margin: 0 }}>
                  Ask about {clientName}'s documents without switching tabs:
                </p>
                <textarea value={quickQ} onChange={e => setQuickQ(e.target.value)}
                  onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); askQuick(); } }}
                  rows={3} placeholder="e.g. What is the current case status?"
                  style={{ padding: 10, border: "1px solid rgba(0,0,0,0.15)", borderRadius: 8, fontSize: 13, resize: "none", fontFamily: "inherit", outline: "none" }} />
                <button onClick={askQuick} disabled={quickAsking || !quickQ.trim() || !contextDocs.length}
                  style={{
                    padding: "8px", borderRadius: 8, border: "none", fontSize: 13, fontWeight: 500, cursor: "pointer",
                    background: quickQ.trim() && contextDocs.length ? "#0F6E56" : "rgba(0,0,0,0.08)",
                    color: quickQ.trim() && contextDocs.length ? "#fff" : "rgba(0,0,0,0.3)",
                  }}>
                  {quickAsking ? "Asking…" : "Ask"}
                </button>
                {!contextDocs.length && (
                  <p style={{ fontSize: 11, color: "rgba(0,0,0,0.35)", margin: 0 }}>Upload documents for this client first.</p>
                )}
                {quickA && (
                  <div style={{ padding: 10, borderRadius: 8, fontSize: 12, lineHeight: 1.6, background: quickA.error ? "#FCEBEB" : "#F6F5F0", color: quickA.error ? "#791F1F" : "#2C2C2A" }}>
                    <MarkdownText text={quickA.text} />
                    {quickA.confidence != null && (
                      <div style={{ marginTop: 6 }}>
                        <StatusBadge type={quickA.confidence > 0.7 ? "success" : "warning"}>
                          Confidence: {Math.round(quickA.confidence * 100)}%
                        </StatusBadge>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── RFE Tracker ─────────────────────────────────────────────────────────────

const RFE_STATUSES = [
  { value: "open",        label: "Open",       color: "#EF9F27", bg: "#FAEEDA", border: "#EF9F27" },
  { value: "in_progress", label: "In Progress", color: "#378ADD", bg: "#E6F1FB", border: "#85B7EB" },
  { value: "responded",   label: "Responded",  color: "#1D9E75", bg: "#E1F5EE", border: "#9FE1CB" },
  { value: "approved",    label: "Approved ✓", color: "#27500A", bg: "#EAF3DE", border: "#97C459" },
  { value: "denied",      label: "Denied",     color: "#791F1F", bg: "#FCEBEB", border: "#F09595" },
];

const CASE_TYPES = ["H-1B", "I-130", "I-140", "I-485", "I-765", "N-400", "Asylum", "OPT", "Other"];

const SERVICE_CENTERS = [
  "California Service Center (CSC)",
  "Nebraska Service Center (NSC)",
  "Texas Service Center (TSC)",
  "Vermont Service Center (VSC)",
  "Potomac Service Center (PSC)",
  "National Benefits Center (NBC)",
  "Other",
];

/** Returns { label, bg, border, text } for a days_remaining value. */
function deadlineStyle(days) {
  if (days === null || days === undefined) return { label: "No deadline", bg: "#F1EFE8", border: "#C8C6BE", text: "#888780" };
  if (days < 0)  return { label: `Overdue ${-days}d`,     bg: "#FCEBEB", border: "#F09595", text: "#791F1F" };
  if (days === 0) return { label: "Due TODAY",             bg: "#FCEBEB", border: "#E24B4A", text: "#791F1F" };
  if (days <= 14) return { label: `${days}d left`,         bg: "#FCEBEB", border: "#F09595", text: "#791F1F" };
  if (days <= 30) return { label: `${days}d left`,         bg: "#FAEEDA", border: "#EF9F27", text: "#633806" };
  return             { label: `${days}d left`,             bg: "#EAF3DE", border: "#97C459", text: "#27500A" };
}

function DeadlinePill({ days }) {
  const s = deadlineStyle(days);
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", fontSize: 11, fontWeight: 700,
      padding: "3px 10px", borderRadius: 100,
      background: s.bg, border: `1px solid ${s.border}`, color: s.text,
      whiteSpace: "nowrap",
    }}>{s.label}</span>
  );
}

function StatusPill({ status }) {
  const s = RFE_STATUSES.find(x => x.value === status) || RFE_STATUSES[0];
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", fontSize: 11, fontWeight: 600,
      padding: "2px 10px", borderRadius: 100,
      background: s.bg, border: `1px solid ${s.border}`, color: s.color,
    }}>{s.label}</span>
  );
}

const EMPTY_FORM = {
  client_name: "", case_type: "", receipt_number: "", service_center: "",
  rfe_issue_date: "", response_deadline: "", notes: "",
};

function RFETracker() {
  const [cases, setCases] = useState([]);
  const [selectedCase, setSelectedCase] = useState(null); // full case object with issues
  const [showNewForm, setShowNewForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [newIssueText, setNewIssueText] = useState("");
  const [extracting, setExtracting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loadingCases, setLoadingCases] = useState(true);
  const extractRef = useRef(null);
  const extractModeRef = useRef("quick"); // tracks which button triggered the file input

  const inputStyle = {
    padding: "6px 10px", border: "1px solid rgba(0,0,0,0.15)", borderRadius: 8,
    fontSize: 13, outline: "none", fontFamily: "inherit", boxSizing: "border-box",
  };

  // ── Data fetching ───────────────────────────────────────────────────

  const loadCases = useCallback(async () => {
    setLoadingCases(true);
    try {
      const res = await fetch(`${API_BASE}/rfe/cases`);
      if (res.ok) setCases(await res.json());
    } catch (e) { console.error("Failed to load RFE cases", e); }
    setLoadingCases(false);
  }, []);

  const loadCase = useCallback(async (caseId) => {
    try {
      const res = await fetch(`${API_BASE}/rfe/cases/${caseId}`);
      if (res.ok) {
        const c = await res.json();
        setSelectedCase(c);
        // Sync updated case in list
        setCases(prev => prev.map(x => x.id === c.id ? { ...x, ...c } : x));
      }
    } catch (e) { console.error(e); }
  }, []);

  // Initial load. `loadCases` is wrapped in useCallback with [] deps so the
  // identity is stable — this effect runs exactly once on mount. The lint
  // rule fires because loadCases internally calls setLoadingCases() before
  // its await; that's intentional (UI shows the loading state immediately)
  // and not the cascading-render anti-pattern the rule is designed to catch.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { loadCases(); }, [loadCases]);

  // ── Case creation ───────────────────────────────────────────────────

  const createCase = async () => {
    if (!form.client_name.trim()) return;
    setSaving(true);
    try {
      const body = {
        client_name: form.client_name.trim(),
        case_type: form.case_type || null,
        receipt_number: form.receipt_number || null,
        service_center: form.service_center || null,
        rfe_issue_date: form.rfe_issue_date || null,
        response_deadline: form.response_deadline || null,
        notes: form.notes,
      };
      const res = await fetch(`${API_BASE}/rfe/cases`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      if (res.ok) {
        const newCase = await res.json();
        setCases(prev => {
          const updated = [...prev, newCase];
          // Re-sort by deadline urgency (nulls last)
          return updated.sort((a, b) => {
            if (!a.response_deadline && !b.response_deadline) return 0;
            if (!a.response_deadline) return 1;
            if (!b.response_deadline) return -1;
            return a.response_deadline.localeCompare(b.response_deadline);
          });
        });
        setForm(EMPTY_FORM);
        setShowNewForm(false);
        // Auto-select the new case
        setSelectedCase({ ...newCase, issues: [] });
      }
    } catch (e) { console.error(e); }
    setSaving(false);
  };

  // ── Status update ───────────────────────────────────────────────────

  const updateStatus = async (caseId, status) => {
    try {
      const res = await fetch(`${API_BASE}/rfe/cases/${caseId}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      if (res.ok) {
        const updated = await res.json();
        setCases(prev => prev.map(c => c.id === caseId ? { ...c, status } : c));
        if (selectedCase?.id === caseId) setSelectedCase(prev => ({ ...prev, status, ...updated }));
      }
    } catch (e) { console.error(e); }
  };

  // ── Notes update (debounced on blur) ────────────────────────────────

  const saveNotes = async (caseId, notes) => {
    try {
      await fetch(`${API_BASE}/rfe/cases/${caseId}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ notes }),
      });
      setCases(prev => prev.map(c => c.id === caseId ? { ...c, notes } : c));
    } catch (e) { console.error(e); }
  };

  // ── Delete case ─────────────────────────────────────────────────────

  const deleteCase = async (caseId) => {
    if (!window.confirm("Delete this RFE case and all its checklist items? This cannot be undone.")) return;
    try {
      await fetch(`${API_BASE}/rfe/cases/${caseId}`, { method: "DELETE" });
      setCases(prev => prev.filter(c => c.id !== caseId));
      if (selectedCase?.id === caseId) setSelectedCase(null);
    } catch (e) { console.error(e); }
  };

  // ── Issue management ────────────────────────────────────────────────

  const addIssue = async () => {
    const title = newIssueText.trim();
    if (!title || !selectedCase) return;
    try {
      const res = await fetch(`${API_BASE}/rfe/cases/${selectedCase.id}/issues`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      });
      if (res.ok) {
        const issue = await res.json();
        setSelectedCase(prev => ({ ...prev, issues: [...prev.issues, issue] }));
        setNewIssueText("");
      }
    } catch (e) { console.error(e); }
  };

  const toggleIssue = async (issueId, currentCompleted) => {
    if (!selectedCase) return;
    const completed = !currentCompleted;
    try {
      const res = await fetch(`${API_BASE}/rfe/cases/${selectedCase.id}/issues/${issueId}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ completed }),
      });
      if (res.ok) {
        setSelectedCase(prev => ({
          ...prev,
          issues: prev.issues.map(i => i.id === issueId ? { ...i, completed: completed ? 1 : 0 } : i),
        }));
      }
    } catch (e) { console.error(e); }
  };

  const deleteIssue = async (issueId) => {
    if (!selectedCase) return;
    try {
      await fetch(`${API_BASE}/rfe/cases/${selectedCase.id}/issues/${issueId}`, { method: "DELETE" });
      setSelectedCase(prev => ({ ...prev, issues: prev.issues.filter(i => i.id !== issueId) }));
    } catch (e) { console.error(e); }
  };

  // ── PDF auto-extract ────────────────────────────────────────────────

  const handleExtractFile = async (e) => {
    const file = e.target.files?.[0];
    if (!file || !selectedCase) return;
    setExtracting(extractModeRef.current); // "quick" | "ai" — drives button label
    const formData = new FormData();
    formData.append("file", file);
    const mode = extractModeRef.current;
    try {
      const res = await fetch(
        `${API_BASE}/rfe/cases/${selectedCase.id}/extract-issues?mode=${mode}`,
        { method: "POST", body: formData }
      );
      if (res.ok) {
        await loadCase(selectedCase.id);
      }
    } catch (err) { console.error(err); }
    setExtracting(false);
    if (extractRef.current) extractRef.current.value = "";
  };

  // ── Derived values ──────────────────────────────────────────────────

  const issuesDone = selectedCase?.issues?.filter(i => i.completed).length ?? 0;
  const issuesTotal = selectedCase?.issues?.length ?? 0;
  const issuesPct = issuesTotal > 0 ? Math.round((issuesDone / issuesTotal) * 100) : 0;

  // Urgency sort: overdue / critical at top, resolved at bottom
  const urgentCases = cases.filter(c => !["approved", "denied"].includes(c.status));
  const closedCases = cases.filter(c => ["approved", "denied"].includes(c.status));

  // ── Render ──────────────────────────────────────────────────────────

  return (
    <div style={{ display: "flex", height: "100%", overflow: "hidden", fontFamily: "inherit" }}>

      {/* ── LEFT: Cases List ──────────────────────────────────────── */}
      <div style={{
        width: 300, flexShrink: 0, borderRight: "1px solid rgba(0,0,0,0.08)",
        display: "flex", flexDirection: "column", background: "#FAFAF7",
      }}>
        {/* List header */}
        <div style={{
          padding: "12px 14px", borderBottom: "1px solid rgba(0,0,0,0.08)",
          display: "flex", justifyContent: "space-between", alignItems: "center", background: "#fff",
        }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: "rgba(0,0,0,0.5)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
            RFE Cases {cases.length > 0 && `(${cases.length})`}
          </span>
          <button
            onClick={() => { setShowNewForm(true); setSelectedCase(null); }}
            style={{
              padding: "4px 12px", borderRadius: 8, border: "none", fontSize: 12, fontWeight: 600,
              background: "#0F6E56", color: "#fff", cursor: "pointer",
            }}>+ New</button>
        </div>

        {/* Cases scroll */}
        <div style={{ flex: 1, overflow: "auto", padding: "8px 0" }}>
          {loadingCases && (
            <p style={{ fontSize: 12, color: "rgba(0,0,0,0.35)", textAlign: "center", padding: "2rem 0" }}>Loading…</p>
          )}

          {!loadingCases && cases.length === 0 && (
            <div style={{ padding: "2rem 1rem", textAlign: "center" }}>
              <div style={{ fontSize: 28, marginBottom: 8 }}>📋</div>
              <p style={{ fontSize: 12, color: "rgba(0,0,0,0.4)", lineHeight: 1.6, margin: 0 }}>
                No RFE cases yet.<br />Click <strong>+ New</strong> to add the first one.
              </p>
            </div>
          )}

          {/* Active/pending cases */}
          {urgentCases.length > 0 && urgentCases.map(c => {
            // Note: <DeadlinePill /> below handles its own urgency styling.
            // Earlier versions computed `deadlineStyle(c.days_remaining)` here;
            // that's dead code now.
            const isSelected = selectedCase?.id === c.id;
            return (
              <button
                key={c.id}
                onClick={() => { setShowNewForm(false); loadCase(c.id); }}
                style={{
                  display: "block", width: "100%", textAlign: "left",
                  padding: "10px 14px", margin: 0, border: "none",
                  borderLeft: isSelected ? "3px solid #0F6E56" : "3px solid transparent",
                  background: isSelected ? "#E1F5EE" : "transparent",
                  cursor: "pointer", transition: "background 0.1s",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 6, marginBottom: 4 }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: "#2C2C2A", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>
                    {c.client_name}
                  </span>
                  <DeadlinePill days={c.days_remaining} />
                </div>
                <div style={{ display: "flex", gap: 5, flexWrap: "wrap", alignItems: "center" }}>
                  {c.case_type && (
                    <span style={{ fontSize: 10, fontWeight: 600, padding: "1px 7px", borderRadius: 100, background: "#E6F1FB", color: "#0C447C", border: "1px solid #85B7EB" }}>
                      {c.case_type}
                    </span>
                  )}
                  <StatusPill status={c.status} />
                </div>
                {c.receipt_number && (
                  <div style={{ fontSize: 10, color: "rgba(0,0,0,0.35)", marginTop: 4, fontFamily: "'DM Mono', monospace" }}>{c.receipt_number}</div>
                )}
              </button>
            );
          })}

          {/* Closed cases section */}
          {closedCases.length > 0 && (
            <>
              <div style={{ padding: "8px 14px 4px", fontSize: 10, fontWeight: 600, color: "rgba(0,0,0,0.3)", textTransform: "uppercase", letterSpacing: "0.07em" }}>
                Closed
              </div>
              {closedCases.map(c => {
                const isSelected = selectedCase?.id === c.id;
                return (
                  <button
                    key={c.id}
                    onClick={() => { setShowNewForm(false); loadCase(c.id); }}
                    style={{
                      display: "block", width: "100%", textAlign: "left",
                      padding: "8px 14px", margin: 0, border: "none",
                      borderLeft: isSelected ? "3px solid #0F6E56" : "3px solid transparent",
                      background: isSelected ? "#F0F7F5" : "transparent",
                      cursor: "pointer", opacity: 0.6,
                    }}
                  >
                    <div style={{ fontSize: 12, fontWeight: 600, color: "#2C2C2A", marginBottom: 2 }}>{c.client_name}</div>
                    <div style={{ display: "flex", gap: 4 }}>
                      {c.case_type && <span style={{ fontSize: 10, color: "rgba(0,0,0,0.4)" }}>{c.case_type}</span>}
                      <StatusPill status={c.status} />
                    </div>
                  </button>
                );
              })}
            </>
          )}
        </div>
      </div>

      {/* ── RIGHT: Detail / New Form ──────────────────────────────── */}
      <div style={{ flex: 1, overflow: "auto", display: "flex", flexDirection: "column" }}>

        {/* ── NEW CASE FORM ── */}
        {showNewForm && (
          <div style={{ padding: "1.5rem", maxWidth: 680, margin: "0 auto", width: "100%" }}>
            <h3 style={{ margin: "0 0 20px", fontSize: 15, fontWeight: 700, color: "#2C2C2A" }}>
              New RFE Case
            </h3>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
              <div style={{ gridColumn: "1 / -1" }}>
                <label style={{ fontSize: 11, color: "rgba(0,0,0,0.4)", display: "block", marginBottom: 4, fontWeight: 600 }}>Client Name *</label>
                <input
                  autoFocus type="text" placeholder="e.g. John Smith"
                  value={form.client_name} onChange={e => setForm(p => ({ ...p, client_name: e.target.value }))}
                  style={{ ...inputStyle, width: "100%" }} />
              </div>
              <div>
                <label style={{ fontSize: 11, color: "rgba(0,0,0,0.4)", display: "block", marginBottom: 4, fontWeight: 600 }}>Case Type</label>
                <select value={form.case_type} onChange={e => setForm(p => ({ ...p, case_type: e.target.value }))}
                  style={{ ...inputStyle, width: "100%", background: "#fff" }}>
                  <option value="">— select —</option>
                  {CASE_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
              <div>
                <label style={{ fontSize: 11, color: "rgba(0,0,0,0.4)", display: "block", marginBottom: 4, fontWeight: 600 }}>Receipt Number</label>
                <input type="text" placeholder="e.g. EAC2390012345"
                  value={form.receipt_number} onChange={e => setForm(p => ({ ...p, receipt_number: e.target.value }))}
                  style={{ ...inputStyle, width: "100%" }} />
              </div>
              <div>
                <label style={{ fontSize: 11, color: "rgba(0,0,0,0.4)", display: "block", marginBottom: 4, fontWeight: 600 }}>RFE Issue Date</label>
                <input type="date" value={form.rfe_issue_date}
                  onChange={e => setForm(p => ({ ...p, rfe_issue_date: e.target.value }))}
                  style={{ ...inputStyle, width: "100%" }} />
              </div>
              <div>
                <label style={{ fontSize: 11, color: "rgba(0,0,0,0.4)", display: "block", marginBottom: 4, fontWeight: 600 }}>
                  Response Deadline
                  <span style={{ marginLeft: 4, fontWeight: 400, fontSize: 10 }}>(auto: +87 days)</span>
                </label>
                <input type="date" value={form.response_deadline}
                  onChange={e => setForm(p => ({ ...p, response_deadline: e.target.value }))}
                  style={{ ...inputStyle, width: "100%" }} />
              </div>
              <div style={{ gridColumn: "1 / -1" }}>
                <label style={{ fontSize: 11, color: "rgba(0,0,0,0.4)", display: "block", marginBottom: 4, fontWeight: 600 }}>Service Center</label>
                <select value={form.service_center} onChange={e => setForm(p => ({ ...p, service_center: e.target.value }))}
                  style={{ ...inputStyle, width: "100%", background: "#fff" }}>
                  <option value="">— select —</option>
                  {SERVICE_CENTERS.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div style={{ gridColumn: "1 / -1" }}>
                <label style={{ fontSize: 11, color: "rgba(0,0,0,0.4)", display: "block", marginBottom: 4, fontWeight: 600 }}>Notes</label>
                <textarea rows={3} placeholder="Case notes, attorney assignment, key context…"
                  value={form.notes} onChange={e => setForm(p => ({ ...p, notes: e.target.value }))}
                  style={{ ...inputStyle, width: "100%", resize: "vertical" }} />
              </div>
            </div>

            <div style={{ display: "flex", gap: 8 }}>
              <button onClick={createCase} disabled={saving || !form.client_name.trim()}
                style={{
                  padding: "9px 24px", borderRadius: 8, border: "none", fontSize: 13, fontWeight: 600, cursor: "pointer",
                  background: form.client_name.trim() ? "#0F6E56" : "rgba(0,0,0,0.08)",
                  color: form.client_name.trim() ? "#fff" : "rgba(0,0,0,0.3)",
                }}>
                {saving ? "Saving…" : "Create Case"}
              </button>
              <button onClick={() => { setShowNewForm(false); setForm(EMPTY_FORM); }}
                style={{ padding: "9px 18px", borderRadius: 8, border: "1px solid rgba(0,0,0,0.12)", background: "transparent", fontSize: 13, cursor: "pointer", color: "rgba(0,0,0,0.5)" }}>
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* ── CASE DETAIL ── */}
        {selectedCase && !showNewForm && (
          <div style={{ padding: "1.5rem", maxWidth: 760, margin: "0 auto", width: "100%" }}>

            {/* Header row */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16, gap: 12 }}>
              <div>
                <h2 style={{ margin: "0 0 4px", fontSize: 18, fontWeight: 700, color: "#2C2C2A" }}>
                  {selectedCase.client_name}
                </h2>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
                  {selectedCase.case_type && (
                    <span style={{ fontSize: 11, fontWeight: 600, padding: "2px 10px", borderRadius: 100, background: "#E6F1FB", color: "#0C447C", border: "1px solid #85B7EB" }}>
                      {selectedCase.case_type}
                    </span>
                  )}
                  {selectedCase.receipt_number && (
                    <span style={{ fontSize: 11, fontFamily: "'DM Mono', monospace", padding: "2px 8px", borderRadius: 6, background: "#F1EFE8", color: "#2C2C2A", border: "1px solid rgba(0,0,0,0.1)" }}>
                      {selectedCase.receipt_number}
                    </span>
                  )}
                  {selectedCase.service_center && (
                    <span style={{ fontSize: 11, color: "rgba(0,0,0,0.4)" }}>{selectedCase.service_center}</span>
                  )}
                </div>
              </div>
              <button
                onClick={() => deleteCase(selectedCase.id)}
                title="Delete this case"
                style={{ padding: "6px 10px", borderRadius: 8, border: "1px solid rgba(226,75,74,0.3)", background: "transparent", color: "#E24B4A", fontSize: 12, cursor: "pointer" }}
              >Delete</button>
            </div>

            {/* Status + Deadline row */}
            <div style={{
              display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 20,
              padding: "14px 16px", background: "#fff", borderRadius: 12, border: "1px solid rgba(0,0,0,0.08)",
            }}>
              <div>
                <label style={{ fontSize: 11, color: "rgba(0,0,0,0.4)", display: "block", marginBottom: 6, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  Status
                </label>
                <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
                  {RFE_STATUSES.map(s => (
                    <button key={s.value} onClick={() => updateStatus(selectedCase.id, s.value)}
                      style={{
                        padding: "4px 12px", borderRadius: 100, fontSize: 11, fontWeight: 600, cursor: "pointer",
                        border: `1.5px solid ${s.border}`,
                        background: selectedCase.status === s.value ? s.bg : "transparent",
                        color: selectedCase.status === s.value ? s.color : "rgba(0,0,0,0.35)",
                        transition: "all 0.1s",
                      }}>{s.label}</button>
                  ))}
                </div>
              </div>
              <div>
                <label style={{ fontSize: 11, color: "rgba(0,0,0,0.4)", display: "block", marginBottom: 6, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  Response Deadline
                </label>
                {selectedCase.response_deadline ? (
                  <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                    <span style={{ fontSize: 14, fontWeight: 700, color: "#2C2C2A" }}>
                      {new Date(selectedCase.response_deadline + "T12:00:00").toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" })}
                    </span>
                    <DeadlinePill days={selectedCase.days_remaining} />
                  </div>
                ) : (
                  <span style={{ fontSize: 12, color: "rgba(0,0,0,0.3)" }}>No deadline set</span>
                )}
                {selectedCase.rfe_issue_date && (
                  <div style={{ fontSize: 11, color: "rgba(0,0,0,0.35)", marginTop: 4 }}>
                    RFE issued: {new Date(selectedCase.rfe_issue_date + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
                  </div>
                )}
              </div>
            </div>

            {/* ── Upload RFE Notice — dedicated visible section ── */}
            <div style={{
              marginBottom: 16, padding: "12px 14px",
              background: "#F0F7FF", border: "1px solid #BEDAF7", borderRadius: 10,
            }}>
              <p style={{ margin: "0 0 8px", fontSize: 11, fontWeight: 700, color: "#0C447C", letterSpacing: "0.05em", textTransform: "uppercase" }}>
                Upload RFE Notice to Extract Issues
              </p>
              <p style={{ margin: "0 0 10px", fontSize: 12, color: "#3A6A9A", lineHeight: 1.5 }}>
                Upload the RFE document to automatically populate the checklist below.
              </p>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {/* Hidden file input shared by both buttons */}
                <input
                  ref={extractRef}
                  type="file"
                  accept=".pdf,.txt,.docx"
                  hidden
                  onChange={handleExtractFile}
                  disabled={!!extracting}
                />

                {/* Quick Extract — regex, fast, no tokens */}
                <button
                  disabled={!!extracting}
                  onClick={() => { extractModeRef.current = "quick"; extractRef.current?.click(); }}
                  title="Fast text-based extraction — best for clean, searchable PDFs. No API tokens used."
                  style={{
                    padding: "7px 16px", borderRadius: 8, fontSize: 12, fontWeight: 600, cursor: "pointer",
                    border: "1px solid rgba(0,0,0,0.18)",
                    background: extracting === "quick" ? "#E6F1FB" : "#fff",
                    color: extracting === "quick" ? "#0C447C" : "#2C2C2A",
                    display: "flex", alignItems: "center", gap: 5,
                    opacity: !!extracting && extracting !== "quick" ? 0.4 : 1,
                  }}
                >
                  {extracting === "quick" ? "Extracting…" : "⚡ Quick Extract"}
                </button>

                {/* AI Extract — Gemini vision, reads scanned/image PDFs */}
                <button
                  disabled={!!extracting}
                  onClick={() => { extractModeRef.current = "ai"; extractRef.current?.click(); }}
                  title="Gemini-powered — reads scanned or image-based PDFs that Quick Extract can't parse. Uses API tokens."
                  style={{
                    padding: "7px 16px", borderRadius: 8, fontSize: 12, fontWeight: 600, cursor: "pointer",
                    border: "1.5px solid #378ADD",
                    background: extracting === "ai" ? "#E6F1FB" : "rgba(55,138,221,0.08)",
                    color: extracting === "ai" ? "#0C447C" : "#1A6BB5",
                    display: "flex", alignItems: "center", gap: 5,
                    opacity: !!extracting && extracting !== "ai" ? 0.4 : 1,
                  }}
                >
                  {extracting === "ai" ? "✨ AI Reading…" : "✨ AI Extract"}
                </button>

                <span style={{ fontSize: 11, color: "#3A6A9A", alignSelf: "center", fontStyle: "italic" }}>
                  {extracting ? "Processing document…" : "PDF, TXT, or DOCX"}
                </span>
              </div>
            </div>

            {/* Issues Checklist */}
            <div style={{ marginBottom: 20 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: "#2C2C2A" }}>
                  Issues Checklist
                  {issuesTotal > 0 && (
                    <span style={{ marginLeft: 8, fontSize: 11, fontWeight: 500, color: "rgba(0,0,0,0.4)" }}>
                      {issuesDone}/{issuesTotal} resolved
                    </span>
                  )}
                </span>
              </div>

              {/* Progress bar */}
              {issuesTotal > 0 && (
                <div style={{ height: 5, background: "rgba(0,0,0,0.06)", borderRadius: 3, marginBottom: 12, overflow: "hidden" }}>
                  <div style={{
                    height: "100%", borderRadius: 3, transition: "width 0.3s ease",
                    background: issuesPct === 100 ? "#27500A" : issuesPct >= 60 ? "#1D9E75" : "#EF9F27",
                    width: `${issuesPct}%`,
                  }} />
                </div>
              )}

              {/* Issue items */}
              {issuesTotal === 0 && (
                <p style={{ fontSize: 12, color: "rgba(0,0,0,0.35)", margin: "0 0 10px", lineHeight: 1.6 }}>
                  No issues yet. Add items manually below, or upload the RFE notice PDF to auto-extract them.
                </p>
              )}

              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {selectedCase.issues.map(issue => (
                  <div key={issue.id} style={{
                    display: "flex", alignItems: "flex-start", gap: 10, padding: "8px 10px",
                    borderRadius: 8, background: issue.completed ? "#F6FFF6" : "#fff",
                    border: `1px solid ${issue.completed ? "rgba(39,80,10,0.15)" : "rgba(0,0,0,0.09)"}`,
                    transition: "background 0.2s",
                  }}>
                    <input
                      type="checkbox"
                      checked={!!issue.completed}
                      onChange={() => toggleIssue(issue.id, !!issue.completed)}
                      style={{ marginTop: 2, width: 15, height: 15, accentColor: "#0F6E56", cursor: "pointer", flexShrink: 0 }}
                    />
                    <span style={{
                      flex: 1, fontSize: 13, lineHeight: 1.5, color: "#2C2C2A",
                      textDecoration: issue.completed ? "line-through" : "none",
                      opacity: issue.completed ? 0.55 : 1,
                    }}>
                      {issue.title}
                    </span>
                    <button
                      onClick={() => deleteIssue(issue.id)}
                      style={{ background: "none", border: "none", cursor: "pointer", fontSize: 13, color: "rgba(0,0,0,0.25)", padding: "0 2px", flexShrink: 0, lineHeight: 1 }}
                      title="Remove this issue"
                    >✕</button>
                  </div>
                ))}
              </div>

              {/* Add issue input */}
              <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
                <input
                  type="text"
                  placeholder="Add an issue or evidence item…"
                  value={newIssueText}
                  onChange={e => setNewIssueText(e.target.value)}
                  onKeyDown={e => e.key === "Enter" && addIssue()}
                  style={{ flex: 1, padding: "7px 12px", border: "1px dashed rgba(0,0,0,0.2)", borderRadius: 8, fontSize: 13, outline: "none", fontFamily: "inherit" }}
                />
                <button onClick={addIssue} disabled={!newIssueText.trim()}
                  style={{
                    padding: "7px 16px", borderRadius: 8, border: "none", fontSize: 13, fontWeight: 500, cursor: "pointer",
                    background: newIssueText.trim() ? "#0F6E56" : "rgba(0,0,0,0.08)",
                    color: newIssueText.trim() ? "#fff" : "rgba(0,0,0,0.3)",
                  }}>Add</button>
              </div>
            </div>

            {/* Notes */}
            <div>
              <label style={{ fontSize: 11, color: "rgba(0,0,0,0.4)", display: "block", marginBottom: 6, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                Case Notes
              </label>
              <textarea
                defaultValue={selectedCase.notes || ""}
                key={selectedCase.id}
                onBlur={e => saveNotes(selectedCase.id, e.target.value)}
                rows={4}
                placeholder="Attorney notes, strategy, follow-up reminders…"
                style={{
                  width: "100%", padding: "10px 12px", border: "1px solid rgba(0,0,0,0.1)", borderRadius: 10,
                  fontSize: 13, resize: "vertical", lineHeight: 1.7, fontFamily: "inherit", outline: "none",
                  background: "#FFFEF5", boxSizing: "border-box",
                }}
              />
              <div style={{ fontSize: 10, color: "rgba(0,0,0,0.25)", textAlign: "right", marginTop: 3 }}>saved on blur</div>
            </div>
          </div>
        )}

        {/* ── EMPTY STATE ── */}
        {!selectedCase && !showNewForm && (
          <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", flexDirection: "column", gap: 12, padding: "2rem" }}>
            <div style={{ fontSize: 40 }}>⚖️</div>
            <p style={{ fontSize: 15, fontWeight: 600, color: "#2C2C2A", margin: 0 }}>RFE Case Tracker</p>
            <p style={{ fontSize: 13, color: "rgba(0,0,0,0.4)", maxWidth: 380, textAlign: "center", lineHeight: 1.7, margin: 0 }}>
              Select a case from the list, or click <strong>+ New</strong> to track a new Request for Evidence.
              Each case has its own isolated checklist, deadline countdown, and notes.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Cold-start overlay. The HuggingFace free CPU tier sleeps after ~48h of
 * inactivity, so the first visitor after a sleep has to wait for the
 * container to boot AND for the embedding model to load (~15–60s).
 *
 * Without this overlay the app looks broken — buttons "work" but every
 * API call fails until the embedder is up. The overlay polls /api/health
 * and dismisses itself the moment `ready: true` comes back.
 */
function BootingOverlay({ health }) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setElapsed(e => e + 1), 1000);
    return () => clearInterval(id);
  }, []);

  const isOffline = health?.status === "offline";
  const isInitializing = health && health.status === "healthy" && !health.ready;
  const isInitial = !health;

  let title = "Starting up the demo";
  let subtitle = "Connecting to the backend…";
  if (isInitial) {
    subtitle = "Connecting to the backend…";
  } else if (isOffline) {
    title = "Waking up the server";
    subtitle = "The free-tier container sleeps after inactivity. This usually takes 30–60 seconds on first visit.";
  } else if (isInitializing) {
    title = "Loading the embedding model";
    subtitle = "Almost there — preparing the document retriever. This only happens on the first visit after a restart.";
  }

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 9999,
      background: "rgba(250,250,247,0.96)", backdropFilter: "blur(6px)",
      display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
      fontFamily: "'DM Sans', 'Helvetica Neue', sans-serif", color: "#2C2C2A",
      padding: "0 1.5rem", textAlign: "center",
    }}>
      <div style={{
        width: 56, height: 56, borderRadius: 14,
        background: "linear-gradient(135deg, #0F6E56, #1D9E75)",
        display: "flex", alignItems: "center", justifyContent: "center",
        marginBottom: 24,
        animation: "boot-pulse 1.8s ease-in-out infinite",
      }}>
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 21v-4a2 2 0 012-2h4a2 2 0 012 2v4M13 21v-4a2 2 0 012-2h4a2 2 0 012 2v4M3 10V6a2 2 0 012-2h14a2 2 0 012 2v4" />
        </svg>
      </div>
      <div style={{ fontSize: 20, fontWeight: 600, letterSpacing: "-0.02em", marginBottom: 8 }}>
        {title}
      </div>
      <div style={{ fontSize: 14, color: "rgba(0,0,0,0.55)", maxWidth: 460, lineHeight: 1.55 }}>
        {subtitle}
      </div>
      <div style={{ marginTop: 28, fontFamily: "'DM Mono', monospace", fontSize: 12, color: "rgba(0,0,0,0.35)" }}>
        {elapsed}s elapsed
      </div>
      <div style={{ marginTop: 32, fontSize: 11, color: "rgba(0,0,0,0.4)", maxWidth: 440 }}>
        This is a public demo of an immigration-law RAG assistant. The full version uses persistent storage and the larger BGE-M3 retriever — contact me for the production deployment.
      </div>
      <style>{`
        @keyframes boot-pulse {
          0%, 100% { transform: scale(1); opacity: 1; }
          50% { transform: scale(1.08); opacity: 0.85; }
        }
      `}</style>
    </div>
  );
}

export default function App() {
  const [activeTab, setActiveTab] = useState("qa");
  const [health, setHealth] = useState(null);

  // Poll /api/health until the backend reports `ready: true`. We poll every
  // 2.5s during cold-start; once ready, we drop to a 30s heartbeat just to
  // keep the header badges (Gemini, API Connected) fresh.
  useEffect(() => {
    let cancelled = false;
    let interval = null;

    const tick = () => {
      fetch(`${API_BASE}/health`)
        .then(r => r.json())
        .then(data => {
          if (cancelled) return;
          setHealth(data);
          // Once ready, slow down polling to 30s.
          if (data.ready && interval) {
            clearInterval(interval);
            interval = setInterval(tick, 30000);
          }
        })
        .catch(() => {
          if (!cancelled) setHealth({ status: "offline" });
        });
    };

    tick();                                  // immediate first call
    interval = setInterval(tick, 2500);      // then every 2.5s during warm-up
    return () => { cancelled = true; if (interval) clearInterval(interval); };
  }, []);

  const showOverlay = !health?.ready;

  return (
    <div style={{ height: "100vh", display: "flex", flexDirection: "column", fontFamily: "'DM Sans', 'Helvetica Neue', sans-serif", color: "#2C2C2A", background: "#FAFAF7" }}>
      <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&family=DM+Mono:wght@400&display=swap" rel="stylesheet" />

      {showOverlay && <BootingOverlay health={health} />}

      {/* Public-demo banner — sets expectations, prompts the hire conversation. */}
      <div style={{
        padding: "6px 1.5rem", background: "#FFF8E6", borderBottom: "1px solid #F2D981",
        fontSize: 12, color: "#5C4500", display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
        textAlign: "center",
      }}>
        <span style={{ fontWeight: 600 }}>Public demo.</span>
        <span>Data resets between sessions. For the full deployment with persistent storage, BGE-M3 retrieval, and SLA — <a href="https://hasancanbiyik.com" target="_blank" rel="noopener noreferrer" style={{ color: "#5C4500", textDecoration: "underline" }}>get in touch</a>.</span>
      </div>

      <header style={{
        padding: "0 1.5rem", height: 56, display: "flex", alignItems: "center", justifyContent: "space-between",
        borderBottom: "1px solid rgba(0,0,0,0.08)", background: "#fff",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{
            width: 32, height: 32, borderRadius: 8, background: "linear-gradient(135deg, #0F6E56, #1D9E75)",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 21v-4a2 2 0 012-2h4a2 2 0 012 2v4M13 21v-4a2 2 0 012-2h4a2 2 0 012 2v4M3 10V6a2 2 0 012-2h14a2 2 0 012 2v4" />
            </svg>
          </div>
          <span style={{ fontSize: 16, fontWeight: 600, letterSpacing: "-0.02em" }}>Immigration Assistance ChatBot</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {health && (
            <StatusBadge type={health.status === "healthy" ? "success" : "error"}>
              {health.status === "healthy" ? "API Connected" : "API Offline"}
            </StatusBadge>
          )}
          {health?.modules?.gemini_llm && (
            <StatusBadge type={health.modules.gemini_llm === "active" ? "success" : "warning"}>
              Gemini {health.modules.gemini_llm}
            </StatusBadge>
          )}
        </div>
      </header>

      <nav style={{
        display: "flex", gap: 0, borderBottom: "1px solid rgba(0,0,0,0.08)", background: "#fff", padding: "0 1.5rem",
      }}>
        {TABS.map(tab => (
          <button key={tab.id} onClick={() => setActiveTab(tab.id)} style={{
            display: "flex", alignItems: "center", gap: 6, padding: "12px 20px", fontSize: 13, fontWeight: 500,
            border: "none", borderBottom: activeTab === tab.id ? "2px solid #0F6E56" : "2px solid transparent",
            background: "transparent", cursor: "pointer",
            color: activeTab === tab.id ? "#0F6E56" : "rgba(0,0,0,0.45)",
            transition: "all 0.15s",
          }}>
            <Icon path={tab.icon} size={16} />
            {tab.label}
          </button>
        ))}
      </nav>

      <main style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
        {activeTab === "qa" && <DocumentQA />}
        {activeTab === "translate" && <TranslationPanel />}
        {activeTab === "timeline" && <TimelinePanel />}
        {activeTab === "rfe" && <RFETracker />}
      </main>

      <footer style={{
        padding: "8px 1.5rem", borderTop: "1px solid rgba(0,0,0,0.06)",
        fontSize: 11, color: "rgba(0,0,0,0.3)", textAlign: "center", background: "#fff",
      }}>
        Immigration Assistance ChatBot v1.0 — For informational purposes only. Consult USCIS or an immigration attorney for official guidance.
      </footer>
    </div>
  );
}
