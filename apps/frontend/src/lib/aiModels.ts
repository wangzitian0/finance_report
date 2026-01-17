import { apiFetch } from "@/lib/api";

export interface AiModelInfo {
  id: string;
  name?: string;
  is_free: boolean;
  input_modalities: string[];
  pricing: Record<string, string>;
}

export interface AiModelListResponse {
  default_model: string;
  fallback_models: string[];
  models: AiModelInfo[];
}

export async function fetchAiModels(options: { modality?: string; freeOnly?: boolean } = {}) {
  const params = new URLSearchParams();
  if (options.modality) params.set("modality", options.modality);
  if (options.freeOnly) params.set("free_only", "true");
  const query = params.toString();
  return apiFetch<AiModelListResponse>(`/api/ai/models${query ? `?${query}` : ""}`);
}
