<template>
  <div class="shell">
    <!-- ===== 左侧：双层导航 ===== -->
    <div class="nav-rail">
      <!-- 56px 全局图标轨道 -->
      <nav class="track" aria-label="全局导航">
        <div class="track-logo">
          <el-icon :size="22"><Monitor /></el-icon>
        </div>

        <div class="track-items">
          <button
            v-for="item in trackItems"
            :key="item.key"
            class="track-btn"
            :class="{ active: activeTrack === item.key }"
            :aria-label="item.label"
            :aria-current="activeTrack === item.key ? 'page' : undefined"
            @click="switchTrack(item.key)"
          >
            <el-icon :size="20"><component :is="item.icon" /></el-icon>
            <span class="track-label">{{ item.shortLabel }}</span>
          </button>
        </div>

        <div class="track-bottom">
          <button class="track-btn" aria-label="设置">
            <el-icon :size="20"><Setting /></el-icon>
            <span class="track-label">设置</span>
          </button>
        </div>
      </nav>

      <!-- 168px 工作区面板 -->
      <aside
        class="panel"
        :class="{ collapsed: !panelVisible }"
        aria-label="工作区导航"
      >
        <div class="panel-header">
          <span class="panel-title">{{ activePanelTitle }}</span>
        </div>

        <nav class="panel-nav">
          <router-link
            v-for="link in activePanelLinks"
            :key="link.path"
            :to="link.path"
            class="panel-link"
            :class="{ exact: link.exact && route.path === link.path }"
          >
            <span class="panel-link-icon">
              <el-icon :size="16"><component :is="link.icon" /></el-icon>
            </span>
            <span class="panel-link-text">{{ link.label }}</span>
            <span v-if="link.badge" class="panel-link-badge">{{ link.badge }}</span>
          </router-link>
        </nav>

        <div class="panel-footer">
          <span class="panel-version">审计系统</span>
        </div>
      </aside>
    </div>

    <!-- ===== 主区域 ===== -->
    <div class="main-area">
      <!-- 顶部 搜索栏 -->
      <header class="top-bar">
        <div class="bar-left">
          <button
            class="panel-toggle"
            :aria-label="panelVisible ? '收起面板' : '展开面板'"
            @click="panelVisible = !panelVisible"
          >
            <el-icon :size="18"><Fold /></el-icon>
          </button>
          <div class="bar-breadcrumb">
            <span class="bar-page-title">{{ pageTitle || '工作概览' }}</span>
            <span v-if="pageSubtitle" class="bar-page-subtitle">{{ pageSubtitle }}</span>
          </div>
        </div>

        <div class="bar-center">
          <div class="command-bar" @click="focusCommand">
            <el-icon :size="16" class="command-icon"><Search /></el-icon>
            <input
              ref="commandInput"
              v-model="commandQuery"
              class="command-input"
              type="text"
              placeholder="搜索单位或功能…"
              @keydown.enter="handleCommand"
            />
          <!-- 快捷键提示已隐藏 -->
          </div>
        </div>

        <div class="bar-right">
          <span class="bar-period" v-if="currentPeriod">
            <span class="bar-period-dot"></span>
            {{ currentPeriod }}
          </span>
          <span class="bar-time">{{ currentTime }}</span>
        </div>
      </header>

      <!-- 主内容区 -->
      <main class="content-area">
        <router-view v-slot="{ Component }">
          <transition name="page-fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  HomeFilled,
  Upload,
  OfficeBuilding,
  Monitor,
  Search,
  Fold,
  Setting,
  TrendCharts,
  DataAnalysis,
  Collection,
} from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()

// ===== 轨道 =====
const activeTrack = ref<'home' | 'data'>('home')
const panelVisible = ref(true)
const isNarrowScreen = ref(false)

// 监听屏幕宽度：≤768px 时自动收起面板
function checkScreenWidth() {
  isNarrowScreen.value = window.innerWidth <= 768
  if (isNarrowScreen.value) {
    panelVisible.value = false
  }
}

