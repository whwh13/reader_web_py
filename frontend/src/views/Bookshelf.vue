<template>
  <div>
    <div class="shelf-bar">
      <el-button type="primary" :loading="refreshing" @click="refreshShelf">刷新书架</el-button>
      <span v-if="books.length">{{ books.length }} 本</span>
    </div>
    <el-empty v-if="!loading && books.length === 0" description="书架空空如也，去搜索添加吧" />
    <el-row :gutter="16">
      <el-col v-for="b in books" :key="b.bookUrl" :span="4" style="margin-bottom: 16px">
        <el-card shadow="hover" class="book-card" @click="openReader(b)">
          <div class="book-cover">{{ b.name.slice(0, 1) }}</div>
          <div class="book-name" :title="b.name">{{ b.name }}</div>
          <div class="book-author">{{ b.author }}</div>
          <div v-if="b.durChapterTitle" class="book-progress">读到:{{ b.durChapterTitle }}</div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { shelfApi } from "../api";
import type { Book } from "../api/types";

const router = useRouter();
const books = ref<Book[]>([]);
const loading = ref(false);
const refreshing = ref(false);

async function load() {
  loading.value = true;
  const r = await shelfApi.getBookshelf(false);
  if (r.isSuccess) books.value = r.data;
  loading.value = false;
}

async function refreshShelf() {
  refreshing.value = true;
  const r = await shelfApi.getBookshelf(true);
  if (r.isSuccess) books.value = r.data;
  refreshing.value = false;
}

function openReader(b: Book) {
  router.push({ path: "/reader", query: { url: b.bookUrl } });
}

onMounted(load);
</script>

<style scoped>
.shelf-bar { margin-bottom: 16px; display: flex; gap: 12px; align-items: center; }
.book-card { cursor: pointer; text-align: center; }
.book-cover {
  width: 80px; height: 106px; margin: 0 auto 8px; border-radius: 6px;
  background: linear-gradient(135deg, #5b8def, #7c4dff);
  color: #fff; font-size: 32px; line-height: 106px; font-weight: 700;
}
.book-name { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.book-author { color: var(--el-text-color-secondary); font-size: 12px; }
.book-progress { color: var(--el-color-primary); font-size: 12px; margin-top: 4px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
