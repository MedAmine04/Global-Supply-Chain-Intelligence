import { useEffect, useState } from "react";
import { api } from "../api/client";
import KpiCard from "./KpiCard";

export default function OverviewSection() {
  const [kpis, setKpis] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.overviewKPIs().then(setKpis).catch((err) => setError(err.message));
  }, []);

  if (error) {
    return <p style={{ color: "crimson" }}>Erreur lors du chargement des KPI : {error}</p>;
  }

  if (!kpis) {
    return <p>Chargement des KPI…</p>;
  }

  return (
    <section>
      <h2>Vue d'ensemble opérationnelle</h2>
      <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
        <KpiCard label="Commandes totales" value={kpis.total_orders} />
        <KpiCard label="Expéditions totales" value={kpis.total_shipments} />
        <KpiCard
          label="Livraison à l'heure"
          value={kpis.on_time_delivery_rate}
          suffix="%"
        />
        <KpiCard
          label="Délai moyen"
          value={kpis.average_delay_days}
          suffix=" j"
        />
        <KpiCard label="Taux d'incidents" value={kpis.incident_rate} suffix="%" />
      </div>
    </section>
  );
}