interface TrackItem {
  key: 'home' | 'data'
  label: string
  shortLabel: string
  icon: any
}

const trackItems: TrackItem[] = [
  { key: 'home', label: '首页', shortLabel: '首页', icon: HomeFilled },
  { key: 'data', label: '数据管理', shortLabel: '数据', icon: TrendCharts },
]

function switchTrack(key: 'home' | 'data') {
  activeTrack.value = key
  // 窄屏下不自动展开面板
  if (!isNarrowScreen.value && !panelVisible.value) {
    panelVisible.value = true
  }
  if (key === 'home') router.push('/')
}

// 根据当前路由自动同步轨道
watch(
  () => route.path,
  (path) => {
    if (path.startsWith('/data/') || path === '/data') {
      activeTrack.value = 'data'
    } else {
      activeTrack.value = 'home'
    }
  },
  { immediate: true }
)

// ===== 面板 =====
interface PanelLink {
  path: string
  label: string
  icon: any
  exact?: boolean
  badge?: string
}

const activePanelTitle = computed(() => {
  return trackItems.find((t) => t.key === activeTrack.value)?.label || ''
})

const activePanelLinks = computed<PanelLink[]>(() => {
  if (activeTrack.value === 'home') {
    return [
      { path: '/', label: '总览', icon: HomeFilled, exact: true },
    ]
  }
  return [
    { path: '/data/import', label: '数据导入', icon: Upload, exact: true },
    { path: '/data/companies', label: '被审计单位', icon: OfficeBuilding, exact: true },
    { path: '/data/standard-accounts', label: '标准科目', icon: Collection, exact: true },
    { path: '/data/view', label: '数据查看', icon: DataAnalysis, exact: true },
  ]
})

// ===== 页面信息（从路由 meta 或映射） =====
const pageTitleMap: Record<string, string> = {
  '/': '工作概览',
  '/data/import': '数据导入',
  '/data/companies': '被审计单位管理',
  '/data/standard-accounts': '标准科目表查看',
  '/data/view': '数据查看',
}
const pageSubtitleMap: Record<string, string> = {
  '/': '查看当前年度的数据导入、单位和待处理事项',
  '/data/import': '上传文件 · 映射字段 · 校验入库',
  '/data/companies': '管理审计对象信息',
  '/data/standard-accounts': '系统内置标准科目 · 只读查看',
  '/data/view': '科目余额表 · 序时账 · 辅助明细账',
}

const pageTitle = computed(() => pageTitleMap[route.path] || '')
const pageSubtitle = computed(() => pageSubtitleMap[route.path] || '')

// ===== 搜索栏 =====
const commandQuery = ref('')
const commandInput = ref<HTMLInputElement>()

function focusCommand() {
  nextTick(() => commandInput.value?.focus())
}

function handleCommand() {
  const q = commandQuery.value.trim().toLowerCase()
  if (!q) return
  // 简单命令路由
  if (q.includes('导入') || q.includes('import')) {
    router.push('/data/import')
  } else if (q.includes('单位') || q.includes('公司') || q.includes('company')) {
    router.push('/data/companies')
  } else if (q.includes('查看') || q.includes('数据') || q.includes('模板')) {
    router.push('/data/view')
  } else if (q.includes('首页') || q.includes('总览') || q.includes('home')) {
    router.push('/')
  }
  commandQuery.value = ''
}

// 键盘快捷键
function onKeydown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
    e.preventDefault()
    focusCommand()
  }
}

// ===== 时间 =====
const currentTime = ref('')
let timer: ReturnType<typeof setInterval> | null = null

