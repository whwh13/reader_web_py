<template>
  <div>
    <div class="shelf-bar">
      <el-button type="primary" :loading="refreshing" @click="refreshShelf">刷新书架</el-button>
      <span v-if="books.length">{{ books.length }} 本</span>
    </div>
    <el-empty v-if="!loading && books.length === 0" description="书架空空如也，去搜索添加吧" />
    <el-row :gutter="16">
      <el-col v-for="b in books" :key="b.bookUrl" :span="4" style="margin-bottom: 16px">
        <el-card shadow="hover" class="book-card" @click="showDetail(b)">
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
          <div v-if="b.durChapterTitle" class="book-progress">读到:{{ b.durChapterTitle }}</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 书籍详情弹层：点卡片弹出，右上角叉号关闭 -->
    <el-dialog
      v-model="detailVisible"
      :title="detailBook?.name"
      width="560px"
      :show-close="true"
      :close-on-click-modal="false"
    >
      <div v-if="detailBook" class="detail-meta">
        <el-image
          v-if="detailBook.coverUrl"
          :src="detailBook.coverUrl"
          fit="cover"
          class="detail-cover"
        />
        <div v-else class="detail-cover fallback">{{ detailBook.name.slice(0, 1) }}</div>
        <div class="detail-text">
          <p class="detail-author">✍ {{ detailBook.author || "未知作者" }}</p>
          <p class="detail-origin">📚 来源：{{ detailBook.originName || detailBook.origin }}</p>
          <p v-if="detailBook.kind" class="detail-kind">🏷 {{ detailBook.kind }}</p>
          <p v-if="detailBook.totalChapterNum" class="detail-chapters">
            📄 共 {{ detailBook.totalChapterNum }} 章
          </p>
          <p v-if="detailBook.latestChapterTitle" class="detail-latest">
            ⏱ 最新：{{ detailBook.latestChapterTitle }}
          </p>
          <p v-if="detailBook.durChapterTitle" class="detail-progress">
            📍 读到：{{ detailBook.durChapterTitle }}
          </p>
        </div>
      </div>
      <div v-if="detailBook" class="detail-intro">
        <p class="detail-intro-title">简介</p>
        <p class="detail-intro-body">{{ detailBook.intro || "暂无简介" }}</p>
      </div>
      <template #footer>
        <el-button
          type="danger"
          plain
          :loading="deleting === detailBook?.bookUrl"
          @click="removeBook(detailBook!)"
        >删除书籍</el-button>
        <el-button @click="showToc(detailBook!)">目录</el-button>
        <el-button @click="openSourceSite(detailBook!)">打开源站</el-button>
        <el-button type="primary" @click="detailBook && openReader(detailBook)">继续阅读</el-button>
      </template>
    </el-dialog>

    <!-- 目录弹层 -->
    <el-dialog
      v-model="tocVisible"
      :title="detailBook ? `《${detailBook.name}》目录${toc.length ? `（${toc.length} 章）` : ''}` : '目录'"
      width="480px"
      :show-close="true"
    >
      <div v-loading="tocLoading" class="toc-list">
        <el-empty v-if="!tocLoading && toc.length === 0" description="目录为空（未缓存，进阅读器后加载）" />
        <div
          v-for="c in toc"
          :key="c.index"
          class="toc-item"
          :class="{ current: c.index === detailBook?.durChapterIndex }"
          @click="toc.length && openReaderAt(detailBook!, c.index)"
        >
          <span class="toc-title">{{ c.isVolume ? "▸ " : "" }}{{ c.title }}</span>
          <el-tag v-if="c.index === detailBook?.durChapterIndex" size="small" type="primary">当前</el-tag>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { booksApi, shelfApi } from "../api";
import type { Book, BookChapter } from "../api/types";

const router = useRouter();
const books = ref<Book[]>([]);
const loading = ref(false);
const refreshing = ref(false);
const deleting = ref("");
const detailVisible = ref(false);
const detailBook = ref<Book | null>(null);
const tocVisible = ref(false);
const tocLoading = ref(false);
const toc = ref<BookChapter[]>([]);

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

function showDetail(b: Book) {
  detailBook.value = b;
  detailVisible.value = true;
}

function openReader(b: Book) {
  router.push({ path: "/reader", query: { url: b.bookUrl } });
}

function openReaderAt(b: Book, index: number) {
  router.push({ path: "/reader", query: { url: b.bookUrl, jump: String(index) } });
}

async function showToc(b: Book) {
  tocVisible.value = true;
  tocLoading.value = true;
  toc.value = [];
  // refresh=0：只读缓存目录（不真请求；未缓存则提示进阅读器加载）
  const r = await booksApi.getChapterList(b.bookUrl, false, b.origin);
  tocLoading.value = false;
  if (r.isSuccess) toc.value = r.data;
}

function openSourceSite(b: Book) {
  // bookUrl 就是源站的这本书页面（部分源是接口 URL，打开后由源站自行处理）
  if (!b.bookUrl) {
    ElMessage.warning("该书没有可打开的源站地址");
    return;
  }
  window.open(b.bookUrl, "_blank", "noopener");
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
    detailVisible.value = false;
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
.detail-meta { display: flex; gap: 16px; }
.detail-cover { width: 100px; height: 136px; border-radius: 6px; flex-shrink: 0; }
.detail-cover.fallback {
  background: linear-gradient(135deg, #5b8def, #7c4dff);
  color: #fff; font-size: 32px; line-height: 136px; text-align: center; font-weight: 700;
}
.detail-text { flex: 1; min-width: 0; }
.detail-text p { margin: 0 0 6px; }
.detail-author { font-weight: 600; }
.detail-origin, .detail-kind, .detail-chapters, .detail-latest, .detail-progress {
  color: var(--el-text-color-regular); font-size: 13px;
}
.detail-progress { color: var(--el-color-primary); }
.detail-latest {
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.detail-intro { margin-top: 12px; border-top: 1px solid var(--el-border-color-lighter); padding-top: 10px; }
.detail-intro-title { font-weight: 600; margin: 0 0 6px; }
.detail-intro-body { line-height: 1.8; white-space: pre-wrap; color: var(--el-text-color-regular); margin: 0; }
.toc-list { max-height: 420px; overflow-y: auto; }
.toc-item {
  display: flex; justify-content: space-between; align-items: center;
  padding: 7px 10px; border-radius: 6px; cursor: pointer; font-size: 13px;
}
.toc-item:hover { background: var(--el-fill-color-light); }
.toc-item.current { color: var(--el-color-primary); background: var(--el-color-primary-light-9); }
.toc-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-right: 8px; }
</style>
