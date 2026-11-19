<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { ApiError, del, get, patch, post, query } from "../../api";
import { EQUIPMENT_LABELS } from "../../labels";
import { labelSize } from "../../resources";
import { notify, notifyError } from "../../toasts";
import type { Floor, Resource, ResourceKind } from "../../types";

type Draft = Pick<Resource, "x" | "y" | "w" | "h" | "name" | "capacity" | "active" | "equipment">;
const EDITABLE: (keyof Draft)[] = ["x", "y", "w", "h", "name", "capacity", "active", "equipment"];

const route = useRoute();
const router = useRouter();

const floors = ref<Floor[]>([]);
const resources = ref<Resource[]>([]);
const drafts = reactive<Record<number, Draft>>({});
const selectedId = ref<number | null>(null);
const saving = ref(false);
const svg = ref<SVGSVGElement | null>(null);

const floorId = computed(() => Number(route.query.floor) || floors.value[0]?.id || null);
const floor = computed(() => floors.value.find((f) => f.id === floorId.value) ?? null);
const step = computed(() => (floor.value && floor.value.width >= 200 ? 10 : 1));
const fontSize = computed(() => (floor.value ? Math.max(floor.value.width, floor.value.height) / 45 : 10));
const selected = computed(() => resources.value.find((r) => r.id === selectedId.value) ?? null);
const dirtyIds = computed(() => resources.value.filter((r) => isDirty(r)).map((r) => r.id));

function view(r: Resource): Draft {
  return drafts[r.id] ?? r;
}

function draftOf(r: Resource): Draft {
  drafts[r.id] ??= { x: r.x, y: r.y, w: r.w, h: r.h, name: r.name, capacity: r.capacity, active: r.active, equipment: [...r.equipment] };
  return drafts[r.id];
}

function isDirty(r: Resource): boolean {
  const d = drafts[r.id];
  return !!d && EDITABLE.some((k) => JSON.stringify(d[k]) !== JSON.stringify(r[k]));
}

async function loadFloors() {
  floors.value = await get<Floor[]>("/api/booking/floors");
}

async function loadResources() {
  if (!floorId.value) return;
  resources.value = await get<Resource[]>(`/api/booking/resources${query({ floor_id: floorId.value })}`);
  for (const key of Object.keys(drafts)) delete drafts[Number(key)];
}

onMounted(async () => {
  try {
    await loadFloors();
    await loadResources();
  } catch (e) {
    notifyError(e);
  }
});
watch(floorId, () => {
  selectedId.value = null;
  loadResources().catch(notifyError);
});

// --- перетаскивание ---
let drag: { id: number; mode: "move" | "resize"; dx: number; dy: number } | null = null;

function toPlan(event: PointerEvent): { x: number; y: number } {
  const matrix = svg.value?.getScreenCTM();
  if (!svg.value || !matrix) return { x: 0, y: 0 };
  const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse());
  return { x: point.x, y: point.y };
}

const snap = (v: number) => Math.round(v / step.value) * step.value;

function startDrag(event: PointerEvent, r: Resource, mode: "move" | "resize") {
  selectedId.value = r.id;
  const d = draftOf(r);
  const p = toPlan(event);
  drag = { id: r.id, mode, dx: p.x - (mode === "move" ? d.x : d.x + d.w), dy: p.y - (mode === "move" ? d.y : d.y + d.h) };
  (event.currentTarget as Element).setPointerCapture(event.pointerId);
}

function moveDrag(event: PointerEvent) {
  if (!drag || !floor.value) return;
  const d = drafts[drag.id];
  const p = toPlan(event);
  if (drag.mode === "move") {
    d.x = Math.min(Math.max(0, snap(p.x - drag.dx)), floor.value.width - d.w);
    d.y = Math.min(Math.max(0, snap(p.y - drag.dy)), floor.value.height - d.h);
  } else {
    d.w = Math.min(Math.max(step.value, snap(p.x - drag.dx - d.x)), floor.value.width - d.x);
    d.h = Math.min(Math.max(step.value, snap(p.y - drag.dy - d.y)), floor.value.height - d.y);
  }
}

function endDrag() {
  drag = null;
}