function updateTime() {
  const now = new Date()
  currentTime.value = now.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// ===== 当前期间（预留） =====
const currentPeriod = ref('2025 年度')

onMounted(() => {
  checkScreenWidth()
  updateTime()
  timer = setInterval(updateTime, 30000)
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('resize', checkScreenWidth)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('resize', checkScreenWidth)
})
</script>

<style scoped>
/* ============================================================
   Shell 布局
   ============================================================ */

.shell {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

/* ===== 导航轨道 (56px 暗色图标轨) ===== */
.nav-rail {
  display: flex;
  flex-shrink: 0;
}

.track {
  width: var(--track-width);
  background: var(--color-track-bg);
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 0 0 var(--spacing-3);
  border-right: 1px solid var(--color-track-border);
  user-select: none;
  z-index: 2;
}

.track-logo {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-track-icon-active);
  margin-top: var(--spacing-3);
  margin-bottom: var(--spacing-4);
}

.track-items {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  width: 100%;
  padding: 0 var(--spacing-1);
}

.track-btn {
  width: 44px;
  height: 44px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  border: none;
  background: transparent;
  color: var(--color-track-icon);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--transition-fast);
  position: relative;
}

.track-btn:hover {
  background: var(--color-track-bg-hover);
  color: var(--color-track-icon-active);
}

.track-btn.active {
  color: var(--color-track-icon-active);
  background: var(--color-track-bg-active);
}

/* 左边线激活指示 */
.track-btn.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 2px;
  height: 20px;
  background: var(--color-track-accent);
  border-radius: 0 2px 2px 0;
}

.track-label {
  font-size: 9px;
  line-height: 1;
  font-weight: var(--font-weight-medium);
  letter-spacing: 0.02em;
}

.track-bottom {
  margin-top: auto;
}

/* ===== 工作区面板 (170px 浅色面板) ===== */
.panel {
  width: var(--panel-width);
  background: var(--color-panel-bg);
  border-right: 1px solid var(--color-panel-border);
  display: flex;
  flex-direction: column;
  transition: width var(--transition-slow), opacity var(--transition-base);
  overflow: hidden;
}

.panel.collapsed {
  width: 0;
  opacity: 0;
}

.panel-header {
  padding: var(--spacing-4) var(--spacing-4) var(--spacing-3);
  height: 52px;
  display: flex;
  align-items: center;
}

.panel-title {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--text-regular);
  letter-spacing: 0.02em;
  text-transform: uppercase;
}

