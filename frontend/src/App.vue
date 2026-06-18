<template>
  <el-container class="layout">
    <!-- 侧边栏 -->
    <el-aside width="220px" class="sidebar">
      <div class="logo">📊 审计系统</div>
      <el-menu
        :default-active="route.path"
        router
        background-color="#304156"
        text-color="#bfcbd9"
        active-text-color="#409EFF"
      >
        <el-menu-item index="/">
          <el-icon><HomeFilled /></el-icon>
          <span>首页</span>
        </el-menu-item>
        <el-sub-menu index="data">
          <template #title>
            <el-icon><FolderOpened /></el-icon>
            <span>数据管理</span>
          </template>
          <el-menu-item index="/data/import">
            <el-icon><Upload /></el-icon>
            <span>数据导入</span>
          </el-menu-item>
          <el-menu-item index="/data/companies">
            <el-icon><OfficeBuilding /></el-icon>
            <span>被审计单位</span>
          </el-menu-item>
        </el-sub-menu>
      </el-menu>
    </el-aside>

    <!-- 主内容 -->
    <el-container>
      <el-header class="header">
        <span class="title">审计系统基座 v0.1</span>
      </el-header>
      <el-main>
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { useRoute } from 'vue-router'
const route = useRoute()
</script>

<style scoped>
.layout {
  height: 100vh;
}
.sidebar {
  background: #304156;
  overflow-y: auto;
}
.logo {
  color: #fff;
  font-size: 18px;
  font-weight: bold;
  text-align: center;
  padding: 20px 0;
  border-bottom: 1px solid rgba(255,255,255,0.1);
}
.header {
  background: #fff;
  display: flex;
  align-items: center;
  border-bottom: 1px solid #e4e7ed;
  padding: 0 20px;
}
.title {
  font-size: 16px;
  color: #666;
}
.el-main {
  background: #f5f7fa;
}
</style>
