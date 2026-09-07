"""前后端共用的数据模型与常量。

这个文件是整个项目唯一的字段定义来源，桌面前端与本机后端都从这里导入，
用来保证双方对同一个字段的理解完全一致（新增字段只需要改这里）。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

API_PREFIX = "/api"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

SUPPORTED_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")


# ---------------------------------------------------------------------------
# 运行状态
# ---------------------------------------------------------------------------


class JobStatus(str, Enum):
    """检测任务的生命周期状态。"""

    PENDING = "pending"      # 已创建，尚未开始
    RUNNING = "running"      # 正在推理
    DONE = "done"            # 全部处理完毕（允许存在个别失败）
    FAILED = "failed"        # 任务级失败（如模型加载失败、文件夹不存在）
    CANCELED = "canceled"    # 用户主动取消


class ModelStatus(str, Enum):
    """本地 PyTorch 模型的加载状态。"""

    NOT_LOADED = "not_loaded"   # 尚未加载
    LOADING = "loading"         # 正在加载权重
    READY = "ready"             # 就绪，可用
    ERROR = "error"             # 加载失败，model_message 中给出原因


# ---------------------------------------------------------------------------
# 请求 / 响应模型
# ---------------------------------------------------------------------------


class CreateJobRequest(BaseModel):
    """创建检测任务：一个文件夹 + 一段缺陷类型文本（中英文均可）。"""

    folder: str
    prompt: str = ""


class CreateJobResponse(BaseModel):
    job_id: str


class FailureItem(BaseModel):
    """单张图片的失败信息。"""

    filename: str
    error: str


class JobInfo(BaseModel):
    """任务的完整状态，前端每秒轮询一次该结构来刷新界面。"""

    job_id: str
    status: JobStatus = JobStatus.PENDING
    total: int = 0                      # 扫描到的图片总数
    processed: int = 0                  # 已处理数量（成功 + 失败）
    succeeded: int = 0
    failed: int = 0
    current_file: str | None = None     # 当前正在处理的文件名
    message: str | None = None          # 面向用户的中文提示
    elapsed_ms: int = 0                 # 已耗时
    results: list[str] = Field(default_factory=list)    # 结果图文件名列表
    failures: list[FailureItem] = Field(default_factory=list)


class HealthInfo(BaseModel):
    """健康检查：环境自检 + 模型加载状态。启动后前端第一时间展示它。"""

    backend: bool = True
    torch_available: bool = False
    torch_version: str | None = None
    cuda_available: bool = False
    model_status: ModelStatus = ModelStatus.NOT_LOADED
    model_message: str | None = None


class AppConfig(BaseModel):
    """可调参数（与模型无关，仅影响性能与输出质量）。"""

    batch_size: int = 8         # 每批送入模型的图片数
    max_side: int = 0           # 超大图长边缩放上限，0 表示不缩放
    jpeg_quality: int = 90      # 结果图 JPEG 编码质量
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT


class ImageListResponse(BaseModel):
    """某个文件夹下扫描到的图片（前端用于显示"共 N 张"）。"""

    folder: str
    total: int
    files: list[str] = Field(default_factory=list)
