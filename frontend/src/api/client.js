const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function getJSON(path) {
  const res = await fetch(`${API_URL}${path}`);
  if (!res.ok) {
    throw new Error(`API error ${res.status} on ${path}`);
  }
  return res.json();
}

async function postJSON(path, body) {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `API error ${res.status} on ${path}`);
  }
  return res.json();
}

export const api = {
  health: () => getJSON("/health"),
  overviewKPIs: () => getJSON("/api/kpis/overview"),
  supplierPerformance: () => getJSON("/api/suppliers/performance"),
  regionTransportBreakdown: () => getJSON("/api/analysis/region-transport"),
  atRiskShipments: (limit = 10) => getJSON(`/api/predictions/at-risk?limit=${limit}`),
  askCopilot: (question) => postJSON("/api/copilot/ask", { question }),
};
