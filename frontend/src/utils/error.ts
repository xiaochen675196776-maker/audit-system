/**
 * 将后端错误响应归一化为纯中文消息字符串。
 *
 * 覆盖场景：
 * - detail 是字符串 — 若为已知英文模式则翻译，否则只记 console 并返回中文兜底
 * - detail 是 FastAPI ValidationError 数组 — 翻译每条 msg
 * - detail 是对象 — 翻译 message 字段
 * - error.message 字符串（网络错误等）— 翻译已知模式
 * - 全部为空时使用 fallback
 *
 * 原则：用户可见界面不出现英文原文；调试信息只写 console.error。
 */

interface FastAPIErrorItem {
  msg: string
  type?: string
  loc?: (string | number)[]
  input?: unknown
  ctx?: Record<string, unknown>
}

/** 把已知英文错误短语翻译为中文；无法翻译时返回 null */
function translateMessage(raw: string): string | null {
  const s = raw.trim()

  // 精确匹配 — 网络/超时
  if (s === 'Network Error') return '网络连接失败，请检查后端服务是否启动'
  if (s === 'timeout' || s === 'ECONNABORTED' || s.startsWith('timeout of')) return '请求超时，请稍后重试'

  // FastAPI 常见校验消息
  if (s.startsWith('Input should be less than or equal to ')) return '请求参数超出允许范围'
  if (s.startsWith('Input should be greater than or equal to ')) return '请求参数低于允许范围'
  if (s.startsWith('Input should be less than ')) return '请求参数超出允许范围'
  if (s.startsWith('Input should be greater than ')) return '请求参数低于允许范围'
  if (s.includes('should be a valid') || s.includes('should be a')) return '请求参数格式不正确'
  if (s.startsWith('ensure this value has at least')) return '请求参数长度不足'
  if (s.startsWith('ensure this value has at most')) return '请求参数长度超出限制'
  if (s.startsWith('field required') || s.includes('is required')) return '缺少必填参数'
  if (s.startsWith('value is not a valid')) return '请求参数类型不正确'
  if (s.startsWith('string does not match regex')) return '请求参数格式不符合要求'

  // FastAPI detail 常见消息
  if (s.startsWith('Input should be')) return '请求参数不符合要求'
  if (s === 'Unauthorized') return '未授权，请检查登录状态'
  if (s === 'Forbidden') return '没有权限执行此操作'
  if (s === 'Not Found') return '请求的资源不存在'
  if (s === 'Method Not Allowed') return '请求方法不正确'
  if (s === 'Internal Server Error') return '服务器内部错误，请稍后重试'
  if (s === 'Service Unavailable') return '服务暂不可用，请稍后重试'
  if (s === 'Bad Request') return '请求格式不正确'

  // 默认：无法翻译，返回 null
  return null
}

export function normalizeError(e: unknown, fallback: string): string {
  const err = e as Record<string, any> | undefined

  // 1. FastAPI HTTPException detail 字符串
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim().length > 0) {
    const translated = translateMessage(detail)
    if (translated) return `${fallback}：${translated}`
    // 无法翻译的英文原文只记 console，不展示给用户
    console.error('[normalizeError] detail:', detail)
    return fallback
  }

  // 2. FastAPI RequestValidationError detail 数组
  if (Array.isArray(detail) && detail.length > 0) {
    const translated = detail
      .map((item: FastAPIErrorItem) => translateMessage(item.msg || ''))
      .filter((m): m is string => m !== null)
    if (translated.length > 0) {
      return `${fallback}：${translated.join('；')}`
    }
    // 全是无法翻译的英文
    const rawMsgs = detail.map((item: FastAPIErrorItem) => item.msg || '').filter(Boolean)
    if (rawMsgs.length > 0) {
      console.error('[normalizeError] validation detail:', rawMsgs)
    }
    return fallback
  }

  // 3. detail 是对象
  if (detail && typeof detail === 'object') {
    if (typeof detail.message === 'string' && detail.message.trim().length > 0) {
      const translated = translateMessage(detail.message)
      if (translated) return `${fallback}：${translated}`
      console.error('[normalizeError] detail.message:', detail.message)
      return fallback
    }
    console.error('[normalizeError] detail object:', JSON.stringify(detail))
    return fallback
  }

  // 4. error.message 字符串（网络错误等）
  const msg = err?.message
  if (typeof msg === 'string' && msg.trim().length > 0) {
    const translated = translateMessage(msg)
    if (translated) return `${fallback}：${translated}`
    console.error('[normalizeError] message:', msg)
    return fallback
  }

  // 5. 全部为空
  return fallback || '后端服务不可用，请启动后端服务后重试。'
}
