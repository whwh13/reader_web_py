<template>
  <el-dialog v-model="visible" title="换源" width="560px" @open="loadSources">
    <div v-loading="loading" element-loading-text="全源精搜中…">
      <el-alert
        v-if="loading"
        type="info"
        :closable="false"
        class="wait-alert"
        title="正在扫描全部启用书源查找候选，慢源较多时需要 3-7 分钟，完成后自动显示"
      />
      <el-empty v-if="!loading && candidates.length === 0" description="没有找到其他书源" />
      <el-table
        v-if="candidates.length"
        :data="candidates"
        size="small"
        max-height="380"
        highlight-current-row
        @current-change="(row: Book | null) => (selected = row)"
      >
        <el-table-column prop="name" label="书名" min-width="150" show-overflow-tooltip />
        <el-table-column label="书源" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">
            <span>{{ row.originName }}</span>
            <el-tag v-if="isCurrent(row)" size="small" type="info" class="current-tag">当前源</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="latestChapterTitle" label="最新章节" min-width="130" show-overflow-tooltip />
      </el-table>
    </div>
    <template #footer>
      <span v-if="switching" class="switching-tip">正在换源并迁移进度…</span>
      <span v-else-if="isSelectedCurrent" class="switching-tip">已选中当前源</span>
      <el-button @click="visible = false">取消</el-button>
      <el-button
        type="primary"
        :disabled="!selected || switching || isSelectedCurrent"
        @click="doSwitch"
      >切换到选中源</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { ElMessage } from "element-plus";
import { booksApi } from "../api";
import type { Book } from "../api/types";
import { relocateProgress } from "../utils/progressRelocate";

const props = defineProps<{
  bookUrl: string;
  currentIndex: number;
  currentTitle?: string | null;
  currentOrigin?: string | null;
  currentOriginName?: string | null;
}>();
const emit = defineEmits<{
  switched: [payload: { newBookUrl: string; index: number; newSourceName: string }];
}>();

const visible = ref(false);
const loading = ref(false);
const switching = ref(false);
const candidates = ref<Book[]>([]);
const selected = ref<Book | null>(null);

function isCurrent(b: Book): boolean {
  if (props.currentOrigin) return b.origin === props.currentOrigin;
  return b.bookUrl === props.bookUrl;
}

const isSelectedCurrent = computed(() => !!selected.value && isCurrent(selected.value));

function open() {
  visible.value = true;
}

async function loadSources() {
  loading.value = true;
  candidates.value = [];
  selected.value = null;
  const r = await booksApi.getAvailableBookSource(props.bookUrl);
  if (r.isSuccess) {
    // 当前源也保留在列表中（标记"当前源"，选中时禁用切换）
    candidates.value = (r.data.list || []).filter((b) => b.bookUrl);
    // 当前源排到最前面，方便一眼确认
    candidates.value.sort((a, b) => Number(isCurrent(b)) - Number(isCurrent(a)));
  }
  loading.value = false;
}

async function doSwitch() {
  if (!selected.value) return;
  switching.value = true;
  try {
    const target = selected.value;
    const rd = await booksApi.setBookSource(props.bookUrl, target.origin, target.bookUrl);
    if (!rd.isSuccess) return;

    // 进度迁移：取新目录，按 标题→序号→钳制 定位
    let index = props.currentIndex;
    const toc = await booksApi.getChapterList(target.bookUrl);
    if (toc.isSuccess && toc.data.length) {
      const relocated = relocateProgress({
        oldIndex: props.currentIndex,
        oldTitle: props.currentTitle,
        newTitles: toc.data.map((c) => c.title),
      });
      index = relocated.index;
    }

    visible.value = false;
    ElMessage.success(`已切换到「${target.originName || target.origin}」`);
    emit("switched", {
      newBookUrl: target.bookUrl,
      index,
      newSourceName: target.originName || target.origin || "",
    });
  } finally {
    switching.value = false;
  }
}

defineExpose({ open });
</script>

<style scoped>
.switching-tip { color: var(--el-text-color-secondary); margin-right: 12px; font-size: 12px; }
.current-tag { margin-left: 6px; }
.wait-alert { margin-bottom: 10px; }
</style>
