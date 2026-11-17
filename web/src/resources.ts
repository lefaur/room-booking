import { ref } from "vue";

import { get } from "./api";
import type { Resource } from "./types";

/** Справочник ресурсов для подписей в списках броней (брони хранят только resource_id). */
export const resourcesById = ref<Record<number, Resource>>({});

export async function loadResources(): Promise<void> {
  const list = await get<Resource[]>("/api/booking/resources");
  resourcesById.value = Object.fromEntries(list.map((r) => [r.id, r]));
}
