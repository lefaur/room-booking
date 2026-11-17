<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import { get } from "../api";
import BookingCard from "../components/BookingCard.vue";
import { loadResources, resourcesById } from "../resources";
import type { Booking } from "../types";

const route = useRoute();
const booking = ref<Booking | null>(null);
const error = ref("");

onMounted(async () => {
  try {
    const [found] = await Promise.all([get<Booking>(`/api/booking/bookings/${route.params.id}`), loadResources()]);
    booking.value = found;
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
});
</script>

<template>
  <h1>Бронь №{{ route.params.id }}</h1>
  <p v-if="error" class="card error" data-testid="booking-error">{{ error }}</p>
  <div v-if="booking" style="max-width: 480px">
    <BookingCard :booking="booking" :resource="resourcesById[booking.resource_id]" @changed="booking = $event" />
  </div>
  <p><RouterLink to="/bookings">Все брони</RouterLink></p>
</template>
