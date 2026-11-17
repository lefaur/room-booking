<script setup lang="ts">
import { onMounted, ref } from "vue";

import { get, patch, query } from "../../api";
import { ROLE_LABELS } from "../../labels";
import { session } from "../../session";
import { formatDay } from "../../time";
import { notify, notifyError } from "../../toasts";
import type { Role, User } from "../../types";

const users = ref<User[]>([]);
const roles = ref<Role[]>([]);
const search = ref("");

async function load() {
  try {
    users.value = await get<User[]>(`/api/auth/users${query({ email: search.value.trim(), limit: 200 })}`);
  } catch (e) {
    notifyError(e);
  }
}

async function update(user: User, changes: Partial<Pick<User, "role" | "is_active">>) {
  try {
    const updated = await patch<User>(`/api/auth/users/${user.id}`, changes);
    users.value = users.value.map((u) => (u.id === updated.id ? updated : u));
    notify(`Пользователь ${updated.email} обновлён`);
  } catch (e) {
    notifyError(e);
    await load(); // вернуть селект к реальному значению
  }
}

onMounted(async () => {
  try {
    roles.value = await get<Role[]>("/api/auth/roles");
  } catch (e) {
    notifyError(e);
  }
  await load();
});
</script>

<template>
  <h1>Пользователи</h1>
  <form class="card row" style="margin-bottom: 16px" @submit.prevent="load">
    <label>Email <input v-model="search" type="email" placeholder="точное совпадение" data-testid="users-search" /></label>
    <button type="submit" data-testid="users-search-submit">Найти</button>
  </form>
  <div class="card">
    <table class="responsive" data-testid="users-table">
      <thead>
        <tr><th>Имя</th><th>Email</th><th>Роль</th><th>Активен</th><th>Создан</th></tr>
      </thead>
      <tbody>
        <tr v-for="u in users" :key="u.id" data-testid="user-row" :data-email="u.email">
          <td data-label="Имя">{{ u.full_name }}</td>
          <td data-label="Email">{{ u.email }}</td>
          <td data-label="Роль">
            <select
              :value="u.role"
              :disabled="u.id === session.user?.id"
              data-testid="user-role"
              @change="update(u, { role: ($event.target as HTMLSelectElement).value })"
            >
              <option v-for="r in roles" :key="r.name" :value="r.name">{{ ROLE_LABELS[r.name] ?? r.title }}</option>
            </select>
          </td>
          <td data-label="Активен">
            <input
              type="checkbox"
              :checked="u.is_active"
              :disabled="u.id === session.user?.id"
              data-testid="user-active"
              @change="update(u, { is_active: ($event.target as HTMLInputElement).checked })"
            />
          </td>
          <td data-label="Создан">{{ formatDay(u.created_at) }}</td>
        </tr>
      </tbody>
    </table>
    <p v-if="!users.length" class="muted">Никого не нашлось.</p>
  </div>
</template>