// --- сохранение ---
async function save() {
  saving.value = true;
  const errors: string[] = [];
  for (const r of resources.value.filter(isDirty)) {
    const d = drafts[r.id];
    const changes = Object.fromEntries(EDITABLE.filter((k) => JSON.stringify(d[k]) !== JSON.stringify(r[k])).map((k) => [k, d[k]]));
    try {
      const updated = await patch<Resource>(`/api/booking/resources/${r.id}`, { version: r.version, ...changes });
      resources.value = resources.value.map((x) => (x.id === r.id ? updated : x));
      delete drafts[r.id];
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      // 409 бывает и при пересечении с другим ресурсом; про устаревшую версию говорим по-человечески
      const reason =
        e instanceof ApiError && e.status === 409 && message.startsWith("Ресурс уже изменён")
          ? "кто-то изменил его раньше вас, обновите редактор"
          : message;
      errors.push(`«${r.name}»: ${reason}`);
    }
  }
  saving.value = false;
  if (errors.length) notify(`Не сохранено: ${errors.join("; ")}`, "error", 8000);
  else notify("Изменения сохранены");
}

function discard() {
  for (const key of Object.keys(drafts)) delete drafts[Number(key)];
}

async function reload() {
  try {
    await loadResources();
  } catch (e) {
    notifyError(e);
  }
}

// --- создание и удаление ---
const newFloor = reactive({ name: "", level: 1, width: 600, height: 400 });
const newResource = reactive({ kind: "room" as ResourceKind, name: "", capacity: 6, w: 80, h: 60 });

async function createFloor() {
  try {
    const created = await post<Floor>("/api/booking/floors", { ...newFloor });
    await loadFloors();
    newFloor.name = "";
    notify(`Этаж «${created.name}» создан`);
    router.replace({ query: { floor: String(created.id) } });
  } catch (e) {
    notifyError(e);
  }
}

/** Свободное место для нового ресурса: первая точка сетки, где он ни с чем не пересекается. */
function freeSpot(w: number, h: number): { x: number; y: number } | null {
  if (!floor.value) return null;
  const s = Math.max(step.value, 10);
  for (let y = 0; y + h <= floor.value.height; y += s) {
    for (let x = 0; x + w <= floor.value.width; x += s) {
      const clash = resources.value.some((r) => {
        const v = view(r);
        return x < v.x + v.w && v.x < x + w && y < v.y + v.h && v.y < y + h;
      });
      if (!clash) return { x, y };
    }
  }
  return null;
}

async function createResource() {
  if (!floor.value) return;
  const spot = freeSpot(newResource.w, newResource.h);
  if (!spot) {
    notify("На плане нет свободного места такого размера", "error");
    return;
  }
  try {
    const created = await post<Resource>("/api/booking/resources", {
      floor_id: floor.value.id,
      kind: newResource.kind,
      name: newResource.name,
      capacity: newResource.kind === "desk" ? 1 : newResource.capacity,
      w: newResource.w,
      h: newResource.h,
      ...spot,
    });
    resources.value.push(created);
    selectedId.value = created.id;
    newResource.name = "";
    notify(`«${created.name}» добавлен`);
  } catch (e) {
    notifyError(e);
  }
}

async function removeSelected() {
  const r = selected.value;
  if (!r) return;
  try {
    await del(`/api/booking/resources/${r.id}`);
    resources.value = resources.value.filter((x) => x.id !== r.id);
    delete drafts[r.id];
    selectedId.value = null;
    notify(`«${r.name}» удалён`);
  } catch (e) {
    notifyError(e);
  }
}

function toggleEquipment(item: string, on: boolean) {
  if (!selected.value) return;
  const d = draftOf(selected.value);
  d.equipment = on ? [...d.equipment, item] : d.equipment.filter((e) => e !== item);
}
</script>

