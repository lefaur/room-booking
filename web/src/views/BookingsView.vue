<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";

import { get, query } from "../api";
import BookingCard from "../components/BookingCard.vue";
import { ACTIVE_STATUSES } from "../labels";
import { loadResources, resourcesById } from "../resources";
import { session } from "../session";
import { notifyError } from "../toasts";
import type { Booking } from "../types";

type Tab = "active" | "history" | "everyone";

const tab = ref<Tab>("active");
const bookings = ref<Booking[]>([]);
const loading = ref(true);

const tabs = computed(() => {
  const list: { id: Tab; label: string }[] = [
    { id: "active", label: "Активные" },
    { id: "history", label: "История" },
  ];
  if (session.can("bookings.read_all")) list.push({ id: "everyone", label: "Все сотрудники" });
  return list;
});

const shown = computed(() => {
  const now = Date.now();
  const isActive = (b: Booking) => ACTIVE_STATUSES.includes(b.status) && new Date(b.end).getTime() > now;
  const list = tab.value === "history" ? bookings.value.filter((b) => !isActive(b)) : bookings.value.filter(isActive);
  return [...list].sort((a, b) =>
    tab.value === "history" ? b.start.localeCompare(a.start) : a.start.localeCompare(b.start),
  );
});

async function load() {
  loading.value = true;
  try {
    const scope = tab.value === "everyone" ? "all" : "own";
    bookings.value = await get<Booking[]>(`/api/booking/bookings${query({ scope, limit: 500 })}`);
  } catch (e) {
    notifyError(e);
  } finally {
    loading.value = false;
  }
}

function replace(updated: Booking) {
  bookings.value = bookings.value.map((b) => (b.id === updated.id ? updated : b));
}

onMounted(async () => {
  await Promise.all([load(), loadResources().catch(notifyError)]);
});
watch(tab, load);
</script>

<template>
  <h1>Брони</h1>
  <div class="tabs" role="tablist">
    <button
      v-for="t in tabs"
      :key="t.id"
      role="tab"
      :class="{ active: tab === t.id }"
      :aria-selected="tab === t.id"
      :data-testid="`tab-${t.id}`"
      @click="tab = t.id"
    >
      {{ t.label }}
    </button>
  </div>
  <p v-if="!loading && !shown.length" class="card muted" data-testid="bookings-empty">
    Здесь пока пусто. <RouterLink to="/">Забронировать на карте</RouterLink>
  </p>
  <div class="bookings-list" data-testid="bookings-list">
    <BookingCard v-for="b in shown" :key="b.id" :booking="b" :resource="resourcesById[b.resource_id]" @changed="replace" />
  </div>
</template>
