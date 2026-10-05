<template>
  <div>
    <div class="search-bar">
      <el-input
        v-model="keyword"
        placeholder="输入书名或作者，回车搜索"
        size="large"
        clearable
        @keyup.enter="doSearch"
      />
      <el-button type="primary" size="large" :loading="searching" @click="doSearch">搜索</el-button>
    </div>
    <div v-if="searching" class="search-tip">多源搜索中…（已聚合 {{ results.length }} 条）</div>
    <el-table :data="results" v-loading="searching" @row-click="addToShelf">
      <el-table-column prop="name" label="书名" min-width="180" />
      <el-table-column prop="author" label="作者" width="140" />
      <el-table-column prop="originName" label="来源" width="160" />
      <el-table-column prop="latestChapterTitle" label="最新章节" min-width="180" />
      <el-table-column label="操作" width="120">
        <template #default="{ row }">
          <el-button size="small" type="primary" @click.stop="addToShelf(row)">入架</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-if="!searching && searched && results.length === 0" description="没有搜到结果" />
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { ElMessage } from "element-plus";
import { searchApi, shelfApi } from "../api";
import type { Book } from "../api/types";

const keyword = ref("");
const results = ref<Book[]>([]);
const searching = ref(false);
const searched = ref(false);
const added = new Set<string>();

async function doSearch() {
  const key = keyword.value.trim();
  if (!key) return;
  searching.value = true;
  searched.value = true;
  results.value = [];
  // 单源逐个搜（MVP：串行前 12 个启用源；多源 SSE 在 backlog）
  const src = await import("../api").then((m) => m.sourcesApi.getBookSources(true));
  const sources = (src.isSuccess ? src.data : []).filter((s) => s.enabled).slice(0, 12);
  for (const s of sources) {
    const r = await searchApi.searchBook(key, s.bookSourceUrl);
    if (r.isSuccess) {
      for (const b of r.data) {
        const dedup = `${b.name}|${b.author}`;
        if (!added.has(dedup)) {
          added.add(dedup);
          results.value.push(b);
        }
      }
    }
  }
  searching.value = false;
}

async function addToShelf(b: Book) {
  const r = await shelfApi.saveBook({
    name: b.name,
    author: b.author,
    bookUrl: b.bookUrl,
    origin: b.origin,
    originName: b.originName,
    originOrder: b.originOrder ?? 0,
  });
  if (r.isSuccess) ElMessage.success(`《${b.name}》已加入书架`);
}
</script>

<style scoped>
.search-bar { display: flex; gap: 12px; margin-bottom: 16px; }
.search-tip { color: var(--el-text-color-secondary); margin-bottom: 8px; }
:deep(.el-table__row) { cursor: pointer; }
</style>
