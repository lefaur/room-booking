<script setup lang="ts">
import { computed } from "vue";

import type { Floor, MapResource } from "../types";

const props = defineProps<{ floor: Floor; resources: MapResource[]; selectedId: number | null }>();
const emit = defineEmits<{ select: [resource: MapResource] }>();

const fontSize = computed(() => Math.max(props.floor.width, props.floor.height) / 45);

function state(resource: MapResource): string {
  if (!resource.active) return "off";
  return resource.busy ? "busy" : "free";
}

function pick(resource: MapResource) {
  if (resource.active) emit("select", resource);
}
</script>

<template>
  <svg
    :viewBox="`0 0 ${floor.width} ${floor.height}`"
    role="img"
    :aria-label="`План этажа ${floor.name}`"
    data-testid="floor-plan"
  >
    <rect class="map-floor" x="0" y="0" :width="floor.width" :height="floor.height" />
    <g
      v-for="res in resources"
      :key="res.id"
      data-testid="map-resource"
      :data-name="res.name"
      :data-kind="res.kind"
      :data-state="state(res)"
      role="button"
      :tabindex="res.active ? 0 : -1"
      :aria-label="`${res.name}: ${state(res) === 'free' ? 'свободно' : state(res) === 'busy' ? 'занято' : 'недоступно'}`"
      @click="pick(res)"
      @keydown.enter="pick(res)"
    >
      <rect
        class="res"
        :class="[state(res), { selected: res.id === selectedId }]"
        :x="res.x"
        :y="res.y"
        :width="res.w"
        :height="res.h"
        :rx="res.kind === 'desk' ? fontSize / 3 : fontSize / 2"
      />
      <text class="res-label" :x="res.x + res.w / 2" :y="res.y + res.h / 2" :font-size="fontSize">
        {{ res.name }}
      </text>
    </g>
  </svg>
</template>
