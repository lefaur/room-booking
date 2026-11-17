<script setup lang="ts">
import { onMounted, ref } from "vue";

import { ApiError, get, post } from "../../api";
import { formatDay, formatTime } from "../../time";
import { notify, notifyError } from "../../toasts";
import type { JobInfo, JobRun } from "../../types";

const jobs = ref<JobInfo[]>([]);
const running = ref<string | null>(null);

async function load() {
  try {
    jobs.value = await get<JobInfo[]>("/api/scheduler/jobs");
  } catch (e) {
    notifyError(e);
  }
}

async function run(name: string) {
  running.value = name;
  try {
    await post<JobRun>(`/api/scheduler/jobs/${name}/run`);
    notify(`Джоба ${name} выполнена`);
  } catch (e) {
    // 502 — джоба отработала с ошибкой, подробности будут в последнем запуске
    if (e instanceof ApiError && e.status === 502) notify(`Джоба ${name} завершилась с ошибкой`, "error");
    else notifyError(e);
  } finally {
    running.value = null;
    await load();
  }
}

function when(iso: string | null | undefined): string {
  return iso ? `${formatDay(iso)} ${formatTime(iso)}` : "—";
}

onMounted(load);
</script>

<template>
  <h1>Фоновые джобы</h1>
  <p v-if="jobs[0]?.mode === 'manual'" class="muted" data-testid="jobs-manual">
    Планировщик в ручном режиме: джобы запускаются только кнопкой или из тестов.
  </p>
  <div class="card">
    <table class="responsive" data-testid="jobs-table">
      <thead>
        <tr><th>Джоба</th><th>Расписание</th><th>Последний запуск</th><th>Результат</th><th /></tr>
      </thead>
      <tbody>
        <tr v-for="job in jobs" :key="job.name" data-testid="job-row" :data-job="job.name">
          <td data-label="Джоба"><code>{{ job.name }}</code></td>
          <td data-label="Расписание">{{ job.schedule }}</td>
          <td data-label="Последний запуск">{{ when(job.last_run?.finished_at) }}</td>
          <td data-label="Результат">
            <span v-if="job.last_run" class="badge" :class="job.last_run.status === 'ok' ? 'confirmed' : 'cancelled'" data-testid="job-status">
              {{ job.last_run.status === "ok" ? "успешно" : "ошибка" }}
            </span>
            <small v-if="job.last_run" class="muted" data-testid="job-result"> {{ JSON.stringify(job.last_run.result) }}</small>
          </td>
          <td>
            <button :disabled="running !== null" data-testid="job-run" @click="run(job.name)">
              {{ running === job.name ? "Выполняется…" : "Запустить" }}
            </button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
