import { apiFetch } from "@/lib/api";
import type { Schemas } from "@/lib/api-schema";

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

export async function fetchAiModels(
  options: { modality?: string; freeOnly?: boolean } = {},
): Promise<AiModelListResponse> {
  const params = new URLSearchParams();
  if (options.modality) params.set("modality", options.modality);
  if (options.freeOnly) params.set("free_only", "true");
  const query = params.toString();
  const catalog = await apiFetch<Schemas["LlmCatalogResponse"]>(
    `/api/llm/catalog${query ? `?${query}` : ""}`,
  );

  const models: AiModelInfo[] = catalog.models.map((m) => ({
    id: m.id,
    name: m.id,
    is_free: m.is_free,
    input_modalities: m.modalities,
    pricing: {},
  }));

  return {
    default_model: models[0]?.id ?? "",
    fallback_models: models.slice(1).map((m) => m.id),
    models,
  };
}
