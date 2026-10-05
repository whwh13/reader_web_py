<template>
  <div>
    <div class="src-bar">
      <el-input v-model="remoteUrl" placeholder="粘贴书源 JSON 文件 URL 或直接粘贴 JSON 内容" />
      <el-button type="primary" :loading="importing" @click="doImport">导入书源</el-button>
      <el-upload :show-file-list="false" :auto-upload="false" accept=".json" :on-change="onFile">
        <el-button>从文件导入</el-button>
      </el-upload>
    </div>
    <el-table :data="sources" v-loading="loading">
      <el-table-column prop="bookSourceName" label="名称" min-width="180" />
      <el-table-column prop="bookSourceGroup" label="分组" width="140" />
      <el-table-column prop="bookSourceUrl" label="URL" min-width="260" show-overflow-tooltip />
      <el-table-column label="启用" width="90">
        <template #default="{ row }">
          <el-tag :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? "启用" : "停用" }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="100">
        <template #default="{ row }">
          <el-popconfirm title="确定删除？" @confirm="remove(row)">
            <template #reference>
              <el-button size="small" type="danger">删除</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import type { UploadFile } from "element-plus";
import { sourcesApi } from "../api";
import type { BookSourceSimple } from "../api/types";

const sources = ref<BookSourceSimple[]>([]);
const loading = ref(false);
const importing = ref(false);
const remoteUrl = ref("");

async function load() {
  loading.value = true;
  const r = await sourcesApi.getBookSources(true);
  if (r.isSuccess) sources.value = r.data;
  loading.value = false;
}

async function doImport() {
  const input = remoteUrl.value.trim();
  if (!input) return;
  importing.value = true;
  try {
    let payload: unknown[];
    if (input.startsWith("http")) {
      const r = await sourcesApi.saveFromRemoteSource(input);
      if (r.isSuccess) {
        ElMessage.success(`导入 ${r.data} 个书源`);
        remoteUrl.value = "";
        await load();
      }
      return;
    }
    payload = JSON.parse(input);
    const r = await sourcesApi.saveBookSources(payload);
    if (r.isSuccess) {
      ElMessage.success(`导入 ${r.data} 个书源`);
      remoteUrl.value = "";
      await load();
    }
  } catch (e) {
    ElMessage.error(`解析失败: ${e instanceof Error ? e.message : e}`);
  } finally {
    importing.value = false;
  }
}

async function onFile(file: UploadFile) {
  const text = await (file.raw as File).text();
  remoteUrl.value = text;
  await doImport();
}

async function remove(row: BookSourceSimple) {
  const r = await sourcesApi.deleteBookSource(row.bookSourceUrl);
  if (r.isSuccess) {
    ElMessage.success("已删除");
    await load();
  }
}

onMounted(load);
</script>

<style scoped>
.src-bar { display: flex; gap: 12px; margin-bottom: 16px; }
</style>
