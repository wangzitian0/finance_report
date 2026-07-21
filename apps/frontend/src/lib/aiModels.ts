import { apiOperation } from "@/lib/api-client";
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
  const catalog = await apiOperation("get_catalog_llm_catalog_get", {
    query: {
      modality: options.modality as Schemas["Modality"] | undefined,
      free_only: options.freeOnly || undefined,
    },
  });

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