.panel-nav {
  flex: 1;
  padding: 0 var(--spacing-2);
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.panel-link {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  padding: 7px var(--spacing-3);
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
  text-decoration: none;
  transition: all var(--transition-fast);
  position: relative;
}

.panel-link:hover {
  background: rgba(0, 0, 0, 0.04);
  color: var(--text-primary);
}

.panel-link.exact,
.router-link-exact-active.panel-link {
  background: rgba(59, 110, 165, 0.08);
  color: var(--color-primary-600);
  font-weight: var(--font-weight-medium);
}

/* 面板激活项左边线 */
.panel-link.router-link-active:not(.router-link-exact-active) {
  /* 父路由匹配但非精确匹配，不特殊处理 */
}

.panel-link-icon {
  display: flex;
  align-items: center;
  flex-shrink: 0;
  opacity: 0.7;
}

.panel-link.exact .panel-link-icon,
.router-link-exact-active .panel-link-icon {
  opacity: 1;
}

.panel-link-text {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.panel-link-badge {
  margin-left: auto;
  font-size: var(--font-size-xs);
  background: var(--color-primary-500);
  color: #fff;
  padding: 0 5px;
  border-radius: var(--radius-full);
  line-height: 16px;
  min-width: 18px;
  text-align: center;
}

.panel-footer {
  padding: var(--spacing-3) var(--spacing-4);
  border-top: 1px solid var(--color-panel-border);
}

.panel-version {
  font-size: var(--font-size-xs);
  color: var(--text-placeholder);
}

/* ===== 主区域 ===== */
.main-area {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* ===== 顶部 搜索栏 (56px) ===== */
.top-bar {
  height: var(--header-height);
  background: var(--bg-header);
  display: flex;
  align-items: center;
  gap: var(--spacing-4);
  padding: 0 var(--spacing-5);
  border-bottom: 1px solid var(--border-light);
  flex-shrink: 0;
}

.bar-left {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  min-width: 0;
}

.panel-toggle {
  width: 30px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
  flex-shrink: 0;
}

.panel-toggle:hover {
  background: var(--color-gray-100);
  color: var(--text-primary);
}

.bar-breadcrumb {
  display: flex;
  align-items: baseline;
  gap: var(--spacing-2);
  min-width: 0;
}

.bar-page-title {
  font-size: var(--font-size-md);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
  white-space: nowrap;
}

.bar-page-subtitle {
  font-size: var(--font-size-sm);
  color: var(--text-placeholder);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ===== 搜索栏 搜索框 ===== */
.bar-center {
  flex: 1;
  display: flex;
  justify-content: center;
  max-width: 480px;
}

.command-bar {
  width: 100%;
  height: 34px;
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  padding: 0 var(--spacing-3);
  background: var(--color-gray-50);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  cursor: text;
  transition: all var(--transition-fast);
}

.command-bar:hover {
  border-color: var(--color-gray-300);
}

.command-bar:focus-within {
  border-color: var(--color-primary-400);
  box-shadow: 0 0 0 2px rgba(59, 110, 165, 0.12);
  background: var(--bg-card);
}

.command-icon {
  color: var(--text-placeholder);
  flex-shrink: 0;
}

.command-input {
  flex: 1;
  border: none;
  background: transparent;
  font-size: var(--font-size-sm);
  color: var(--text-primary);
  outline: none;
  font-family: var(--font-family-base);
}

.command-input::placeholder {
  color: var(--text-placeholder);
}

.command-kbd {
  font-size: 10px;
  padding: 1px 5px;
  border: 1px solid var(--border-light);
  border-radius: 3px;
  color: var(--text-placeholder);
  font-family: var(--font-family-mono);
  flex-shrink: 0;
}

/* ===== 右侧 ===== */
.bar-right {
  display: flex;
  align-items: center;
  gap: var(--spacing-4);
  flex-shrink: 0;
}

.bar-period {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
  white-space: nowrap;
}

.bar-period-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-success);
  flex-shrink: 0;
}

.bar-time {
  font-size: var(--font-size-sm);
  color: var(--text-placeholder);
  font-variant-numeric: tabular-nums;
}

/* ===== 主内容区 ===== */
.content-area {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: var(--spacing-6);
  background: var(--bg-page);
}

/* ===== 页面过渡 ===== */
.page-fade-enter-active,
.page-fade-leave-active {
  transition: opacity var(--transition-base), transform var(--transition-base);
}

.page-fade-enter-from {
  opacity: 0;
  transform: translateY(6px);
}

.page-fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

/* ===== 响应式 ===== */

/* 1366px 及以下 */
@media (max-width: 1366px) {
  .bar-center {
    max-width: 320px;
  }

  .content-area {
    padding: var(--spacing-5);
  }
}

/* 1024px 平板 */
@media (max-width: 1024px) {
  .panel {
    width: 0;
    opacity: 0;
    position: absolute;
    left: var(--track-width);
    top: 0;
    bottom: 0;
    z-index: var(--z-sticky);
    box-shadow: var(--shadow-lg);
  }

  .panel:not(.collapsed) {
    width: var(--panel-width);
    opacity: 1;
  }

  .bar-page-subtitle {
    display: none;
  }

  .bar-center {
    max-width: 240px;
  }
}

/* 768px */
@media (max-width: 768px) {
  .bar-center {
    max-width: 180px;
  }

  .bar-period {
    display: none;
  }

  .content-area {
    padding: var(--spacing-4);
  }

  .command-kbd {
    display: none;
  }
}

/* 480px */
@media (max-width: 480px) {
  .track {
    width: 48px;
  }

  .bar-center {
    display: none;
  }

  .bar-page-subtitle {
    display: none;
  }

  .content-area {
    padding: var(--spacing-3);
  }
}
</style>
