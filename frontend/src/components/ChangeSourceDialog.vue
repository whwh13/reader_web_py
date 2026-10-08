<template>
  <el-dialog v-model="visible" title="换源" width="560px" @open="loadSources">
    <div>
      <el-alert
        v-if="loading"
        type="info"
        :closable="false"
        class="wait-alert"
        :title="`正在扫描全部启用书源（${done}/${total}）… 命中的候选会实时显示在下方`"
      />
      <el-progress
        v-if="loading && total > 0"
        :percentage="Math.round((done / total) * 100)"
        :stroke-width="6"
        class="scan-progress"
      />
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
      <el-empty
        v-if="!loading && candidates.length === 0"
        description="没有找到其他书源"
      />
    </div>
    <template #footer>
      <span v-if="switching" class="switching-tip">正在换源并迁移进度…</span>
      <span v-else-if="isSelectedCurrent" class="switching-tip">已选中当前源</span>
      <el-button @click="cancelScan">取消</el-button>
      <el-button
        type="primary"
        :disabled="!selected || switching"
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
const done = ref(0);
const total = ref(0);
let es: EventSource | null = null;

function isCurrent(b: Book): boolean {
  if (props.currentOrigin) return b.origin === props.currentOrigin;
  return b.bookUrl === props.bookUrl;
}

const isSelectedCurrent = computed(() => !!selected.value && isCurrent(selected.value));

function open() {
  visible.value = true;
}

function cancelScan() {
  es?.close();
  es = null;
  loading.value = false;
  visible.value = false;
}

function loadSources() {
  loading.value = true;
  candidates.value = [];
  selected.value = null;
  done.value = 0;
  total.value = 0;
  const promise = booksApi.getAvailableBookSourceSSE(
    { url: props.bookUrl },
    (frame) => {
      done.value = frame.done;
      total.value = frame.total;
      if (frame.book) {
        // 命中即追加（同源去重：bookUrl 相同不重复加）
        if (frame.book.bookUrl && !candidates.value.some((b) => b.bookUrl === frame.book!.bookUrl)) {
          candidates.value.push(frame.book);
        }
      }
    }
  );
  promise.then((r) => {
    loading.value = false;
    es = null;
    if (r === null) ElMessage.warning("换源扫描中断");
    // 当前源排到最前面，方便一眼确认
    candidates.value.sort((a, b) => Number(isCurrent(b)) - Number(isCurrent(a)));
  });
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
.scan-progress { margin-bottom: 10px; }
</style>
