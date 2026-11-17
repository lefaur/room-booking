<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";

import { get, put } from "../../api";
import { SETTING_LABELS } from "../../labels";
import { notify, notifyError } from "../../toasts";
import type { Settings } from "../../types";

const saved = ref<Settings>({});
const form = reactive<Settings>({});
const error = ref("");

const changed = computed(() => Object.keys(form).filter((k) => form[k] !== saved.value[k]));

function fill(values: Settings) {
  saved.value = values;
  Object.assign(form, values);
}

async function save() {
  error.value = "";
  try {
    fill(await put<Settings>("/api/booking/settings", Object.fromEntries(changed.value.map((k) => [k, form[k]]))));
    notify("Правила сохранены");
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

onMounted(async () => {
  try {
    fill(await get<Settings>("/api/booking/settings"));
  } catch (e) {
    notifyError(e);
  }
});
</script>

<template>
  <h1>Правила бронирования</h1>
  <form class="card stack" style="max-width: 560px" data-testid="settings-form" @submit.prevent="save">
    <label v-for="key in Object.keys(saved)" :key="key">
      {{ SETTING_LABELS[key] ?? key }}
      <input v-model.number="form[key]" type="number" :data-testid="`setting-${key}`" />
    </label>
    <p v-if="error" class="error" role="alert" data-testid="form-error">{{ error }}</p>
    <div class="row">
      <button class="primary" type="submit" :disabled="!changed.length" data-testid="settings-save">Сохранить</button>
      <button type="button" :disabled="!changed.length" @click="fill(saved)">Сбросить</button>
    </div>
  </form>
</template>
