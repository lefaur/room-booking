<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";

import { post } from "../api";
import { session } from "../session";

const router = useRouter();
const fullName = ref("");
const email = ref("");
const password = ref("");
const error = ref("");
const busy = ref(false);

async function submit() {
  error.value = "";
  busy.value = true;
  try {
    await post("/api/auth/register", { email: email.value, password: password.value, full_name: fullName.value });
    const pair = await post<{ access_token: string; refresh_token: string }>("/api/auth/login", {
      email: email.value,
      password: password.value,
    });
    session.setTokens(pair.access_token, pair.refresh_token);
    await router.push("/");
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="auth-box card">
    <h1>Регистрация</h1>
    <form class="stack" data-testid="register-form" @submit.prevent="submit">
      <label>Имя и фамилия <input v-model="fullName" required maxlength="120" data-testid="register-name" /></label>
      <label>Email <input v-model="email" type="email" required data-testid="register-email" /></label>
      <label>
        Пароль
        <input v-model="password" type="password" autocomplete="new-password" required data-testid="register-password" />
        <small>Не короче 8 символов, буквы и цифры</small>
      </label>
      <p v-if="error" class="error" role="alert" data-testid="form-error">{{ error }}</p>
      <button class="primary" type="submit" :disabled="busy" data-testid="register-submit">Зарегистрироваться</button>
      <div class="links"><RouterLink to="/login">Уже есть аккаунт</RouterLink></div>
    </form>
  </div>
</template>
