<script setup lang="ts">
import { computed, ref } from "vue";

import { post } from "../api";
import { STATUS_LABELS } from "../labels";
import { session } from "../session";
import { formatInterval } from "../time";
import { notify, notifyError } from "../toasts";
import type { Booking, Resource } from "../types";

const props = defineProps<{ booking: Booking; resource?: Resource }>();
const emit = defineEmits<{ changed: [booking: Booking] }>();

const busy = ref(false);
const own = computed(() => props.booking.user_id === Number(session.claims?.sub));
const kind = computed(() => props.resource?.kind ?? "room");
const notOver = computed(() => new Date(props.booking.end).getTime() > Date.now());

const canConfirm = computed(() => own.value && props.booking.status === "pending");
const canCheckIn = computed(() => own.value && props.booking.status === "confirmed" && notOver.value);
const canCancel = computed(
  () =>
    (own.value || session.can("bookings.cancel_any")) &&
    ["pending", "confirmed"].includes(props.booking.status) &&
    notOver.value,
);

const MESSAGES = { confirm: "Бронь подтверждена", cancel: "Бронь отменена", "check-in": "Отметка принята, хорошей встречи" };

async function act(action: keyof typeof MESSAGES) {
  busy.value = true;
  try {
    const updated = await post<Booking>(`/api/booking/bookings/${props.booking.id}/${action}`);
    notify(MESSAGES[action]);
    emit("changed", updated);
  } catch (e) {
    notifyError(e);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <article class="card booking-card" data-testid="booking-card" :data-id="booking.id" :data-status="booking.status">
    <header>
      <div>
        <strong data-testid="booking-resource">{{ resource?.name ?? `Ресурс №${booking.resource_id}` }}</strong>
        <div class="muted" data-testid="booking-when">{{ formatInterval(booking.start, booking.end, kind) }}</div>
      </div>
      <span class="badge" :class="booking.status" data-testid="booking-status">{{ STATUS_LABELS[booking.status] }}</span>
    </header>
    <div v-if="!own" class="muted" data-testid="booking-owner">{{ booking.user_email }}</div>
    <div class="actions">
      <button v-if="canConfirm" class="primary" :disabled="busy" data-testid="booking-confirm" @click="act('confirm')">Подтвердить</button>
      <button v-if="canCheckIn" class="primary" :disabled="busy" data-testid="booking-checkin" @click="act('check-in')">Я на месте</button>
      <button v-if="canCancel" class="danger" :disabled="busy" data-testid="booking-cancel" @click="act('cancel')">Отменить</button>
      <RouterLink :to="`/bookings/${booking.id}`" class="muted" style="margin-left: auto; align-self: center">№{{ booking.id }}</RouterLink>
    </div>
  </article>
</template>
