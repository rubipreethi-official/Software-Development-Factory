const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

export async function fetchHealth() {
  const res = await fetch(`${API_BASE_URL}/health`, { cache: "no-store" });
  if (!res.ok) throw new Error("Backend offline");
  return res.json();
}

export async function submitPRD(title: string, content: string) {
  const res = await fetch(`${API_BASE_URL}/prd`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, content }),
  });
  if (!res.ok) throw new Error("Submission failed");
  return res.json();
}

export async function fetchExecutions(limit = 10) {
  const res = await fetch(`${API_BASE_URL}/executions?limit=${limit}`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch executions");
  return res.json();
}

export async function fetchExecutionStatus(id: string) {
  const res = await fetch(`${API_BASE_URL}/executions/${id}`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch status");
  return res.json();
}

export async function fetchArtifacts(id: string, type: "spec" | "code" | "validation") {
  const res = await fetch(`${API_BASE_URL}/executions/${id}/${type}`, { cache: "no-store" });
  if (!res.ok) return null;
  return res.json();
}

export async function fetchReviews() {
  const res = await fetch(`${API_BASE_URL}/reviews`, { cache: "no-store" });
  if (!res.ok) throw new Error("Failed to fetch reviews");
  return res.json();
}

export async function approveReview(id: string, reviewer: string, comments: string) {
  const res = await fetch(`${API_BASE_URL}/reviews/${id}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reviewer, comments }),
  });
  if (!res.ok) throw new Error("Approval failed");
  return res.json();
}
