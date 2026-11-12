"""OCR 客户端：封装 PaddleOCR 托管异步接口。

仅做 HTTP 薄封装：提交 / 查询 / 下载 JSONL / 下载图片。重试、作业恢复与
SUBMISSION_UNKNOWN 的判定由流水线层负责。
"""

import hashlib
import json
from urllib.parse import urlparse

import httpx

from app.core.config import settings


def build_request_config() -> tuple[dict, str]:
    """构建 optionalPayload，返回 (payload, config_hash)。

    方向矫正 / 去畸变先置 False，便于建立原件定位基线；其余沿用已验证调用配置。
    """
    payload: dict = {
        "markdownIgnoreLabels": [],
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useLayoutDetection": True,
        "useChartRecognition": False,
        "useSealRecognition": True,
        "useOcrForImageBlock": True,
        "mergeTables": True,
        "relevelTitles": True,
        "restructurePages": True,
        "temperature": 0,
        "maxPixels": 2822400,
        "minPixels": 147384,
    }
    config_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    return payload, config_hash


class OcrClient:
    def __init__(self) -> None:
        self.base_url = settings.OCR_JOB_URL
        self.model = settings.OCR_MODEL
        self._headers = {"Authorization": f"bearer {settings.OCR_ACCESS_TOKEN}"}
        self._client = httpx.Client(
            timeout=httpx.Timeout(
                connect=settings.OCR_CONNECT_TIMEOUT_SECONDS,
                read=settings.OCR_REQUEST_TIMEOUT_SECONDS,
                write=settings.OCR_REQUEST_TIMEOUT_SECONDS,
                pool=10,
            ),
            follow_redirects=True,
        )

    def submit(self, file_bytes: bytes, filename: str, content_type: str) -> str:
        """提交本地文件，返回 provider_job_id。"""
        _, config = build_request_config()
        resp = self._client.post(
            self.base_url,
            headers=self._headers,
            files={"file": (filename, file_bytes, content_type)},
            data={"model": self.model, "optionalPayload": json.dumps(config)},
        )
        resp.raise_for_status()
        data = resp.json()
        job_id = data.get("data", {}).get("jobId")
        if not job_id:
            raise RuntimeError(f"OCR 提交未返回 jobId: {str(data)[:200]}")
        return str(job_id)

    def get(self, job_id: str) -> dict:
        """查询作业状态，返回 data 字段。"""
        resp = self._client.get(f"{self.base_url}/{job_id}", headers=self._headers)
        resp.raise_for_status()
        return resp.json().get("data", {})

    def download_jsonl(self, url: str) -> bytes:
        """下载 JSONL 结果，限制大小。"""
        resp = self._client.get(url)
        resp.raise_for_status()
        if len(resp.content) > settings.OCR_JSONL_MAX_BYTES:
            raise RuntimeError("JSONL 超过大小上限")
        return resp.content

    def download_image(self, url: str) -> bytes:
        """下载图片，校验主机允许列表与大小。"""
        host = urlparse(url).hostname or ""
        if not any(host == h or host.endswith(h) for h in settings.OCR_IMAGE_HOSTS):
            raise RuntimeError(f"不允许下载的主机: {host}")
        resp = self._client.get(url)
        resp.raise_for_status()
        if len(resp.content) > settings.OCR_IMAGE_MAX_BYTES:
            raise RuntimeError("图片超过大小上限")
        return resp.content

    def close(self) -> None:
        self._client.close()
