<template>
  <div class="home">
    <div class="welcome">
      <h2>欢迎使用审计系统基座</h2>
      <p class="subtitle">一站式审计数据管理平台</p>
    </div>

    <!-- 统计卡片 -->
    <el-row :gutter="20" class="stats-row">
      <el-col :span="8">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-inner">
            <div class="stat-icon companies">
              <el-icon :size="32"><OfficeBuilding /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">{{ companyCount }}</div>
              <div class="stat-label">被审计单位</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-inner">
            <div class="stat-icon vouchers">
              <el-icon :size="32"><Document /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">{{ voucherCount.toLocaleString() }}</div>
              <div class="stat-label">已导入凭证</div>
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-inner">
            <div class="stat-icon ledger">
              <el-icon :size="32"><List /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">{{ ledgerCount.toLocaleString() }}</div>
              <div class="stat-label">辅助核算条目</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 快速入口 -->
    <el-card shadow="never" class="quick-actions">
      <template #header>
        <span class="card-title">快速入口</span>
      </template>
      <el-row :gutter="16">
        <el-col :span="8">
          <div class="action-card" @click="$router.push('/data/import')">
            <el-icon :size="28" color="#409eff"><Upload /></el-icon>
            <div class="action-title">导入数据</div>
            <div class="action-desc">上传 Excel/CSV 文件，一键导入</div>
          </div>
        </el-col>
        <el-col :span="8">
          <div class="action-card" @click="$router.push('/data/companies')">
            <el-icon :size="28" color="#67c23a"><OfficeBuilding /></el-icon>
            <div class="action-title">管理单位</div>
            <div class="action-desc">维护被审计单位信息</div>
          </div>
        </el-col>
        <el-col :span="8">
          <div class="action-card">
            <el-icon :size="28" color="#e6a23c"><DataAnalysis /></el-icon>
            <div class="action-title">数据查询</div>
            <div class="action-desc">科目余额 / 序时账查询（即将上线）</div>
          </div>
        </el-col>
      </el-row>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { OfficeBuilding, Document, List, Upload, DataAnalysis } from '@element-plus/icons-vue'
import api from '@/api'

const companyCount = ref(0)
const voucherCount = ref(0)
const ledgerCount = ref(0)

async function fetchStats() {
  try {
    const { data } = await api.get('/companies', { params: { page: 1, page_size: 1 } })
    companyCount.value = data.total || 0
  } catch {
    companyCount.value = 0
  }

  // TODO: 对接会话 B/D 真实统计 API
  voucherCount.value = 0
  ledgerCount.value = 0
}

onMounted(() => {
  fetchStats()
})
</script>

<style scoped>
.home {
  padding: 0;
}

.welcome {
  margin-bottom: 28px;
}

.welcome h2 {
  font-size: 22px;
  color: #303133;
  margin-bottom: 6px;
}

.subtitle {
  color: #999;
  font-size: 14px;
}

/* 统计卡片 */
.stats-row {
  margin-bottom: 24px;
}

.stat-card {
  cursor: default;
}

.stat-inner {
  display: flex;
  align-items: center;
  gap: 16px;
}

.stat-icon {
  width: 64px;
  height: 64px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
}

.stat-icon.companies {
  background: linear-gradient(135deg, #409eff, #337ecc);
}

.stat-icon.vouchers {
  background: linear-gradient(135deg, #67c23a, #529b2e);
}

.stat-icon.ledger {
  background: linear-gradient(135deg, #e6a23c, #c28b2e);
}

.stat-info {
  flex: 1;
}

.stat-value {
  font-size: 30px;
  font-weight: bold;
  color: #303133;
  line-height: 1.2;
}

.stat-label {
  font-size: 13px;
  color: #999;
  margin-top: 4px;
}

/* 快速入口 */
.quick-actions {
  margin-top: 0;
}

.card-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.action-card {
  text-align: center;
  padding: 24px 16px;
  border-radius: 8px;
  border: 1px solid #ebeef5;
  cursor: pointer;
  transition: all 0.3s;
}

.action-card:hover {
  border-color: #409eff;
  background: #ecf5ff;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(64, 158, 255, 0.15);
}

.action-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
  margin: 10px 0 6px;
}

.action-desc {
  font-size: 12px;
  color: #999;
}
</style>
