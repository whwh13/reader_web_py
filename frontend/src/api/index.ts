/** 按域拆分的 API 模块 */

import { get, post } from "./request";
import type { Book, BookChapter, BookSourceSimple } from "./types";

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
