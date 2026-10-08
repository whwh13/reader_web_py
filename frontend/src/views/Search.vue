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
      <el-button type="primary" size="large" :loading="searching" @click="doSearch">
        {{ searching ? "搜索中…" : "搜索" }}
      </el-button>
    </div>
    <div v-if="searching" class="search-tip">
      全源搜索中（{{ searchedSources }}/{{ totalSources }} 源）… 已聚合 {{ groups.length }} 本
    </div>
    <div v-else-if="searched" class="search-tip">
      搜索完成：{{ groups.length }} 本（来自 {{ totalSources }} 个启用书源）
      <el-button v-if="canContinue" link type="primary" @click="continueSearch">继续搜更多</el-button>
    </div>
    <el-table :data="groups" v-loading="searching && groups.length === 0">
      <el-table-column label="书名" min-width="200">
        <template #default="{ row }">
          {{ row.book.name }}
          <el-tag v-if="row.sourceCount > 1" size="small" type="primary" class="src-count">
            {{ row.sourceCount }} 个来源
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="book.author" label="作者" width="140" />
      <el-table-column label="首个来源" width="160">
        <template #default="{ row }">{{ row.book.originName || row.book.origin }}</template>
      </el-table-column>
      <el-table-column prop="book.latestChapterTitle" label="最新章节" min-width="180" />
      <el-table-column label="操作" width="200">
        <template #default="{ row }">
          <el-button size="small" type="primary" @click.stop="addToShelf(row.book)">入架</el-button>
          <el-button
            v-if="row.sourceCount > 1"
            size="small"
            @click.stop="toggleExpand(row)"
          >选来源</el-button>
        </template>
      </el-table-column>
    </el-table>
    <!-- 同书的多来源选择弹窗（点"选来源"弹出，右上角叉号关闭） -->
    <el-dialog
      v-model="expandVisible"
      :title="expandedGroup ? `《${expandedGroup.book.name}》的 ${expandedGroup.sourceCount} 个来源` : ''"
      width="640px"
      :show-close="true"
      :close-on-click-modal="false"
    >
      <el-table v-if="expandedGroup" :data="expandedGroup.sources" size="small" max-height="420">
        <el-table-column prop="originName" label="来源" width="150" show-overflow-tooltip />
        <el-table-column prop="author" label="作者" width="120" show-overflow-tooltip />
        <el-table-column prop="latestChapterTitle" label="最新章节" min-width="160" show-overflow-tooltip />
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="addToShelf(row)">入架</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
    <el-empty
      v-if="!searching && searched && groups.length === 0"
      :description="`全部 ${totalSources} 个启用源均未搜到「${lastKeyword}」`"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { ElMessage } from "element-plus";
import { searchMultiSSE, shelfApi } from "../api";
import type { Book, GroupedSearchResult } from "../api/types";

const keyword = ref("");
const lastKeyword = ref("");
const groups = ref<GroupedSearchResult[]>([]);
const searching = ref(false);
const searched = ref(false);
const searchedSources = ref(0);
const totalSources = ref(0);
const lastIndex = ref(0);
const canContinue = ref(false);
const expandVisible = ref(false);
const expandedGroup = ref<GroupedSearchResult | null>(null);
const added = new Set<string>();

function groupKey(g: GroupedSearchResult) {
  // 聚合键只看书名：同名即聚合一组（源站作者元数据常乱填/缺失，
  // 严格 (name, author) 会把同一本书拆散）；组内展开可见各来源的作者差异
  return g.book.name;
}

/** 相关性档位：精确同名 > 名以前缀 > 名含词 > 垃圾条目（访问受限/安全检测）。 */
function relevanceRank(g: GroupedSearchResult, key: string): number {
  const name = (g.book.name || "").trim();
  const clean = name.replace(/[\s*r]</g, "");
  if (!name || /访问受限|安全检测|人机验证/.test(name)) return 9;
  if (name === key) return 0;
  if (name.startsWith(key)) return 1;
  if (name.includes(key)) return 2;
  return 3;
}

/** 每帧到达后重排：相关性升序为主，同档内多来源优先（更多人收录的书更可能是对的），再按最早出现序。 */
function sortGroups() {
  const key = lastKeyword.value;
  const order = new Map(groups.value.map((g, i) => [groupKey(g), i]));
  groups.value.sort((a, b) => {
    const ra = relevanceRank(a, key);
    const rb = relevanceRank(b, key);
    if (ra !== rb) return ra - rb;
    if (b.sourceCount !== a.sourceCount) return b.sourceCount - a.sourceCount;
    return (order.get(groupKey(a)) ?? 0) - (order.get(groupKey(b)) ?? 0);
  });
}

function toggleExpand(g: GroupedSearchResult) {
  expandedGroup.value = g;
  expandVisible.value = true;
}

async function doSearch() {
  const key = keyword.value.trim();
  if (!key || searching.value) return;
  lastKeyword.value = key;
  searching.value = true;
  searched.value = true;
  groups.value = [];
  added.clear();
  searchedSources.value = 0;
  lastIndex.value = 0;
  canContinue.value = false;
  expandVisible.value = false;
  expandedGroup.value = null;
  await runSearch(key, 0);
}

async function continueSearch() {
  if (searching.value) return;
  searching.value = true;
  canContinue.value = false;
  await runSearch(lastKeyword.value, lastIndex.value);
}

async function runSearch(key: string, from: number) {
  const final = await searchMultiSSE(
    { key, concurrentCount: 48, aggregate: true },
    (frame) => {
      if (frame.lastIndex > 0) {
        searchedSources.value = frame.lastIndex;
        lastIndex.value = frame.lastIndex;
      }
      for (const g of frame.groups || []) {
        const k = g.book.name;
        const existing = groups.value.find((x) => groupKey(x) === k);
        if (existing) {
          // 后续帧出现同书：合并来源
          existing.sourceCount += g.sourceCount;
          existing.sources.push(...g.sources);
        } else if (!added.has(k)) {
          added.add(k);
          groups.value.push(g);
        }
      }
      sortGroups();
    }
  );
  searching.value = false;
  if (final === null) {
    ElMessage.warning("搜索中断");
    return;
  }
  if (final.totalSources) totalSources.value = final.totalSources;
  // isEnd=false 说明因条数上限截断，允许续搜
  canContinue.value = !final.isEnd && final.lastIndex > 0;
  sortGroups();
}

async function addToShelf(b: Book) {
  const r = await shelfApi.saveBook({
    name: b.name,
    author: b.author,
    bookUrl: b.bookUrl,
    origin: b.origin,
    originName: b.originName,
    originOrder: b.originOrder ?? 0,
    coverUrl: b.coverUrl,
    intro: b.intro,
    kind: b.kind,
    totalChapterNum: b.totalChapterNum ?? 0,
    latestChapterTitle: b.latestChapterTitle,
  });
  if (r.isSuccess) ElMessage.success(`《${b.name}》已加入书架（${b.originName || b.origin}）`);
}
</script>

<style scoped>
.search-bar { display: flex; gap: 12px; margin-bottom: 16px; }
.search-tip { color: var(--el-text-color-secondary); margin-bottom: 8px; }
.src-count { margin-left: 6px; }
:deep(.el-table__row) { cursor: default; }
</style>
