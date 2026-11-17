<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { get, query } from "../api";
import BookingPanel from "../components/BookingPanel.vue";
import FloorPlan from "../components/FloorPlan.vue";
import { SLOTS, officeIso, officeToday } from "../time";
import { notifyError } from "../toasts";
import type { Floor, FloorMap, MapResource } from "../types";

const route = useRoute();
const router = useRouter();

const floors = ref<Floor[]>([]);
const map = ref<FloorMap | null>(null);
const selectedId = ref<number | null>(null);
const loading = ref(false);

// состояние страницы живёт в адресе: ссылку на этаж и время можно отправить коллеге
const floorId = computed(() => Number(route.query.floor) || floors.value[0]?.id || null);
const day = computed(() => (typeof route.query.date === "string" ? route.query.date : officeToday()));
const time = computed(() => (typeof route.query.time === "string" && SLOTS.includes(route.query.time) ? route.query.time : "10:00"));
const selected = computed<MapResource | null>(() => map.value?.resources.find((r) => r.id === selectedId.value) ?? null);
const counts = computed(() => {
  const active = map.value?.resources.filter((r) => r.active) ?? [];
  return { free: active.filter((r) => !r.busy).length, busy: active.filter((r) => r.busy).length };
});

function setQuery(patch: Record<string, string | number>) {
  router.replace({ query: { ...route.query, ...Object.fromEntries(Object.entries(patch).map(([k, v]) => [k, String(v)])) } });
}

async function loadMap() {
  if (!floorId.value) return;
  loading.value = true;
  try {
    map.value = await get<FloorMap>(`/api/booking/floors/${floorId.value}/map${query({ at: officeIso(day.value, time.value) })}`);
  } catch (e) {
    map.value = null;
    notifyError(e);
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  try {
    floors.value = await get<Floor[]>("/api/booking/floors");
  } catch (e) {
    notifyError(e);
  }
  await loadMap();
});

watch([floorId, day, time], () => {
  if (map.value?.floor.id !== floorId.value) selectedId.value = null;
  loadMap();
});
</script>

<template>
  <h1>Карта офиса</h1>
  <div class="card row" style="margin-bottom: 16px">
    <label>
      Этаж
      <select :value="floorId ?? ''" data-testid="floor-select" @change="setQuery({ floor: ($event.target as HTMLSelectElement).value })">
        <option v-for="f in floors" :key="f.id" :value="f.id">{{ f.name }}</option>
      </select>
    </label>
    <label>
      Дата
      <input type="date" :value="day" :min="officeToday()" data-testid="map-date" @change="setQuery({ date: ($event.target as HTMLInputElement).value })" />
    </label>
    <label>
      Время
      <select :value="time" data-testid="map-time" @change="setQuery({ time: ($event.target as HTMLSelectElement).value })">
        <option v-for="slot in SLOTS" :key="slot" :value="slot">{{ slot }}</option>
      </select>
    </label>
    <p v-if="map" class="muted" style="margin: 0 0 8px" data-testid="map-summary">Свободно: {{ counts.free }} · занято: {{ counts.busy }}</p>
  </div>

  <p v-if="!floors.length && !loading" class="card muted" data-testid="no-floors">Этажей пока нет.</p>

  <div v-if="map" class="map-layout">
    <div class="map-wrap" :aria-busy="loading">
      <FloorPlan :floor="map.floor" :resources="map.resources" :selected-id="selectedId" @select="selectedId = $event.id" />
      <div class="legend">
        <span><i style="background: var(--free-bg); border: 1px solid var(--free)" />свободно</span>
        <span><i style="background: var(--busy-bg); border: 1px solid var(--busy)" />занято</span>
        <span><i style="background: var(--off-bg); border: 1px solid var(--off)" />недоступно</span>
      </div>
    </div>
    <BookingPanel v-if="selected" :resource="selected" :date="day" :time="time" @booked="loadMap" @close="selectedId = null" />
    <p v-else class="card muted" data-testid="map-hint">Выберите переговорку или рабочее место на плане.</p>
  </div>
</template>
