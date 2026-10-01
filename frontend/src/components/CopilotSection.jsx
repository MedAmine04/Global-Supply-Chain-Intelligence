import { useState } from "react";
import { api } from "../api/client";

export default function CopilotSection() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState(null);
  const [toolCalls, setToolCalls] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  async function handleAsk(e) {
    e.preventDefault();
    if (!question.trim()) return;
    setLoading(true);
    setError(null);
    setAnswer(null);
    try {
      const res = await api.askCopilot(question);
      setAnswer(res.answer);
      setToolCalls(res.tool_calls || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <section>
      <h2>AI Copilot</h2>
      <form onSubmit={handleAsk} style={{ display: "flex", gap: "0.5rem" }}>
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask about your supply chain, contracts, or policies..."
          style={{ flex: 1, padding: "0.5rem" }}
        />
        <button type="submit" disabled={loading}>
          {loading ? "…" : "Ask"}
        </button>
      </form>

      {error && (
        <p style={{ color: "crimson", marginTop: "0.5rem" }}>
          {error}
          {error.includes("ANTHROPIC_API_KEY") && (
            <> — le Copilot nécessite une clé API côté serveur, non configurée ici.</>
          )}
        </p>
      )}
      {answer && <p style={{ marginTop: "0.5rem" }}>{answer}</p>}
      {toolCalls.length > 0 && (
        <details style={{ marginTop: "0.5rem", fontSize: "0.8rem", color: "#666" }}>
          <summary>Données utilisées ({toolCalls.length} outil(s) appelé(s))</summary>
          <pre style={{ background: "#f4f4f4", padding: "0.5rem", overflow: "auto" }}>
            {JSON.stringify(toolCalls, null, 2)}
          </pre>
        </details>
      )}
    </section>
  );
}
