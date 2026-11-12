from fastapi import APIRouter, Response

router = APIRouter(tags=["health"])


@router.get("/health/live")
def live() -> dict:
    return {"status": "ok"}


@router.get("/health/ready")
def ready(response: Response) -> dict:
    # 只检查进程存活；DB 连通性由调用方探测（P1 简化为进程级）。
    return {"status": "ready"}
