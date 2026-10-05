/** axios 封装：/reader3 + ReturnData 解包（借鉴 web-vue3 的 request.ts，去登录态）。 */

import axios from "axios";
import { ElMessage } from "element-plus";
import type { ReturnData } from "./types";

const instance = axios.create({ baseURL: "/reader3", timeout: 60000 });

instance.interceptors.response.use(
  (resp) => resp,
  (error) => {
    ElMessage.error(`网络错误: ${error.message}`);
    return Promise.reject(error);
  }
);

export async function get<T>(url: string, params?: Record<string, unknown>): Promise<ReturnData<T>> {
  const resp = await instance.get<ReturnData<T>>(url, { params });
  return unpack(resp.data);
}

export async function post<T>(
  url: string,
  data?: unknown,
  params?: Record<string, unknown>,
  timeoutMs?: number
): Promise<ReturnData<T>> {
  const resp = await instance.post<ReturnData<T>>(url, data, {
    params,
    timeout: timeoutMs,
  });
  return unpack(resp.data);
}

function unpack<T>(body: ReturnData<T>): ReturnData<T> {
  if (!body || typeof body.isSuccess !== "boolean") {
    ElMessage.error("后端响应格式异常");
    throw new Error("bad ReturnData");
  }
  if (!body.isSuccess && body.errorMsg) {
    ElMessage.error(body.errorMsg);
  }
  return body;
}

/** GET SSE（多源搜索进度）。onMessage 收 {lastIndex, list}，end 时 resolve。 */
export function openSSE<T>(path: string, params: Record<string, unknown>, onMessage: (batch: T[]) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    const qs = new URLSearchParams(
      Object.entries(params).map(([k, v]) => [k, String(v)])
    ).toString();
    const es = new EventSource(`/reader3${path}?${qs}`);
    es.onmessage = (ev) => {
      try {
        const parsed = JSON.parse(ev.data);
        if (parsed && Array.isArray(parsed.data)) onMessage(parsed.data);
      } catch {
        /* 忽略非 JSON 帧 */
      }
    };
    es.addEventListener("end", () => {
      es.close();
      resolve();
    });
    es.addEventListener("error", () => {
      es.close();
      resolve(); // SSE 中断按结束处理
    });
  });
}
