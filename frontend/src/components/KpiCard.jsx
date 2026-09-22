export default function KpiCard({ label, value, suffix = "" }) {
  return (
    <div
      style={{
        background: "#fff",
        border: "1px solid #e2e2e2",
        borderRadius: 8,
        padding: "1rem 1.25rem",
        minWidth: 160,
      }}
    >
      <div style={{ fontSize: "0.8rem", color: "#666", marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: "1.6rem", fontWeight: 600 }}>
        {value === null || value === undefined ? "—" : value}
        {value !== null && value !== undefined ? suffix : ""}
      </div>
    </div>
  );
}
