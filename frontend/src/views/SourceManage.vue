<template>
  <div>
    <!-- 书源订阅 -->
    <el-card shadow="never" class="panel">
      <template #header>
        <div class="panel-head">
          <span>📖 书源订阅</span>
          <el-button size="small" :loading="refreshingAll" @click="refreshAll">刷新全部订阅</el-button>
        </div>
      </template>
      <div class="src-bar">
        <el-input v-model="subName" placeholder="订阅名称（可选）" style="width: 160px" />
        <el-input v-model="subLink" placeholder="订阅 URL（书源 JSON 集合）" />
        <el-button type="primary" :loading="adding" @click="addSub">添加并导入</el-button>
      </div>
      <el-table :data="subs" size="small">
        <el-table-column prop="name" label="名称" min-width="140" show-overflow-tooltip />
        <el-table-column prop="link" label="URL" min-width="240" show-overflow-tooltip />
        <el-table-column label="书源数" width="80">
          <template #default="{ row }">{{ row.sourceCount || "-" }}</template>
        </el-table-column>
        <el-table-column label="上次同步" width="160">
          <template #default="{ row }">
            <span v-if="row.lastSyncTime">{{ fmtTime(row.lastSyncTime) }}</span>
            <el-tag v-else type="danger" size="small">失败</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140">
          <template #default="{ row }">
            <el-button size="small" @click="refreshOne(row.link)">刷新</el-button>
            <el-popconfirm title="删除订阅？" @confirm="removeSub(row.link)">
              <template #reference>
                <el-button size="small" type="danger">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 批量校验 -->
    <el-card shadow="never" class="panel">
      <template #header>
        <div class="panel-head">
          <span>✅ 批量校验</span>
          <div class="panel-head-tools">
            <el-input v-model="keyword" placeholder="搜索关键词" style="width: 140px" size="small" />
            <el-button type="primary" size="small" :disabled="validating" @click="startValidate">
              {{ validating ? `校验中 ${done}/${total}` : "校验全部启用源" }}
            </el-button>
          </div>
        </div>
      </template>
      <el-progress
        v-if="validating || summary"
        :percentage="total ? Math.round((done / total) * 100) : 0"
        :status="summary ? 'success' : undefined"
      />
      <el-alert
        v-if="summary"
        :type="summary.rate >= 60 ? 'success' : 'warning'"
        :closable="false"
        class="rate-alert"
        :title="`成功率 ${summary.rate}%：${summary.ok} 成功 / ${summary.failed} 失败（共 ${summary.total} 源）`"
      />
      <div class="filter-bar">
        <el-radio-group v-model="filterMode" size="small">
          <el-radio-button value="all">全部 ({{ sources.length }})</el-radio-button>
          <el-radio-button value="invalid">失效 ({{ invalidCount }})</el-radio-button>
        </el-radio-group>
      </div>
      <el-table :data="filteredSources" size="small" max-height="420" v-loading="loading">
        <el-table-column prop="bookSourceName" label="名称" min-width="160" show-overflow-tooltip />
        <el-table-column prop="bookSourceGroup" label="分组" width="120" show-overflow-tooltip />
        <el-table-column label="校验" width="90">
          <template #default="{ row }">
            <el-tag v-if="checkMap[row.bookSourceUrl] === true" type="success" size="small">通过</el-tag>
            <el-tag v-else-if="checkMap[row.bookSourceUrl] === false" type="danger" size="small">失效</el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="错误" min-width="160">
          <template #default="{ row }">
            <span class="err-text">{{ row.error || "" }}</span>
          </template>
        </el-table-column>
        <el-table-column label="启用" width="90">
          <template #default="{ row }">
            <el-tag :type="row.enabled ? 'success' : 'info'" size="small">{{ row.enabled ? "启用" : "停用" }}</el-tag>
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
    </el-card>

    <!-- 手动导入 -->
    <el-card shadow="never" class="panel">
      <template #header><span>📥 手动导入</span></template>
      <div class="src-bar">
        <el-input v-model="remoteUrl" placeholder="粘贴书源 JSON 文件 URL 或直接粘贴 JSON 内容" />
        <el-button type="primary" :loading="importing" @click="doImport">导入书源</el-button>
        <el-upload :show-file-list="false" :auto-upload="false" accept=".json" :on-change="onFile">
          <el-button>从文件导入</el-button>
        </el-upload>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import type { UploadFile } from "element-plus";
