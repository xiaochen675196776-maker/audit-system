"""健康检查 API"""

from fastapi import APIRouter

router = APIRouter(tags=["健康检查"])


@router.get("/health")
async def health_check():
    """服务健康检查"""
    return {"status": "ok", "message": "审计系统基座运行中"}
