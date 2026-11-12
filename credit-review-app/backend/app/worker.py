"""后台 Worker 入口：运行 Procrastinate worker。

与 API 共享同一代码、同一数据库、同一挂载目录。默认单实例、3 个轻量异步步骤。
"""

# 先导入任务模块以注册任务（注意：`import app.ocr_pipeline` 会把 `app` 绑定到包，
# 因此必须在之后再 `from app.queue import app` 以取得 App 实例）
import app.ocr_pipeline  # noqa: F401
import app.processing_pipeline  # noqa: F401
from app.queue import app


def main() -> None:
    # Procrastinate 3.10 的 run_worker 是同步方法（内部自建 event loop），
    # 不能再用 asyncio.run 包裹。
    app.run_worker(concurrency=3)


if __name__ == "__main__":
    main()
