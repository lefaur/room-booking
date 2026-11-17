<script setup lang="ts">
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { post } from "../api";

const route = useRoute();
const router = useRouter();
const token = computed(() => (typeof route.query.token === "string" ? route.query.token : ""));
const password = ref("");
const repeat = ref("");
const error = ref("");

async function submit() {
  error.value = "";
  if (password.value !== repeat.value) {
    error.value = "Пароли не совпадают";
    return;
  }
  try {
    await post("/api/auth/password/reset", { token: token.value, new_password: password.value });
    await router.push({ path: "/login", query: { reset: "ok" } });
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}
</script>

<template>
  <div class="auth-box card">
    <h1>Новый пароль</h1>
    <p v-if="!token" class="error" data-testid="form-error">В ссылке нет токена. Запросите сброс ещё раз.</p>
    <form v-else class="stack" data-testid="reset-form" @submit.prevent="submit">
      <label>Новый пароль <input v-model="password" type="password" autocomplete="new-password" required data-testid="reset-password" /></label>
      <label>Ещё раз <input v-model="repeat" type="password" autocomplete="new-password" required data-testid="reset-repeat" /></label>
      <p v-if="error" class="error" role="alert" data-testid="form-error">{{ error }}</p>
      <button class="primary" type="submit" data-testid="reset-submit">Сохранить пароль</button>
    </form>
    <p class="links"><RouterLink to="/forgot-password">Запросить новую ссылку</RouterLink></p>
  </div>
</template>
