import OverviewSection from "./components/OverviewSection";
import SupplierPerformanceSection from "./components/SupplierPerformanceSection";
import RegionTransportSection from "./components/RegionTransportSection";

export default function App() {
  return (
    <main style={{ fontFamily: "sans-serif", padding: "2rem", maxWidth: 1000, margin: "0 auto" }}>
      <h1>Global Supply Chain Intelligence</h1>
      <p style={{ color: "#666" }}>Phase 1 — Data Platform (FR-06 à FR-09)</p>

      <div style={{ display: "flex", flexDirection: "column", gap: "2rem" }}>
        <OverviewSection />
        <SupplierPerformanceSection />
        <RegionTransportSection />
      </div>
    </main>
  );
}
