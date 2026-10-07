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
          <el-image :src="b.coverUrl || ''" fit="cover" class="book-cover" lazy>
            <template #error>
              <div class="book-cover fallback">{{ b.name.slice(0, 1) }}</div>
            </template>
            <template #placeholder>
              <div class="book-cover fallback">…</div>
            </template>
          </el-image>
          <div class="book-name" :title="b.name">{{ b.name }}</div>
          <div class="book-author">{{ b.author }}</div>
          <div class="book-foot">
            <span v-if="b.durChapterTitle" class="book-progress">读到:{{ b.durChapterTitle }}</span>
            <span class="book-foot-btns">
              <el-button
                link
                type="primary"
                size="small"
                class="intro-btn"
                @click.stop="introBook = b; introVisible = true"
              >简介</el-button>
              <el-button
                link
                type="danger"
                size="small"
                class="intro-btn"
                :loading="deleting === b.bookUrl"
                @click.stop="removeBook(b)"
              >删除</el-button>
            </span>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 简介弹层：点书名旁的 ⓘ 或长按卡片 -->
    <el-dialog v-model="introVisible" :title="introBook?.name" width="520px">
      <div class="intro-meta">
        <el-image
          v-if="introBook?.coverUrl"
          :src="introBook.coverUrl"
          fit="cover"
          class="intro-cover"
        />
        <div class="intro-text">
          <p class="intro-author">{{ introBook?.author }} {{ introBook?.kind ? "· " + introBook.kind : "" }}</p>
          <p class="intro-body">{{ introBook?.intro || "暂无简介" }}</p>
          <p class="intro-chapters" v-if="introBook?.totalChapterNum">
            共 {{ introBook.totalChapterNum }} 章
          </p>
        </div>
      </div>
      <template #footer>
        <el-button @click="introVisible = false">关闭</el-button>
        <el-button type="primary" @click="introBook && openReader(introBook)">开始阅读</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { shelfApi } from "../api";
import type { Book } from "../api/types";

const router = useRouter();
const books = ref<Book[]>([]);
const loading = ref(false);
const refreshing = ref(false);
const deleting = ref("");
const introVisible = ref(false);
const introBook = ref<Book | null>(null);

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

async function removeBook(b: Book) {
  const confirmed = await ElMessageBox.confirm(
    `确定将《${b.name}》移出书架？阅读进度与章节缓存会一并删除。`,
    "删除书籍",
    { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" }
  )
    .then(() => true)
    .catch(() => false);
  if (!confirmed) return;
  deleting.value = b.bookUrl;
  const r = await shelfApi.deleteBook({ bookUrl: b.bookUrl });
  deleting.value = "";
  if (r.isSuccess) {
    ElMessage.success(`已删除《${b.name}》`);
    await load();
  } else {
    ElMessage.error(r.errorMsg || "删除失败");
  }
}

onMounted(load);
</script>

<style scoped>
.shelf-bar { margin-bottom: 16px; display: flex; gap: 12px; align-items: center; }
.book-card { cursor: pointer; text-align: center; }
.book-cover {
  width: 90px; height: 120px; margin: 0 auto 8px; border-radius: 6px; display: block;
}
.book-cover.fallback {
  background: linear-gradient(135deg, #5b8def, #7c4dff);
  color: #fff; font-size: 32px; line-height: 120px; font-weight: 700;
}
.book-name { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.book-author { color: var(--el-text-color-secondary); font-size: 12px; }
.book-progress { color: var(--el-color-primary); font-size: 12px; margin-top: 4px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.book-foot { display: flex; align-items: center; justify-content: space-between; }
.book-foot-btns { display: flex; align-items: center; }
.intro-btn { padding: 0 4px; }
.intro-meta { display: flex; gap: 16px; }
.intro-cover { width: 100px; height: 136px; border-radius: 6px; flex-shrink: 0; }
.intro-body { line-height: 1.8; white-space: pre-wrap; color: var(--el-text-color-regular); }
.intro-author { color: var(--el-text-color-secondary); margin-top: 0; }
.intro-chapters { color: var(--el-color-primary); font-size: 12px; }
</style>
