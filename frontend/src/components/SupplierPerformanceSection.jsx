import { useEffect, useState } from "react";
import { api } from "../api/client";

export default function SupplierPerformanceSection() {
  const [suppliers, setSuppliers] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.supplierPerformance().then(setSuppliers).catch((err) => setError(err.message));
  }, []);

  if (error) return <p style={{ color: "crimson" }}>Erreur : {error}</p>;
  if (!suppliers) return <p>Chargement…</p>;

  const topRisk = suppliers.slice(0, 10);

  return (
    <section>
      <h2>Fournisseurs à risque (top 10)</h2>
      {topRisk.length === 0 ? (
        <p>Aucune donnée fournisseur disponible.</p>
      ) : (
        <table style={{ borderCollapse: "collapse", width: "100%" }}>
          <thead>
            <tr style={{ textAlign: "left", borderBottom: "2px solid #ddd" }}>
              <th style={{ padding: "0.4rem" }}>Fournisseur</th>
              <th style={{ padding: "0.4rem" }}>Pays</th>
              <th style={{ padding: "0.4rem" }}>Expéditions</th>
              <th style={{ padding: "0.4rem" }}>Retards</th>
              <th style={{ padding: "0.4rem" }}>Taux de retard</th>
              <th style={{ padding: "0.4rem" }}>Incidents</th>
            </tr>
          </thead>
          <tbody>
            {topRisk.map((s) => (
              <tr key={s.supplier_id} style={{ borderBottom: "1px solid #eee" }}>
                <td style={{ padding: "0.4rem" }}>{s.name}</td>
                <td style={{ padding: "0.4rem" }}>{s.country}</td>
                <td style={{ padding: "0.4rem" }}>{s.total_shipments}</td>
                <td style={{ padding: "0.4rem" }}>{s.delayed_shipments}</td>
                <td style={{ padding: "0.4rem" }}>{s.delay_rate}%</td>
                <td style={{ padding: "0.4rem" }}>{s.incident_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
