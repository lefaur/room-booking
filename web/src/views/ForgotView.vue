<script setup lang="ts">
import { ref } from "vue";

import { post } from "../api";

const email = ref("");
const sent = ref("");
const error = ref("");

async function submit() {
  error.value = "";
  try {
    const resp = await post<{ detail: string }>("/api/auth/password/forgot", { email: email.value });
    sent.value = resp.detail;
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}
</script>

<template>
  <div class="auth-box card">
    <h1>Восстановление пароля</h1>
    <p v-if="sent" data-testid="forgot-sent">{{ sent }}</p>
    <form v-else class="stack" data-testid="forgot-form" @submit.prevent="submit">
      <label>Email <input v-model="email" type="email" required data-testid="forgot-email" /></label>
      <p v-if="error" class="error" role="alert" data-testid="form-error">{{ error }}</p>
      <button class="primary" type="submit" data-testid="forgot-submit">Отправить ссылку</button>
    </form>
    <p class="links"><RouterLink to="/login">Вернуться ко входу</RouterLink></p>
  </div>
</template>
