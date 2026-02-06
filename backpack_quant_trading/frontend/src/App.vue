<template>
  <el-config-provider :locale="zhCn">
    <router-view />
  </el-config-provider>
</template>

<script setup>
import zhCn from 'element-plus/dist/locale/zh-cn.js'
</script>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: var(--font-sans);
  background: var(--color-bg);
  color: var(--color-text);
  -webkit-font-smoothing: antialiased;
}
#app { min-height: 100vh; }
.page { background: transparent; }
.page h2 { color: var(--color-text); font-weight: 700; letter-spacing: -0.02em; }
.page .empty { color: var(--color-text-muted); }
</style>
