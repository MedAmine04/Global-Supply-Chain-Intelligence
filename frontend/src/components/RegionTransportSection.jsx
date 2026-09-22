import { useEffect, useState } from "react";
import { api } from "../api/client";

function riskColor(rate) {
  if (rate >= 20) return "#c0392b";
  if (rate >= 10) return "#e67e22";
  return "#27ae60";
}

export default function RegionTransportSection() {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.regionTransportBreakdown().then(setRows).catch((err) => setError(err.message));
  }, []);

  if (error) return <p style={{ color: "crimson" }}>Erreur : {error}</p>;
  if (!rows) return <p>Chargement…</p>;

  const maxRate = Math.max(...rows.map((r) => r.delay_rate), 1);

  return (
    <section>
      <h2>Retards par région et mode de transport</h2>
      {rows.length === 0 ? (
        <p>Aucune donnée disponible.</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
          {rows.map((r) => (
            <div
              key={`${r.region}-${r.transport_mode}`}
              style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}
            >
              <div style={{ width: 160, fontSize: "0.85rem" }}>
                {r.region} · {r.transport_mode}
              </div>
              <div style={{ flex: 1, background: "#eee", borderRadius: 4, height: 18 }}>
                <div
                  style={{
                    width: `${(r.delay_rate / maxRate) * 100}%`,
                    background: riskColor(r.delay_rate),
                    height: "100%",
                    borderRadius: 4,
                    transition: "width 0.3s",
                  }}
                />
              </div>
              <div style={{ width: 130, fontSize: "0.85rem", color: "#444" }}>
                {r.delay_rate}% ({r.delayed_shipments}/{r.total_shipments})
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
