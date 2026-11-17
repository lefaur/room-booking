<script setup lang="ts">
import { onMounted, ref } from "vue";

import { ApiError, del, get, post } from "../api";
import { ROLE_LABELS } from "../labels";
import { session } from "../session";
import { formatDay, formatTime } from "../time";
import { notify, notifyError } from "../toasts";

interface Link {
  chat_id: number;
  username: string | null;
  linked_at: string;
}

interface LinkCode {
  code: string;
  expires_at: string;
  command: string;
}

const link = ref<Link | null>(null);
const code = ref<LinkCode | null>(null);
const loaded = ref(false);

async function loadLink() {
  try {
    link.value = await get<Link>("/api/tg/link");
    code.value = null;
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) link.value = null;
    else notifyError(e);
  } finally {
    loaded.value = true;
  }
}

async function getCode() {
  try {
    code.value = await post<LinkCode>("/api/tg/link-code");
  } catch (e) {
    notifyError(e);
  }
}

async function unlink() {
  try {
    await del("/api/tg/link");
    link.value = null;
    notify("Telegram отвязан");
  } catch (e) {
    notifyError(e);
  }
}

onMounted(loadLink);
</script>

<template>
  <h1>Профиль</h1>
  <div class="stack" style="max-width: 560px">
    <section class="card" data-testid="profile-info">
      <h2>{{ session.user?.full_name }}</h2>
      <p style="margin: 0">{{ session.user?.email }}</p>
      <p class="muted" style="margin: 0">{{ ROLE_LABELS[session.role] ?? session.role }}</p>
    </section>

    <section v-if="loaded" class="card stack" data-testid="telegram-block">
      <h2 style="margin: 0">Telegram</h2>
      <template v-if="link">
        <p style="margin: 0" data-testid="telegram-linked">
          Привязан{{ link.username ? ` (@${link.username})` : "" }} {{ formatDay(link.linked_at) }}.
          Уведомления о бронях приходят в бот, там же их можно подтвердить или отменить.
        </p>
        <div><button class="danger" data-testid="telegram-unlink" @click="unlink">Отвязать</button></div>
      </template>
      <template v-else>
        <p class="muted" style="margin: 0" data-testid="telegram-not-linked">
          Не привязан. Получите код и отправьте его боту OfficeSpace.
        </p>
        <div v-if="code" class="stack" data-testid="telegram-code-box">
          <span class="code" data-testid="telegram-code">{{ code.code }}</span>
          <span>Отправьте боту: <code data-testid="telegram-command">{{ code.command }}</code></span>
          <span class="muted">Код действует до {{ formatTime(code.expires_at) }}</span>
        </div>
        <div class="row">
          <button class="primary" data-testid="telegram-get-code" @click="getCode">{{ code ? "Новый код" : "Получить код" }}</button>
          <button v-if="code" data-testid="telegram-check" @click="loadLink">Я отправил код</button>
        </div>
      </template>
    </section>
  </div>
</template>
