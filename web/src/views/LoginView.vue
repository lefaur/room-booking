<script setup lang="ts">
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { post } from "../api";
import { session } from "../session";

const route = useRoute();
const router = useRouter();
const email = ref("");
const password = ref("");
const error = ref("");
const busy = ref(false);

async function submit() {
  error.value = "";
  busy.value = true;
  try {
    const pair = await post<{ access_token: string; refresh_token: string }>("/api/auth/login", {
      email: email.value,
      password: password.value,
    });
    session.setTokens(pair.access_token, pair.refresh_token);
    const next = typeof route.query.next === "string" && route.query.next.startsWith("/") ? route.query.next : "/";
    await router.push(next);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="auth-box card">
    <h1>Вход в OfficeSpace</h1>
    <p v-if="route.query.reset === 'ok'" class="muted" data-testid="reset-done">Пароль изменён, войдите с новым паролем.</p>
    <form class="stack" data-testid="login-form" @submit.prevent="submit">
      <label>Email <input v-model="email" type="email" autocomplete="username" required data-testid="login-email" /></label>
      <label>
        Пароль
        <input v-model="password" type="password" autocomplete="current-password" required data-testid="login-password" />
      </label>
      <p v-if="error" class="error" role="alert" data-testid="form-error">{{ error }}</p>
      <button class="primary" type="submit" :disabled="busy" data-testid="login-submit">Войти</button>
      <div class="links">
        <RouterLink to="/register" data-testid="to-register">Регистрация</RouterLink>
        <RouterLink to="/forgot-password" data-testid="to-forgot">Забыли пароль?</RouterLink>
      </div>
    </form>
  </div>
</template>
