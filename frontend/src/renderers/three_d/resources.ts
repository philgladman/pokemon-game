import type { AppearanceDefinition, ThreeDMapResources } from "../../types";

export class ThreeDResourceLoader {
  private manifestRequest: Promise<Record<string, AppearanceDefinition>> | null = null;
  private readonly mapRequests = new Map<string, Promise<ThreeDMapResources>>();

  manifest(): Promise<Record<string, AppearanceDefinition>> {
    if (this.manifestRequest === null) {
      this.manifestRequest = requestJson<Record<string, AppearanceDefinition>>(
        "/api/renderers/three-d/manifest",
      ).catch((error: unknown) => {
        this.manifestRequest = null;
        throw error;
      });
    }
    return this.manifestRequest;
  }

  map(mapId: string): Promise<ThreeDMapResources> {
    const pending = this.mapRequests.get(mapId);
    if (pending !== undefined) return pending;
    const request = requestJson<ThreeDMapResources>(
      `/api/renderers/three-d/maps/${encodeURIComponent(mapId)}`,
    ).catch((error: unknown) => {
      this.mapRequests.delete(mapId);
      throw error;
    });
    this.mapRequests.set(mapId, request);
    return request;
  }
}

async function requestJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Unable to load renderer resource ${url}`);
  return (await response.json()) as T;
}
