<template>
  <div class="command-center">
    <!-- ===== 顶部 ===== -->
    <PageHeader
      title="工作概览"
      subtitle="查看当前年度的数据导入、单位和待处理事项"
      eyebrow="总览"
    />

    <!-- ===== 4 个紧凑指标 ===== -->
    <div class="metrics-strip">
      <StatsCard
        :icon="OfficeBuilding"
        icon-color="var(--color-primary-500)"
        :value="companyCount"
        label="被审计单位"
        :trend="companyTrend"
      />
      <StatsCard
        :icon="Document"
        icon-color="var(--color-success)"
        :value="voucherCount"
        label="序时账条目"
      />
      <StatsCard
        :icon="List"
        icon-color="#8b7ec8"
        :value="ledgerCount"
        label="辅助核算条目"
      />
      <StatsCard
        :icon="WarningFilled"
        icon-color="var(--color-danger)"
        :value="errorCount"
        label="待处理错误"
      />
    </div>

    <!-- ===== 双栏：最近导入 + 待处理事项 ===== -->
    <div class="dashboard-grid">
      <!-- 左：最近导入 -->
      <section class="panel import-pipeline">
        <div class="panel-head">
          <h3 class="panel-title">最近导入</h3>
          <span class="panel-desc">最近导入批次的处理状态</span>
        </div>

        <div v-if="recentImports.length === 0" class="panel-empty">
          <div class="empty-illustration">
            <el-icon :size="32" color="var(--color-gray-300)"><Upload /></el-icon>
          </div>
          <p class="empty-title">暂无导入记录</p>
          <p class="empty-desc">上传表格文件，开始导入审计数据</p>
          <router-link to="/data/import" class="empty-action">
            <el-icon :size="14"><Plus /></el-icon>
            开始导入
          </router-link>
        </div>

        <div v-else class="pipeline-list">
          <div
            v-for="item in recentImports"
            :key="item.id"
            class="pipeline-item"
          >
            <span class="pipeline-status" :class="item.status">
              <span class="status-dot"></span>
              {{ item.statusLabel }}
            </span>
            <span class="pipeline-file">{{ item.fileName }}</span>
            <span class="pipeline-type">{{ item.type }}</span>
            <span class="pipeline-stats">
              <span class="pipe-stat ok">{{ item.success }}</span>
              <span class="pipe-sep">/</span>
              <span class="pipe-stat" :class="{ fail: item.errors > 0 }">{{ item.total }}</span>
            </span>
            <span class="pipeline-time">{{ item.time }}</span>
          </div>
        </div>
      </section>

      <!-- 右：待处理事项 -->
      <section class="panel risk-queue">
        <div class="panel-head">
          <h3 class="panel-title">待处理事项</h3>
          <span class="panel-desc">需关注的数据质量与校验项</span>
        </div>

        <div v-if="riskItems.length === 0" class="panel-empty panel-empty-ok">
          <div class="empty-illustration">
            <el-icon :size="32" color="var(--color-success)"><SuccessFilled /></el-icon>
          </div>
          <p class="empty-title">暂无待处理事项</p>
          <p class="empty-desc">当前暂无需要处理的数据问题</p>
        </div>

        <div v-else class="risk-list">
          <div
            v-for="item in riskItems"
            :key="item.id"
            class="risk-item"
            :class="item.level"
          >
            <span class="risk-level-dot" :class="item.level"></span>
            <span class="risk-text">{{ item.text }}</span>
            <span class="risk-meta">{{ item.meta }}</span>
          </div>
        </div>
      </section>
    </div>

    <!-- ===== 下一步建议动作 ===== -->
    <section class="suggested-actions">
      <div class="panel-head">
        <h3 class="panel-title">常用操作</h3>
        <span class="panel-desc">选择常用功能</span>
      </div>

      <div class="actions-row">
        <ActionCard
          :icon="Upload"
          icon-color="var(--color-primary-500)"
          title="导入序时账数据"
          description="上传表格文件，自动匹配字段并校验借贷平衡"
          @click="$router.push('/data/import')"
        />
        <ActionCard
          :icon="OfficeBuilding"
          icon-color="var(--color-success)"
          title="新增被审计单位"
          description="在开始导入数据前先登记审计对象信息"
          @click="$router.push('/data/companies')"
        />
        <ActionCard
          :icon="DataAnalysis"
          icon-color="var(--text-placeholder)"
          title="数据查询与分析"
          description="科目余额 / 序时账 / 辅助明细账查询"
          badge="即将上线"
        />
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import {
  OfficeBuilding,
  Document,
  List,
  Upload,
  DataAnalysis,
  WarningFilled,
  SuccessFilled,
  Plus,
} from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import StatsCard from '@/components/StatsCard.vue'
import ActionCard from '@/components/ActionCard.vue'
import api from '@/api'

// ===== 指标 =====
const companyCount = ref(0)
const companyTrend = ref<number | undefined>(undefined)
const voucherCount = ref(0)
const ledgerCount = ref(0)
const errorCount = ref(0)
const statsLoadFailed = ref(false)

// ===== 最近导入（空状态占位） =====
interface ImportPipelineItem {
  id: number
  fileName: string
  type: string
  status: 'success' | 'partial' | 'failed'
  statusLabel: string
  success: number
  errors: number
  total: number
  time: string
}
const recentImports = ref<ImportPipelineItem[]>([])

