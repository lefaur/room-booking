<script setup lang="ts">
import { watch } from "vue";
import { useRouter } from "vue-router";

import { get } from "./api";
import AppHeader from "./components/AppHeader.vue";
import ToastList from "./components/ToastList.vue";
import { session } from "./session";
import type { User } from "./types";

const router = useRouter();

// профиль подгружаем при входе и после перезагрузки страницы
watch(
  () => session.accessToken,
  async (token, previous) => {
    if (!token) {
      session.user = null;
      // при старте страницы без токена на вход отправляет сам роутер (с ?next=); здесь — только когда сессия
      // пропала на ходу: выход или отозванный refresh
      if (previous && !router.currentRoute.value.meta.public) await router.push("/login");
      return;
    }
    if (session.user?.id === Number(session.claims?.sub)) return;
    try {
      session.user = await get<User>("/api/auth/me");
    } catch {
      /* 401 уже обработан в api: сессия очищена */
    }
  },
  { immediate: true },
);
</script>

<template>
  <AppHeader v-if="session.loggedIn" />
  <main class="page">
    <RouterView />
  </main>
  <ToastList />
</template>
