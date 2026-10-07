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
            <el-button size="small" type="danger" @click="removeSub(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 批量校验 / 书源管理 -->
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
      <!-- 分组 tag 筛选 -->
      <div class="filter-bar">
        <el-tag
          class="f-tag"
          :type="filterMode === 'all' ? 'primary' : 'info'"
          effect="plain"
          @click="filterMode = 'all'"
        >全部 {{ sources.length }}</el-tag>
        <el-tag
          class="f-tag"
          :type="filterMode === 'invalid' ? 'danger' : 'warning'"
          effect="plain"
          @click="toggleFilter('invalid')"
        >失效 {{ invalidCount }}</el-tag>
        <el-tag
          v-for="g in groups"
          :key="g.name"
          class="f-tag"
          :type="filterMode === g.name ? 'primary' : 'info'"
          effect="plain"
          @click="toggleFilter(g.name)"
        >{{ g.name }} {{ g.count }}</el-tag>
      </div>
      <!-- 批量操作栏（选中书源后出现） -->
      <div v-if="selected.length" class="batch-bar">
        <span class="batch-info">已选 {{ selected.length }} 个书源</span>
        <el-button size="small" type="success" :disabled="validating" @click="batchSetEnabled(true)">启用</el-button>
        <el-button size="small" :disabled="validating" @click="batchSetEnabled(false)">停用</el-button>
        <el-button size="small" type="primary" :disabled="validating" @click="validateSelected">
          {{ validating ? `校验中 ${done}/${total}` : "校验选中" }}
        </el-button>
        <el-button size="small" type="danger" :disabled="validating" @click="batchRemove">删除</el-button>
        <el-button size="small" text @click="clearSelection">取消选择</el-button>
      </div>
      <el-table
        ref="tableRef"
        :data="filteredSources"
        size="small"
        max-height="420"
        v-loading="loading"
        @selection-change="onSelectionChange"
      >
        <el-table-column type="selection" width="42" />
        <el-table-column prop="bookSourceName" label="名称" min-width="150" show-overflow-tooltip />
        <el-table-column label="分组" width="110" show-overflow-tooltip>
          <template #default="{ row }">{{ row.bookSourceGroup || "-" }}</template>
        </el-table-column>
        <el-table-column label="来源" width="110" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.subLink" class="sub-link-text">{{ subDisplayName(row.subLink) }}</span>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="校验" width="90">
          <template #default="{ row }">
            <el-tag v-if="checkMap[row.bookSourceUrl] === true" type="success" size="small">通过</el-tag>
            <el-tag v-else-if="checkMap[row.bookSourceUrl] === false" type="danger" size="small">失效</el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="错误" min-width="140">
          <template #default="{ row }">
            <span class="err-text">{{ row.error || "" }}</span>
          </template>
        </el-table-column>
        <el-table-column label="启用" width="80">
          <template #default="{ row }">
            <el-switch v-model="row.enabled" size="small" :disabled="validating" @change="toggleEnabled(row)" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90">
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
import { ElMessage, ElMessageBox } from "element-plus";
import type { TableInstance, UploadFile } from "element-plus";
import { sourcesApi, subsApi, validateSources } from "../api";
import type { BookSourceSimple, BookSourceSub, ValidateFrame, ValidateSummary } from "../api";

type SourceRow = BookSourceSimple & { error?: string; lastCheckOk?: boolean };

const sources = ref<SourceRow[]>([]);
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

const tableRef = ref<TableInstance>();
const selected = ref<SourceRow[]>([]);
const filterMode = ref<string>("all");

const invalidCount = computed(
  () => Object.values(checkMap.value).filter((v) => v === false).length
);
const groups = computed(() => {
  const counter = new Map<string, number>();
  for (const s of sources.value) {
    const g = (s.bookSourceGroup || "").trim();
    if (g) counter.set(g, (counter.get(g) || 0) + 1);
  }
  return [...counter.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([name, count]) => ({ name, count }));
});
const filteredSources = computed(() => {
  if (filterMode.value === "invalid") {
    return sources.value.filter((s) => checkMap.value[s.bookSourceUrl] === false);
  }
  if (filterMode.value === "all") return sources.value;
  return sources.value.filter((s) => (s.bookSourceGroup || "").trim() === filterMode.value);
});

function toggleFilter(v: string) {
  filterMode.value = filterMode.value === v ? "all" : v;
}

function fmtTime(ts: number) {
  return new Date(ts).toLocaleString("zh-CN", { hour12: false });
}

