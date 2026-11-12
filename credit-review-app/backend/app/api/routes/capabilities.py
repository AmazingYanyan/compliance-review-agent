from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.core.config import settings
from app.models import Capabilities

router = APIRouter(tags=["capabilities"])

BORROWER_CHECKLIST_VERSION = "borrower-wcl-v1"


@router.get("/capabilities", response_model=Capabilities)
def capabilities(_: CurrentUser) -> Capabilities:
    return Capabilities(
        roles=[
            {
                "code": "borrower",
                "label": "借款人",
                "enabled": True,
                "checklist_version": BORROWER_CHECKLIST_VERSION,
                "disabled_reason": None,
            },
            {
                "code": "guarantor",
                "label": "保证人",
                "enabled": False,
                "checklist_version": None,
                "disabled_reason": "检查清单待配置",
            },
            {
                "code": "pledgor",
                "label": "抵（质）押人",
                "enabled": False,
                "checklist_version": None,
                "disabled_reason": "检查清单待配置",
            },
        ],
        product_code="working_capital_loan",
        checklist_version=BORROWER_CHECKLIST_VERSION,
        ocr_configured=settings.ocr_configured,
        llm_configured=settings.llm_configured,
    )
