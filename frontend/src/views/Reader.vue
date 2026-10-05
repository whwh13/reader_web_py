<template>
  <div class="reader-page" :style="readerStyle">
    <div class="reader-toolbar">
      <el-button @click="goBack">返回书架</el-button>
      <el-button @click="drawer = true">目录</el-button>
      <span class="reader-title">{{ book?.name }} · {{ chapter?.title }}</span>
      <div class="reader-tools">
        <el-button size="small" @click="changeSource?.open()">换源</el-button>
        <el-button size="small" @click="prevChapter" :disabled="index <= 0">上一章</el-button>
        <el-button size="small" @click="nextChapter" :disabled="index >= chapters.length - 1">下一章</el-button>
        <el-button size="small" @click="fontSize--; applyStyle()">A-</el-button>
        <el-button size="small" @click="fontSize++; applyStyle()">A+</el-button>
        <el-switch v-model="night" active-text="夜间" />
      </div>
    </div>

    <el-drawer v-model="drawer" title="目录" size="320px">
      <div
        v-for="c in chapters"
        :key="c.index"
        class="toc-item"
        :class="{ active: c.index === index }"
        @click="jumpTo(c.index)"
      >
        {{ c.title }}
      </div>
    </el-drawer>

    <div class="reader-content" v-loading="loading">
      <pre class="reader-text" :style="textStyle">{{ content }}</pre>
    </div>

    <ChangeSourceDialog
      ref="changeSource"
      :book-url="currentBookUrl"
      :current-index="index"
      :current-title="chapter?.title"
      @switched="onSourceSwitched"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { booksApi, shelfApi } from "../api";
import type { Book, BookChapter } from "../api/types";
import ChangeSourceDialog from "../components/ChangeSourceDialog.vue";

const route = useRoute();
const router = useRouter();

const book = ref<Book | null>(null);
const chapters = ref<BookChapter[]>([]);
const chapter = ref<BookChapter | null>(null);
const content = ref("");
const index = ref(0);
const loading = ref(false);
const drawer = ref(false);
const night = ref(false);
const fontSize = ref(18);
const changeSource = ref<InstanceType<typeof ChangeSourceDialog> | null>(null);
const currentBookUrl = computed(() => String(route.query.url || ""));

const readerStyle = computed(() => ({
  background: night.value ? "#1a1a1a" : "#f7f3e8",
  minHeight: "calc(100vh - 40px)",
}));
const textStyle = computed(() => ({
  fontSize: `${fontSize.value}px`,
  color: night.value ? "#b8b8b8" : "#333",
}));

async function loadBook() {
  const url = String(route.query.url || "");
  if (!url) return;
  loading.value = true;
  const shelf = await shelfApi.getShelfBook(url);
  book.value = shelf.isSuccess ? shelf.data : null;

  const toc = await booksApi.getChapterList(url);
  if (!toc.isSuccess || !toc.data.length) {
    loading.value = false;
    return;
  }
  chapters.value = toc.data;
  index.value = book.value?.durChapterIndex ?? 0;
  await loadContent();
  loading.value = false;
}

async function loadContent() {
  const url = String(route.query.url || "");
  chapter.value = chapters.value[index.value] ?? null;
  loading.value = true;
  const r = await booksApi.getBookContent(url, index.value);
  content.value = r.isSuccess ? r.data : `加载失败: ${r.errorMsg}`;
  loading.value = false;
  saveProgress();
  window.scrollTo(0, 0);
}

async function saveProgress() {
  if (!book.value || !chapter.value) return;
  await shelfApi.saveProgress({
    url: book.value.bookUrl,
    index: index.value,
    durChapterIndex: index.value,
    durChapterPos: 0,
    durChapterTime: Date.now(),
    durChapterTitle: chapter.value.title,
    name: book.value.name,
    author: book.value.author,
  });
}

function prevChapter() {
  if (index.value > 0) {
    index.value--;
    loadContent();
  }
}

function nextChapter() {
  if (index.value < chapters.value.length - 1) {
    index.value++;
    loadContent();
  }
}

function jumpTo(i: number) {
  drawer.value = false;
  index.value = i;
  loadContent();
}

function applyStyle() {
  localStorage.setItem("reader_font", String(fontSize.value));
}

function goBack() {
  router.push("/");
}

/** 换源完成：书架记录已由后端改写（bookUrl/origin），跳到新地址并定位迁移后的章节 */
function onSourceSwitched(p: { newBookUrl: string; index: number; newSourceName: string }) {
  router.replace({
    path: "/reader",
    query: { url: p.newBookUrl, jump: String(p.index) },
  });
}

onMounted(() => {
  fontSize.value = Number(localStorage.getItem("reader_font") || 18);
  const jump = route.query.jump;
  loadBook().then(() => {
    if (jump !== undefined) {
      const i = Number(jump);
      if (Number.isInteger(i) && i >= 0 && i < chapters.value.length) {
        index.value = i;
        loadContent();
      }
    }
  });
});
</script>

<style scoped>
.reader-toolbar {
  display: flex; align-items: center; gap: 12px;
  padding: 8px 16px; position: sticky; top: 0; z-index: 10;
  background: rgba(0.5, 0.5, 0.5, 0.06); backdrop-filter: blur(4px);
}
.reader-title { flex: 1; font-weight: 600; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.reader-content { max-width: 760px; margin: 0 auto; padding: 16px 24px 80px; }
.reader-text { white-space: pre-wrap; word-break: break-word; font-family: inherit; line-height: 1.9; margin: 0; }
.toc-item { padding: 8px 12px; cursor: pointer; border-radius: 6px; }
.toc-item:hover { background: var(--el-fill-color-light); }
.toc-item.active { color: var(--el-color-primary); font-weight: 600; }
</style>
