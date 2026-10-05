/** 换源后的阅读进度迁移（借鉴 web-vue3 utils/progressRelocate）：
 *  章节序号保留 → 新目录里按标题精确匹配 → 越界时钳制到末章。 */

export interface RelocateInput {
  oldIndex: number;
  oldTitle?: string | null;
  newTitles: string[];
}

export interface RelocateResult {
  index: number;
  strategy: "index" | "title" | "clamped";
}

export function relocateProgress({ oldIndex, oldTitle, newTitles }: RelocateInput): RelocateResult {
  const n = newTitles.length;
  if (n === 0) return { index: 0, strategy: "clamped" };

  // 1. 序号直接保留
  if (oldIndex >= 0 && oldIndex < n) {
    // 标题能精确对上时确认迁移质量更高；对不上也保留序号（多数换源目录相近）
    if (oldTitle && newTitles[oldIndex] === oldTitle) {
      return { index: oldIndex, strategy: "title" };
    }
    return { index: oldIndex, strategy: "index" };
  }

  // 2. 序号越界：按标题找
  if (oldTitle) {
    const idx = newTitles.indexOf(oldTitle);
    if (idx >= 0) return { index: idx, strategy: "title" };
  }

  // 3. 钳制到末章
  return { index: n - 1, strategy: "clamped" };
}
