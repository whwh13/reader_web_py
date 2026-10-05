import { createRouter, createWebHashHistory } from "vue-router";

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: "/", name: "shelf", component: () => import("../views/Bookshelf.vue") },
    { path: "/search", name: "search", component: () => import("../views/Search.vue") },
    { path: "/sources", name: "sources", component: () => import("../views/SourceManage.vue") },
    { path: "/reader", name: "reader", component: () => import("../views/Reader.vue") },
    { path: "/settings", name: "settings", component: () => import("../views/Settings.vue") },
  ],
});
