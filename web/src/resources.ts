import { ref } from "vue";

import { get } from "./api";
import type { Resource } from "./types";

/** Справочник ресурсов для подписей в списках броней (брони хранят только resource_id). */
export const resourcesById = ref<Record<number, Resource>>({});

export async function loadResources(): Promise<void> {
  const list = await get<Resource[]>("/api/booking/resources");
  resourcesById.value = Object.fromEntries(list.map((r) => [r.id, r]));
}

/** Средняя ширина символа в долях кегля — с запасом под широкие кириллические буквы. */
const CHAR_WIDTH = 0.62;

/** Кегль подписи, которая влезает в прямоугольник ресурса; null — места нет, подпись не рисуется
 * (полное название остаётся во всплывающей подсказке). base — обычный кегль для этого этажа. */
export function labelSize(name: string, w: number, h: number, base: number): number | null {
  const byWidth = (w * 0.9) / (Math.max(name.length, 1) * CHAR_WIDTH);
  const size = Math.min(base, byWidth, h * 0.6);
  return size >= base * 0.4 ? size : null;
}