function subDisplayName(link: string) {
  const sub = subs.value.find((x) => x.link === link);
  if (sub) return sub.name || sub.link;
  return link.replace(/^https?:\/\//, "");
}

async function load() {
  loading.value = true;
  const r = await sourcesApi.getBookSources(false);
  if (r.isSuccess) {
    sources.value = r.data as SourceRow[];
    // 用后端记录的校验结果初始化 checkMap（本次会话已校验的以会话结果为准）
    const seeded: Record<string, boolean> = {};
    for (const s of sources.value) {
      if (s.lastCheckOk !== undefined) seeded[s.bookSourceUrl] = s.lastCheckOk;
    }
    checkMap.value = { ...seeded, ...checkMap.value };
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

async function removeSub(row: BookSourceSub) {
  const action = await ElMessageBox.confirm(
    `是否同时删除该订阅导入的 ${row.sourceCount || 0} 个书源？（仅删除订阅则书源保留，来源标记变灰）`,
    `删除订阅「${row.name || row.link}」`,
    {
      type: "warning",
      confirmButtonText: "删除订阅并删除书源",
      cancelButtonText: "仅删除订阅",
      distinguishCancelAndClose: true,
    }
  )
    .then(() => true)
    .catch((a: string) => (a === "cancel" ? false : null));
  if (action === null) return;
  const r = await subsApi.remove(row.link, action);
  if (r.isSuccess) {
    ElMessage.success(action ? `已删除订阅及 ${r.data?.removed ?? 0} 个书源` : "已删除订阅（书源保留）");
    await load();
  }
}

function onSelectionChange(rows: SourceRow[]) {
  selected.value = rows;
}

function clearSelection() {
  tableRef.value?.clearSelection();
}

async function toggleEnabled(row: SourceRow) {
  const r = await sourcesApi.enableBookSources([row.bookSourceUrl], row.enabled);
  if (r.isSuccess) {
    ElMessage.success(row.enabled ? "已启用" : "已停用");
  } else {
    row.enabled = !row.enabled;
    ElMessage.error(r.errorMsg || "操作失败");
  }
}

async function batchSetEnabled(enabled: boolean) {
  const urls = selected.value.map((s) => s.bookSourceUrl);
  const r = await sourcesApi.enableBookSources(urls, enabled);
  if (r.isSuccess) {
    for (const row of selected.value) row.enabled = enabled;
    ElMessage.success(`已${enabled ? "启用" : "停用"} ${r.data?.updated ?? urls.length} 个书源`);
  } else {
    ElMessage.error(r.errorMsg || "操作失败");
  }
}

async function batchRemove() {
  const urls = selected.value.map((s) => s.bookSourceUrl);
  const confirmed = await ElMessageBox.confirm(
    `确定删除选中的 ${urls.length} 个书源？订阅来源导入的可通过刷新订阅恢复。`,
    "批量删除书源",
    { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" }
  )
    .then(() => true)
    .catch(() => false);
  if (!confirmed) return;
  const r = await sourcesApi.deleteBookSources(urls);
  if (r.isSuccess) {
    ElMessage.success(`已删除 ${urls.length} 个书源`);
    clearSelection();
    await load();
  }
}

function startValidate() {
  checkMap.value = {};
  runValidation(undefined);
}

function validateSelected() {
  const keys = selected.value.map((s) => s.bookSourceUrl);
  if (!keys.length || validating.value) return;
  runValidation(keys);
}

function runValidation(keys?: string[]) {
  validating.value = true;
  done.value = 0;
  total.value = 0;
  summary.value = null;
  validateSources(
    { keyword: keyword.value, concurrency: 12, keys },
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
      ElMessage.success(
        `校验完成：成功率 ${sum.rate}%${keys ? `（选中 ${keys.length} 源）` : ""}`
      );
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

async function remove(row: SourceRow) {
  const r = await sourcesApi.deleteBookSource(row.bookSourceUrl);
  if (r.isSuccess) {
    ElMessage.success("已删除");
    await load();
  }
}

onMounted(load);</script>

<style scoped>
.panel { margin-bottom: 16px; }
.panel-head { display: flex; justify-content: space-between; align-items: center; }
.panel-head-tools { display: flex; gap: 8px; align-items: center; }
.src-bar { display: flex; gap: 12px; margin-bottom: 12px; }
.filter-bar {
  margin: 8px 0;
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  max-height: 72px;
  overflow-y: auto;
}
.f-tag { cursor: pointer; user-select: none; }
.batch-bar {
  display: flex;
  gap: 10px;
  align-items: center;
  margin: 8px 0;
  padding: 6px 10px;
  background: var(--el-fill-color-light);
  border-radius: 6px;
}
.batch-info { font-size: 13px; color: var(--el-text-color-regular); }
.sub-link-text { color: var(--el-text-color-secondary); font-size: 12px; }
.err-text { color: var(--el-color-danger); font-size: 12px; }
.rate-alert { margin: 8px 0; }
</style>
