<template>
  <section class="sa-card followup-card">
    <div class="sa-card-title">
      上次建议追踪
      <span class="extra">追踪状态 × 信号是否仍存在，复核项排在最前</span>
    </div>
    <div class="followup-list">
      <ActionCard v-for="item in items" :key="item.signal_id" :item="item"
        @track="(s, n, it) => emit('track', s, n, it)" />
    </div>
  </section>
</template>

<script setup lang="ts">
import type { FollowupItem } from '@/types/decision'
import ActionCard from './cards/ActionCard.vue'

defineProps<{ items: FollowupItem[] }>()
const emit = defineEmits<{ track: [status: string, note: string, item: FollowupItem] }>()
</script>

<style scoped>
.followup-card { margin-bottom: 14px; }
.followup-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
@media (max-width: 1100px) { .followup-list { grid-template-columns: 1fr; } }
</style>
