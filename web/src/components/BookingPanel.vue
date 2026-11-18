<script setup lang="ts">
import { computed, ref, watch } from "vue";

import { post } from "../api";
import { EQUIPMENT_LABELS } from "../labels";
import { SLOTS, addDays, formatDay, officeIso } from "../time";
import { notify } from "../toasts";
import type { Booking, MapResource } from "../types";

const props = defineProps<{ resource: MapResource; date: string; time: string }>();
const emit = defineEmits<{ booked: [booking: Booking]; close: [] }>();

const start = ref(props.time);
const end = ref("");
const dateFrom = ref(props.date);
const dateTo = ref(props.date);
const error = ref("");
const busy = ref(false);
const created = ref<Booking | null>(null);

const endSlots = computed(() => [...SLOTS, "21:30"].filter((slot) => slot > start.value));

// ключ строкой: после перезагрузки карты приходит новый объект ресурса, и массив в источнике
// считался бы изменением на каждый раз — панель теряла бы сообщение о созданной брони
watch(
  () => `${props.resource.id}|${props.date}|${props.time}`,
  () => {
    start.value = SLOTS.includes(props.time) ? props.time : SLOTS[2];
    end.value = endSlots.value[1] ?? endSlots.value[0];
    dateFrom.value = props.date;
    dateTo.value = props.date;
    error.value = "";
    created.value = null;
  },
  { immediate: true },
);

watch(start, () => {
  if (end.value <= start.value) end.value = endSlots.value[0];
});

async function submit() {
  error.value = "";
  busy.value = true;
  const body =
    props.resource.kind === "room"
      ? { resource_id: props.resource.id, start: officeIso(props.date, start.value), end: officeIso(props.date, end.value) }
      : { resource_id: props.resource.id, date_from: dateFrom.value, date_to: dateTo.value };
  try {
    const booking = await post<Booking>("/api/booking/bookings", body);
    created.value = booking;
    notify("Бронь создана. Подтвердите её в разделе «Брони»");
    emit("booked", booking);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <aside class="card stack" data-testid="booking-panel">
    <header class="row" style="justify-content: space-between; align-items: start; flex-wrap: nowrap">
      <div>
        <h2 data-testid="panel-title">{{ resource.name }}</h2>
        <p class="muted" style="margin: 0">
          {{ resource.kind === "room" ? `Переговорка на ${resource.capacity} мест` : "Рабочее место" }}
          <template v-if="resource.equipment.length">
            · {{ resource.equipment.map((e) => EQUIPMENT_LABELS[e] ?? e).join(", ") }}
          </template>
        </p>
      </div>
      <button class="link-button" style="flex-shrink: 0" aria-label="Закрыть" data-testid="panel-close" @click="emit('close')">✕</button>
    </header>

    <!-- после своей брони ресурс на карте занят ею же: «занято, выберите другое» читалось бы как ошибка -->
    <template v-if="resource.busy && !created">
      <p v-if="resource.mine" class="muted" data-testid="panel-busy-mine">
        На это время у вас уже есть бронь. <RouterLink to="/bookings">Мои брони</RouterLink>
      </p>
      <p v-else class="muted" data-testid="panel-busy">На выбранное время занято, выберите другое время.</p>
    </template>

    <form class="stack" data-testid="booking-form" @submit.prevent="submit">
      <template v-if="resource.kind === 'room'">
        <p style="margin: 0">Дата: <strong data-testid="panel-date">{{ formatDay(`${date}T12:00:00Z`) }}</strong></p>
        <div class="row">
          <label>
            С
            <select v-model="start" data-testid="booking-start">
              <option v-for="slot in SLOTS" :key="slot" :value="slot">{{ slot }}</option>
            </select>
          </label>
          <label>
            До
            <select v-model="end" data-testid="booking-end">
              <option v-for="slot in endSlots" :key="slot" :value="slot">{{ slot }}</option>
            </select>
          </label>
        </div>
      </template>
      <div v-else class="row">
        <label>С <input v-model="dateFrom" type="date" required data-testid="booking-date-from" /></label>
        <label>По <input v-model="dateTo" type="date" :min="dateFrom" :max="addDays(dateFrom, 59)" required data-testid="booking-date-to" /></label>
      </div>
      <p v-if="error" class="error" role="alert" data-testid="form-error">{{ error }}</p>
      <button class="primary" type="submit" :disabled="busy" data-testid="booking-submit">Забронировать</button>
    </form>

    <p v-if="created" data-testid="booking-created">
      Бронь №{{ created.id }} создана и ждёт подтверждения.
      <RouterLink :to="`/bookings/${created.id}`" data-testid="booking-created-link">Открыть</RouterLink>
    </p>
  </aside>
</template>
