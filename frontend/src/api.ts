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
  unitcell_name: string;  // HFSS 中作為陣列基準的物件名稱
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

export const uploadModel = async (file: File) => {
  const formData = new FormData();
  formData.append("file", file);
  
  const res = await fetch("/api/upload_model", {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || "Failed to upload model");
  }
  return res.json();
};
