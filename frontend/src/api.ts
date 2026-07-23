// 此工具由虎門科技資深技術工程師Jeff Hong洪敬傑提供
export interface ArrayConfig {
  mode: string;
  shape: string;
  frequency: number;
  unit_cell_size: number;
  num_elements: number;
  feed_x: number;
  feed_y: number;
  feed_z: number;
  beam_theta: number;
  beam_phi: number;
}

export const fetchPreview = async (config: ArrayConfig) => {
  const res = await fetch("/api/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
  if (!res.ok) throw new Error("Failed to fetch preview");
  return res.json();
};

export const generateModel = async (config: ArrayConfig) => {
  const res = await fetch("/api/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
  if (!res.ok) {
    const data = await res.json()
    throw new Error(data.detail || "Failed to generate model");
  }
  return res.json();
};

export interface GenerateStatus {
  running: boolean;
  current: number;
  total: number;
  phase: string;
  result: string | null;
  error: string | null;
}

export const getGenerateStatus = async (): Promise<GenerateStatus> => {
  const res = await fetch("/api/generate/status");
  if (!res.ok) throw new Error("Failed to fetch generate status");
  return res.json();
};

export const cancelGenerate = async () => {
  const res = await fetch("/api/generate/cancel", { method: "POST" });
  if (!res.ok) throw new Error("Failed to cancel");
  return res.json();
};

export interface SweepStatus {
  running: boolean;
  current: number;
  total: number;
  phase: string;
  result: string | null;
  error: string | null;
  csv_url: string | null;
}

export const startSweep = async (lx_min_um: number, lx_max_um: number, points: number) => {
  const res = await fetch("/api/sweep", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ lx_min_um, lx_max_um, points }),
  });
  if (!res.ok) throw new Error("Failed to start sweep");
  return res.json();
};

export const getSweepStatus = async (): Promise<SweepStatus> => {
  const res = await fetch("/api/sweep/status");
  if (!res.ok) throw new Error("Failed to fetch sweep status");
  return res.json();
};

export const cancelSweep = async () => {
  const res = await fetch("/api/sweep/cancel", { method: "POST" });
  if (!res.ok) throw new Error("Failed to cancel sweep");
  return res.json();
};

export const uploadFile = async (file: File) => {
  const formData = new FormData();
  formData.append("file", file);
  
  const res = await fetch("/api/upload", {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const data = await res.json()
    throw new Error(data.detail || "Failed to upload file");
  }
  return res.json();
};

export const releaseAedt = async () => {
  const res = await fetch("/api/release", {
    method: "POST",
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || "Failed to release AEDT");
  }
  return res.json();
};

export const uploadProject = async (file: File) => {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch("/api/upload_project", {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || "Failed to upload project");
  }
  return res.json();
};
