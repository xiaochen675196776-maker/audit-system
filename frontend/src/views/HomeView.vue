<template>
  <div class="home">
    <h2>欢迎使用审计系统基座</h2>
    <el-row :gutter="20" class="stats">
      <el-col :span="8">
        <el-card shadow="hover">
          <el-statistic title="被审计单位" :value="0" />
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover">
          <el-statistic title="已导入凭证" :value="0" />
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover">
          <el-statistic title="辅助核算条目" :value="0" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.home h2 {
  margin-bottom: 24px;
}
</style>
