import { useEffect, useState } from "react";
import { api } from "../api/client";

export default function AtRiskShipmentsSection() {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.atRiskShipments(10).then(setRows).catch((err) => setError(err.message));
  }, []);

  if (error) return <p style={{ color: "crimson" }}>Erreur : {error}</p>;
  if (!rows) return <p>Chargement…</p>;

  return (
    <section>
      <h2>Expéditions à risque de retard (prédiction ML)</h2>
      {rows.length === 0 ? (
        <p>
          Aucune prédiction disponible. Lancer <code>python -m app.cli train-model</code> puis{" "}
          <code>predict-risk</code>.
        </p>
      ) : (
        <>
          <table style={{ borderCollapse: "collapse", width: "100%" }}>
            <thead>
              <tr style={{ textAlign: "left", borderBottom: "2px solid #ddd" }}>
                <th style={{ padding: "0.4rem" }}>Expédition</th>
                <th style={{ padding: "0.4rem" }}>Fournisseur</th>
                <th style={{ padding: "0.4rem" }}>Transport</th>
                <th style={{ padding: "0.4rem" }}>Probabilité de retard</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.shipment_id} style={{ borderBottom: "1px solid #eee" }}>
                  <td style={{ padding: "0.4rem" }}>{r.shipment_id}</td>
                  <td style={{ padding: "0.4rem" }}>{r.supplier_name}</td>
                  <td style={{ padding: "0.4rem" }}>{r.transport_mode}</td>
                  <td style={{ padding: "0.4rem" }}>{(r.probability * 100).toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p style={{ color: "#666", fontSize: "0.8rem" }}>
            Modèle : {rows[0].model_name}. Signal modeste (ROC-AUC ≈ 0.57 sur données
            synthétiques) — à lire comme un classement de risque relatif, pas une certitude.
          </p>
        </>
      )}
    </section>
  );
}
