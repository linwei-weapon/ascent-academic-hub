<template><div class="test-heading">正在进入专家问策，验证已发布能力……</div></template>
<script setup lang="ts">import {onMounted} from 'vue';import {useRoute,useRouter} from 'vue-router';const route=useRoute(),router=useRouter();onMounted(()=>router.replace({path:'/admin/reports/advice',query:{expertId:String(route.params.id)}}))</script>
<style scoped>.test-heading{display:flex;gap:20px;align-items:center;padding:18px 28px;font-size:13px;color:#64748b;flex-wrap:wrap}</style>
