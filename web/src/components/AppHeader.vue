<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { post } from "../api";
import { ROLE_LABELS } from "../labels";
import { session } from "../session";

const route = useRoute();
const router = useRouter();
const menuOpen = ref(false);

watch(() => route.fullPath, () => (menuOpen.value = false));

const adminLinks = computed(() =>
  [
    { to: "/admin/editor", label: "Редактор", perm: "floors.write" },
    { to: "/admin/users", label: "Пользователи", perm: "users.manage" },
    { to: "/admin/settings", label: "Правила", perm: "settings.write" },
    { to: "/admin/jobs", label: "Джобы", perm: "jobs.run" },
  ].filter((link) => session.can(link.perm)),
);

async function logout() {
  const refresh = session.refreshToken;
  if (refresh) {
    try {
      await post("/api/auth/logout", { refresh_token: refresh });
    } catch {
      /* выходим в любом случае */
    }
  }
  session.clear();
  await router.push("/login");
}
</script>

<template>
  <header class="header">
    <RouterLink to="/" class="logo">OfficeSpace</RouterLink>
    <button
      class="burger"
      data-testid="menu-toggle"
      :aria-expanded="menuOpen"
      aria-label="Меню"
      @click="menuOpen = !menuOpen"
    >
      <span /><span /><span />
    </button>
    <nav class="nav" :class="{ open: menuOpen }" data-testid="main-nav">
      <RouterLink to="/" data-testid="nav-map">Карта</RouterLink>
      <RouterLink to="/bookings" data-testid="nav-bookings">Брони</RouterLink>
      <RouterLink to="/profile" data-testid="nav-profile">Профиль</RouterLink>
      <RouterLink
        v-for="link in adminLinks"
        :key="link.to"
        :to="link.to"
        class="nav-admin"
        :data-testid="`nav-${link.to.split('/').pop()}`"
      >
        {{ link.label }}
      </RouterLink>
      <div class="nav-user">
        <span data-testid="current-user">{{ session.user?.full_name ?? session.claims?.email }}</span>
        <small>{{ ROLE_LABELS[session.role] ?? session.role }}</small>
        <button class="link-button" data-testid="logout" @click="logout">Выйти</button>
      </div>
    </nav>
  </header>
</template>
