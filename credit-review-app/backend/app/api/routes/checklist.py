from fastapi import APIRouter

from app import checklist
from app.api.deps import CurrentUser

router = APIRouter(tags=["checklist"])


@router.get("/checklist")
def get_checklist(_: CurrentUser) -> dict:
    """返回借款人检查清单（3 类材料、18 叶子），版本 borrower-wcl-v1 冻结。"""
    return checklist.get_checklist()