import { sourcesApi, subsApi, validateSources } from "../api";
import type { BookSourceSimple, BookSourceSub, ValidateFrame, ValidateSummary } from "../api";

const sources = ref<(BookSourceSimple & { error?: string })[]>([]);
const checkMap = ref<Record<string, boolean>>({});
const loading = ref(false);
const importing = ref(false);
const remoteUrl = ref("");

const subs = ref<BookSourceSub[]>([]);
const subLink = ref("");
const subName = ref("");
const adding = ref(false);
const refreshingAll = ref(false);

const validating = ref(false);
const done = ref(0);
const total = ref(0);
const summary = ref<ValidateSummary | null>(null);
const keyword = ref("我的");
const filterMode = ref<"all" | "invalid">("all");

const invalidCount = computed(
  () => Object.values(checkMap.value).filter((v) => v === false).length
);
const filteredSources = computed(() => {
  if (filterMode.value === "invalid") {
    return sources.value.filter((s) => checkMap.value[s.bookSourceUrl] === false);
  }
  return sources.value;
});

function fmtTime(ts: number) {
  return new Date(ts).toLocaleString("zh-CN", { hour12: false });
}

async function load() {
  loading.value = true;
  const r = await sourcesApi.getBookSources(false);
  if (r.isSuccess) {
    // 带出后端记录的最近校验错误（bookSource 数据里的字段由后端补充）
    sources.value = r.data as (BookSourceSimple & { error?: string })[];
  }
  const s = await subsApi.list();
  if (s.isSuccess) subs.value = s.data;
  loading.value = false;
}

async function addSub() {
  const link = subLink.value.trim();
  if (!link) return;
  adding.value = true;
  const r = await subsApi.add(link, subName.value.trim());
  adding.value = false;
  if (r.isSuccess) {
    ElMessage.success(`订阅导入 ${r.data?.count ?? 0} 个书源`);
    subLink.value = "";
    subName.value = "";
    await load();
  }
}

async function refreshOne(link: string) {
  const r = await subsApi.refresh(link);
  if (r.isSuccess) ElMessage.success("订阅已刷新");
  await load();
}

async function refreshAll() {
  refreshingAll.value = true;
  const r = await subsApi.refresh();
  refreshingAll.value = false;
  if (r.isSuccess) {
    const results = r.data as { ok: boolean; count: number; link: string }[];
    const okCount = results.filter((x) => x.ok).length;
    ElMessage.success(`刷新完成：${okCount}/${results.length} 个订阅成功`);
    await load();
  }
}

async function removeSub(link: string) {
  const r = await subsApi.remove(link);
  if (r.isSuccess) {
    ElMessage.success("已删除订阅");
    await load();
  }
}

function startValidate() {
  validating.value = true;
  done.value = 0;
  total.value = 0;
  summary.value = null;
  checkMap.value = {};
  validateSources(
    { keyword: keyword.value, concurrency: 12 },
    (frame: ValidateFrame) => {
      total.value = frame.total;
      done.value = frame.done;
      checkMap.value[frame.bookSourceUrl] = frame.ok;
      const src = sources.value.find((s) => s.bookSourceUrl === frame.bookSourceUrl);
      if (src) src.error = frame.error;
    }
  ).then((sum) => {
    validating.value = false;
    if (sum) {
      summary.value = sum;
      ElMessage.success(`校验完成：成功率 ${sum.rate}%`);
    } else {
      ElMessage.warning("校验中断");
    }
  });
}

async function doImport() {
  const input = remoteUrl.value.trim();
  if (!input) return;
  importing.value = true;
  try {
    if (input.startsWith("http")) {
      const r = await sourcesApi.saveFromRemoteSource(input);
      if (r.isSuccess) {
        ElMessage.success(`导入 ${r.data} 个书源`);
        remoteUrl.value = "";
        await load();
      }
      return;
    }
    const payload = JSON.parse(input);
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
  remoteUrl.value = await (file.raw as File).text();
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
.panel { margin-bottom: 16px; }
.panel-head { display: flex; justify-content: space-between; align-items: center; }
.panel-head-tools { display: flex; gap: 8px; align-items: center; }
.src-bar { display: flex; gap: 12px; margin-bottom: 12px; }
.filter-bar { margin: 8px 0; }
.err-text { color: var(--el-color-danger); font-size: 12px; }
.rate-alert { margin: 8px 0; }
</style>