// ===== 待处理事项（空状态） =====
interface RiskItem {
  id: number
  level: 'high' | 'medium' | 'low'
  text: string
  meta: string
}
const riskItems = ref<RiskItem[]>([])

// ===== 加载统计数据 =====
async function fetchStats() {
  statsLoadFailed.value = false
  try {
    const { data } = await api.get('/companies', { params: { page: 1, page_size: 1 } })
    companyCount.value = data.total || 0
  } catch {
    companyCount.value = 0
    statsLoadFailed.value = true
  }

  // TODO: 对接后端统计 API
  voucherCount.value = 0
  ledgerCount.value = 0
  errorCount.value = 0
}

onMounted(() => {
  fetchStats()
})
</script>

<style scoped>
.command-center {
  max-width: var(--content-max-width);
  margin: 0 auto;
}

/* ===== 指标条 ===== */
.metrics-strip {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--spacing-4);
  margin-bottom: var(--spacing-6);
}

/* ===== 双栏 ===== */
.dashboard-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--spacing-5);
  margin-bottom: var(--spacing-6);
}

/* ===== 面板通用 ===== */
.panel {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.panel-head {
  display: flex;
  align-items: baseline;
  gap: var(--spacing-3);
  padding: var(--spacing-4) var(--spacing-5);
  border-bottom: 1px solid var(--border-lighter);
}

.panel-title {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--text-primary);
  letter-spacing: 0.02em;
  text-transform: uppercase;
}

.panel-desc {
  font-size: var(--font-size-xs);
  color: var(--text-placeholder);
}

/* ===== 空状态 ===== */
.panel-empty {
  padding: var(--spacing-10) var(--spacing-5);
  text-align: center;
}

.panel-empty-ok {
  background: #f9fbf9;
}

.empty-illustration {
  margin-bottom: var(--spacing-3);
}

.empty-title {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--text-secondary);
  margin-bottom: var(--spacing-1);
}

.empty-desc {
  font-size: var(--font-size-xs);
  color: var(--text-placeholder);
  margin-bottom: var(--spacing-4);
}

.empty-action {
  display: inline-flex;
  align-items: center;
  gap: var(--spacing-1);
  font-size: var(--font-size-sm);
  color: var(--color-primary-500);
  text-decoration: none;
  font-weight: var(--font-weight-medium);
  transition: color var(--transition-fast);
}

.empty-action:hover {
  color: var(--color-primary-600);
}

/* ===== 最近导入列表 ===== */
.pipeline-list {
  padding: var(--spacing-1) 0;
}

.pipeline-item {
  display: flex;
  align-items: center;
  gap: var(--spacing-3);
  padding: var(--spacing-3) var(--spacing-5);
  font-size: var(--font-size-sm);
  transition: background var(--transition-fast);
}

.pipeline-item:hover {
  background: var(--color-gray-50);
}

.pipeline-item + .pipeline-item {
  border-top: 1px solid var(--border-lighter);
}

.pipeline-status {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
  width: 72px;
  flex-shrink: 0;
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-medium);
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.pipeline-status.success { color: var(--color-success); }
.pipeline-status.success .status-dot { background: var(--color-success); }
.pipeline-status.partial { color: var(--color-warning); }
.pipeline-status.partial .status-dot { background: var(--color-warning); }
.pipeline-status.failed { color: var(--color-danger); }
.pipeline-status.failed .status-dot { background: var(--color-danger); }

.pipeline-file {
  flex: 1;
  font-weight: var(--font-weight-medium);
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pipeline-type {
  width: 80px;
  flex-shrink: 0;
  font-size: var(--font-size-xs);
  color: var(--text-placeholder);
}

.pipeline-stats {
  width: 60px;
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
  text-align: right;
  font-size: var(--font-size-xs);
}

.pipe-stat.ok { color: var(--color-success); }
.pipe-stat.fail { color: var(--color-danger); }
.pipe-sep { color: var(--text-placeholder); margin: 0 1px; }

.pipeline-time {
  width: 80px;
  flex-shrink: 0;
  font-size: var(--font-size-xs);
  color: var(--text-placeholder);
  text-align: right;
}

/* ===== 待处理事项 ===== */
.risk-list {
  padding: var(--spacing-1) 0;
}

.risk-item {
  display: flex;
  align-items: center;
  gap: var(--spacing-3);
  padding: var(--spacing-3) var(--spacing-5);
  font-size: var(--font-size-sm);
}

.risk-item + .risk-item {
  border-top: 1px solid var(--border-lighter);
}

.risk-level-dot {
  width: 8px;
  height: 8px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
}

.risk-level-dot.high { background: var(--color-danger); }
.risk-level-dot.medium { background: var(--color-warning); }
.risk-level-dot.low { background: var(--color-info); }

.risk-text {
  flex: 1;
  color: var(--text-regular);
}

.risk-meta {
  font-size: var(--font-size-xs);
  color: var(--text-placeholder);
  flex-shrink: 0;
}

/* ===== 建议动作 ===== */
.suggested-actions {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.actions-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--spacing-3);
  padding: var(--spacing-4) var(--spacing-5);
}

/* ===== 响应式 ===== */

@media (max-width: 1366px) {
  .metrics-strip {
    gap: var(--spacing-3);
  }
}

@media (max-width: 1024px) {
  .dashboard-grid {
    grid-template-columns: 1fr;
  }

  .actions-row {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .metrics-strip {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 480px) {
  .metrics-strip {
    grid-template-columns: 1fr;
  }

  .pipeline-item {
    flex-wrap: wrap;
  }
}
</style>