<template>
  <h1>Редактор этажей</h1>
  <div class="card row" style="margin-bottom: 16px">
    <label>
      Этаж
      <select :value="floorId ?? ''" data-testid="editor-floor" @change="router.replace({ query: { floor: ($event.target as HTMLSelectElement).value } })">
        <option v-for="f in floors" :key="f.id" :value="f.id">{{ f.name }}</option>
      </select>
    </label>
    <button class="primary" :disabled="!dirtyIds.length || saving" data-testid="editor-save" @click="save">
      Сохранить{{ dirtyIds.length ? ` (${dirtyIds.length})` : "" }}
    </button>
    <button :disabled="!dirtyIds.length" data-testid="editor-discard" @click="discard">Отменить правки</button>
    <button data-testid="editor-reload" @click="reload">Обновить</button>
  </div>

  <div class="editor-layout">
    <div class="map-wrap">
      <svg
        v-if="floor"
        ref="svg"
        :viewBox="`0 0 ${floor.width} ${floor.height}`"
        data-testid="editor-plan"
        @pointermove="moveDrag"
        @pointerup="endDrag"
        @pointercancel="endDrag"
      >
        <rect class="map-floor" x="0" y="0" :width="floor.width" :height="floor.height" @pointerdown="selectedId = null" />
        <g v-for="r in resources" :key="r.id" data-testid="editor-resource" :data-name="r.name">
          <rect
            class="res"
            :class="[view(r).active ? 'free' : 'off', { selected: r.id === selectedId, dirty: isDirty(r) }]"
            :x="view(r).x"
            :y="view(r).y"
            :width="view(r).w"
            :height="view(r).h"
            style="cursor: move"
            @pointerdown.prevent="startDrag($event, r, 'move')"
          />
          <title>{{ view(r).name }}</title>
          <text
            v-if="labelSize(view(r).name, view(r).w, view(r).h, fontSize)"
            class="res-label"
            :x="view(r).x + view(r).w / 2"
            :y="view(r).y + view(r).h / 2"
            :font-size="labelSize(view(r).name, view(r).w, view(r).h, fontSize)!"
          >
            {{ view(r).name }}
          </text>
          <rect
            v-if="r.id === selectedId"
            class="handle"
            data-testid="editor-resize"
            :x="view(r).x + view(r).w - fontSize / 2"
            :y="view(r).y + view(r).h - fontSize / 2"
            :width="fontSize"
            :height="fontSize"
            @pointerdown.prevent.stop="startDrag($event, r, 'resize')"
          />
        </g>
      </svg>
      <p v-else class="muted">Создайте первый этаж.</p>
    </div>

    <div class="stack">
      <section v-if="selected" class="card stack" data-testid="editor-props">
        <h2 style="margin: 0">{{ selected.kind === "room" ? "Переговорка" : "Рабочее место" }}</h2>
        <label>Название <input v-model="draftOf(selected).name" data-testid="prop-name" /></label>
        <label v-if="selected.kind === 'room'">
          Мест <input v-model.number="draftOf(selected).capacity" type="number" min="1" data-testid="prop-capacity" />
        </label>
        <div class="row muted" data-testid="prop-geometry">
          x {{ view(selected).x }}, y {{ view(selected).y }}, {{ view(selected).w }}×{{ view(selected).h }}
        </div>
        <div v-if="selected.kind === 'room'" class="row">
          <label v-for="(label, item) in EQUIPMENT_LABELS" :key="item" class="inline">
            <input
              type="checkbox"
              :checked="view(selected).equipment.includes(item)"
              @change="toggleEquipment(item, ($event.target as HTMLInputElement).checked)"
            />
            {{ label }}
          </label>
        </div>
        <label class="inline">
          <input v-model="draftOf(selected).active" type="checkbox" data-testid="prop-active" /> Доступно для брони
        </label>
        <div><button class="danger" data-testid="editor-delete" @click="removeSelected">Удалить</button></div>
      </section>

      <form v-if="floor" class="card stack" data-testid="new-resource-form" @submit.prevent="createResource">
        <h2 style="margin: 0">Добавить на план</h2>
        <div class="row">
          <label>
            Тип
            <select v-model="newResource.kind" data-testid="new-kind">
              <option value="room">Переговорка</option>
              <option value="desk">Рабочее место</option>
            </select>
          </label>
          <label v-if="newResource.kind === 'room'">Мест <input v-model.number="newResource.capacity" type="number" min="1" style="width: 80px" /></label>
        </div>
        <label>Название <input v-model="newResource.name" required data-testid="new-name" /></label>
        <button type="submit" data-testid="new-submit">Добавить</button>
      </form>

      <form class="card stack" data-testid="new-floor-form" @submit.prevent="createFloor">
        <h2 style="margin: 0">Новый этаж</h2>
        <label>Название <input v-model="newFloor.name" required data-testid="new-floor-name" /></label>
        <div class="row">
          <label>Уровень <input v-model.number="newFloor.level" type="number" style="width: 80px" /></label>
          <label>Ширина <input v-model.number="newFloor.width" type="number" min="10" style="width: 90px" /></label>
          <label>Высота <input v-model.number="newFloor.height" type="number" min="10" style="width: 90px" /></label>
        </div>
        <button type="submit" data-testid="new-floor-submit">Создать этаж</button>
      </form>
    </div>
  </div>
</template>
