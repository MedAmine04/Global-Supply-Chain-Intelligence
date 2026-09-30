import OverviewSection from "./components/OverviewSection";
import SupplierPerformanceSection from "./components/SupplierPerformanceSection";
import RegionTransportSection from "./components/RegionTransportSection";
import AtRiskShipmentsSection from "./components/AtRiskShipmentsSection";
import CopilotSection from "./components/CopilotSection";

export default function App() {
  return (
    <main style={{ fontFamily: "sans-serif", padding: "2rem", maxWidth: 1000, margin: "0 auto" }}>
      <h1>Global Supply Chain Intelligence</h1>
      <p style={{ color: "#666" }}>Phases 1-6 — Data Platform, ML, NLP, CV, AI Copilot</p>

      <div style={{ display: "flex", flexDirection: "column", gap: "2rem" }}>
        <OverviewSection />
        <SupplierPerformanceSection />
        <AtRiskShipmentsSection />
        <CopilotSection />
        <RegionTransportSection />
      </div>
    </main>
  );
}
