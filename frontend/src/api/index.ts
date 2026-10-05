/** 按域拆分的 API 模块 */

import { get, post } from "./request";
import type { Book, BookChapter, BookSourceSimple } from "./types";

export type { Book, BookChapter, BookSourceSimple } from "./types";

export const shelfApi = {
  getBookshelf: (refresh = false) =>
    get<Book[]>("/getBookshelf", { refresh: refresh ? 1 : 0, v: Date.now() }),
  getShelfBook: (url: string) => post<Book>("/getShelfBook", { url }),
  saveBook: (book: Partial<Book>) => post<unknown>("/saveBook", book, { v: Date.now() }),
  deleteBook: (book: Partial<Book>) => post<unknown>("/deleteBook", book, { v: Date.now() }),
  saveProgress: (p: {
    url: string;
    index: number;
    durChapterIndex: number;
    durChapterPos: number;
    durChapterTime: number;
    durChapterTitle: string;
    name: string;
    author: string;
  }) => post<unknown>("/saveBookProgress", p),
};

export const booksApi = {
  getBookInfo: (bookSourceUrl: string, url: string) =>
    post<Book>("/getBookInfo", { bookSourceUrl, url }),
  getChapterList: (url: string, refresh = false, bookSourceUrl?: string) =>
    post<BookChapter[]>("/getChapterList", { url, refresh: refresh ? 1 : 0, bookSourceUrl }),
  getBookContent: (url: string, index: number, refresh = false, bookSourceUrl?: string) =>
    post<string>("/getBookContent", { url, index, refresh: refresh ? 1 : 0, bookSourceUrl }),
  /** 换源：getAvailableBookSource 返回 {lastIndex, list}；全源精搜较慢（1-3 分钟） */
  getAvailableBookSource: (url: string, refresh = false) =>
    post<{ lastIndex: number; list: Book[] }>(
      "/getAvailableBookSource",
      { url, refresh: refresh ? 1 : 0 },
      undefined,
      300000
    ),
  setBookSource: (bookUrl: string, bookSourceUrl: string, newUrl: string) =>
    post<unknown>("/setBookSource", { bookUrl, bookSourceUrl, newUrl }),
};

export const searchApi = {
  searchBook: (key: string, bookSourceUrl: string, page = 1) =>
    get<Book[]>("/searchBook", { key, bookSourceUrl, page, concurrentCount: 16, lastIndex: -1, v: Date.now() }),
};

export const sourcesApi = {
  getBookSources: (simple = true) =>
    get<BookSourceSimple[]>("/getBookSources", { simple: simple ? 1 : 0, v: Date.now() }),
  saveBookSources: (sources: unknown[]) => post<number>("/saveBookSources", { bookSources: sources }),
  saveFromRemoteSource: (url: string) => post<number>("/saveFromRemoteSource", { url }),
  deleteBookSource: (bookSourceUrl: string) =>
    post<unknown>("/deleteBookSources", { bookSourceUrls: [bookSourceUrl] }),
};

export interface BookSourceSub {
  link: string;
  name: string;
  lastSyncTime: number;
  sourceCount: number;
  lastError?: string | null;
}

export const subsApi = {
  list: () => get<BookSourceSub[]>("/getBookSourceSubs"),
  add: (link: string, name = "") => post<{ count: number }>("/saveBookSourceSub", { link, name }),
  remove: (link: string) => post<unknown>("/deleteBookSourceSub", { link }),
  refresh: (link?: string) => post<unknown>("/refreshBookSourceSub", link ? { link } : {}),
};

export interface ValidateFrame {
  bookSourceUrl: string;
  bookSourceName: string;
  ok: boolean;
  count: number;
  elapsed: number;
  error?: string;
  done: number;
  total: number;
}

export interface ValidateSummary {
  total: number;
  ok: number;
  failed: number;
  rate: number;
}

/** 批量校验 SSE：逐源回调，end 时 resolve 汇总。 */
export function validateSources(
  opts: { keyword?: string; concurrency?: number },
  onFrame: (frame: ValidateFrame) => void
): Promise<ValidateSummary | null> {
  return new Promise((resolve) => {
    const qs = new URLSearchParams(
      Object.entries({ keyword: opts.keyword || "我的", concurrency: String(opts.concurrency || 12) })
    ).toString();
    const es = new EventSource(`/reader3/validateBookSourcesSSE?${qs}`);
    es.addEventListener("end", (ev) => {
      es.close();
      try {
        resolve(JSON.parse((ev as MessageEvent).data));
      } catch {
        resolve(null);
      }
    });
    es.addEventListener("error", () => {
      es.close();
      resolve(null);
    });
    es.onmessage = (ev) => {
      try {
        onFrame(JSON.parse(ev.data));
      } catch {
        /* 忽略坏帧 */
      }
    };
  });
}
