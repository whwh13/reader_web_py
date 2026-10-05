<template>
  <el-container class="app-shell">
    <el-aside width="180px" class="app-aside">
      <div class="app-title">阅读 <small>reader-py</small></div>
      <el-menu :default-active="route.fullPath" router>
        <el-menu-item index="/">📚 书架</el-menu-item>
        <el-menu-item index="/search">🔍 搜索</el-menu-item>
        <el-menu-item index="/sources">📖 书源管理</el-menu-item>
        <el-menu-item index="/settings">⚙️ 设置</el-menu-item>
      </el-menu>
    </el-aside>
    <el-main><router-view /></el-main>
  </el-container>
</template>

<script setup lang="ts">
import { useRoute } from "vue-router";
const route = useRoute();
</script>

<style>
.app-shell { height: 100vh; }
.app-aside { border-right: 1px solid var(--el-border-color-light); }
.app-title { font-size: 20px; font-weight: 700; padding: 18px 16px; }
.app-title small { color: var(--el-text-color-secondary); font-size: 12px; margin-left: 6px; }
body { margin: 0; }
</style>
