<template>
  <el-descriptions title="服务信息" :column="1" border>
    <el-descriptions-item label="服务">reader-py（「阅读」Python 重写）</el-descriptions-item>
    <el-descriptions-item label="后端地址">{{ rootAddress }}<span class="hint">（KOReader 插件填这个地址再加 /reader3）</span></el-descriptions-item>
    <el-descriptions-item label="KOReader 插件">
      服务器地址填 <code>{{ rootAddress }}/reader3</code>，用户名密码留空
    </el-descriptions-item>
    <el-descriptions-item label="书源数量">{{ sourceCount }}</el-descriptions-item>
  </el-descriptions>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { sourcesApi } from "../api";

// 根地址（legacy 习惯：显示 origin，不带 /reader3 路径）
const rootAddress = location.origin;
const sourceCount = ref(0);

onMounted(async () => {
  const r = await sourcesApi.getBookSources(true);
  if (r.isSuccess) sourceCount.value = r.data.length;
});
</script>

<style scoped>
.hint { color: var(--el-text-color-secondary); font-size: 12px; }
</style>
