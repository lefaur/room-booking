<script setup lang="ts">
import { toasts } from "../toasts";
</script>

<template>
  <div class="toasts" aria-live="polite">
    <div v-for="toast in toasts" :key="toast.id" class="toast" :class="toast.kind" data-testid="toast" :data-kind="toast.kind">
      {{ toast.text }}
    </div>
  </div>
</template>
