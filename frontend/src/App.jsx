import { useEffect, useState } from "react";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

export default function App() {
  const [health, setHealth] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch(`${API_URL}/health`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then(setHealth)
      .catch((err) => setError(err.message));
  }, []);

  return (
    <main style={{ fontFamily: "sans-serif", padding: "2rem" }}>
      <h1>Global Supply Chain Intelligence</h1>
      <p>Phase 0 — Foundation</p>

      <section>
        <h2>Statut backend</h2>
        {error && <p style={{ color: "crimson" }}>Erreur : {error}</p>}
        {!error && !health && <p>Connexion à l'API en cours…</p>}
        {health && (
          <pre style={{ background: "#f4f4f4", padding: "1rem" }}>
            {JSON.stringify(health, null, 2)}
          </pre>
        )}
      </section>
    </main>
  );
}
