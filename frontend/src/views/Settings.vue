<template>
  <el-descriptions title="服务信息" :column="1" border>
    <el-descriptions-item label="服务">reader-py（「阅读」Python 重写）</el-descriptions-item>
    <el-descriptions-item label="后端">{{ backend }}</el-descriptions-item>
    <el-descriptions-item label="书源数量">{{ sourceCount }}</el-descriptions-item>
    <el-descriptions-item label="KOReader 插件">
      服务器地址填 <code>{{ backend }}/reader3</code>，用户名密码留空
    </el-descriptions-item>
  </el-descriptions>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { sourcesApi } from "../api";

const backend = `${location.origin}/reader3`;
const sourceCount = ref(0);

onMounted(async () => {
  const r = await sourcesApi.getBookSources(true);
  if (r.isSuccess) sourceCount.value = r.data.length;
});
</script>
