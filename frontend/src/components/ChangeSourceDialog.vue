<template>
  <el-dialog v-model="visible" title="换源" width="560px" @open="loadSources">
    <div v-loading="loading">
      <el-empty v-if="!loading && candidates.length === 0" description="没有找到其他书源" />
      <el-table
        v-else
        :data="candidates"
        size="small"
        max-height="380"
        highlight-current-row
        @current-change="(row: Book | null) => (selected = row)"
      >
        <el-table-column prop="name" label="书名" min-width="160" show-overflow-tooltip />
        <el-table-column prop="originName" label="书源" min-width="120" show-overflow-tooltip />
        <el-table-column prop="latestChapterTitle" label="最新章节" min-width="140" show-overflow-tooltip />
      </el-table>
    </div>
    <template #footer>
      <span v-if="switching" class="switching-tip">正在换源并迁移进度…</span>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :disabled="!selected || switching" @click="doSwitch">切换到选中源</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { ElMessage } from "element-plus";
import { booksApi } from "../api";
import type { Book } from "../api/types";
import { relocateProgress } from "../utils/progressRelocate";

const props = defineProps<{
  bookUrl: string;
  currentIndex: number;
  currentTitle?: string | null;
}>();
const emit = defineEmits<{
  switched: [payload: { newBookUrl: string; index: number; newSourceName: string }];
}>();

const visible = ref(false);
const loading = ref(false);
const switching = ref(false);
const candidates = ref<Book[]>([]);
const selected = ref<Book | null>(null);

function open() {
  visible.value = true;
}

async function loadSources() {
  loading.value = true;
  candidates.value = [];
  selected.value = null;
  const r = await booksApi.getAvailableBookSource(props.bookUrl);
  if (r.isSuccess) {
    // 排除当前源自身
    candidates.value = (r.data.list || []).filter(
      (b) => b.bookUrl && b.bookUrl !== props.bookUrl
    );
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
</style>
