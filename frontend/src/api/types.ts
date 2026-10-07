/** 领域类型（与 /reader3 契约对齐） */

export interface ReturnData<T = unknown> {
  isSuccess: boolean;
  errorMsg: string;
  data: T;
}

export interface Book {
  bookUrl: string;
  tocUrl?: string;
  origin: string;
  originName?: string;
  originOrder?: number;
  name: string;
  author: string;
  kind?: string | null;
  coverUrl?: string | null;
  intro?: string | null;
  wordCount?: string | null;
  latestChapterTitle?: string | null;
  totalChapterNum?: number;
  durChapterIndex?: number;
  durChapterPos?: number;
  durChapterTime?: number;
  durChapterTitle?: string | null;
  [key: string]: unknown;
}

export interface BookChapter {
  url: string;
  title: string;
  index: number;
  baseUrl?: string;
  bookUrl?: string;
  isVolume?: boolean;
  isVip?: boolean;
  tag?: string | null;
}

export interface BookSourceSimple {
  bookSourceUrl: string;
  bookSourceName: string;
  bookSourceGroup?: string | null;
  enabled: boolean;
  customOrder: number;
  subLink?: string | null;
}

export interface SearchResult extends Book {
  lastIndex?: number;
}
