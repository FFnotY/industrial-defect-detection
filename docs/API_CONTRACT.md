# 接口契约

本项目有两层接口：

1. **桌面前端 ? 本机后端**：HTTP（`127.0.0.1:8765`）+ JSON
2. **后端 ? 你的模型**：Python 函数调用（同进程，不走网络）

两层接口的定义都写在这里，改动前请先更新本文档。

---

## 一、后端 ? 模型（核心契约）

唯一实现文件：`model/inference.py`。这是"两个输入、一个输出"的落点。

```python
def load_model() -> Any:
    """加载并返回模型对象。
    要求：幂等（重复调用不重复读盘）；失败时抛出带中文说明的异常。
    """

def run_inference(image_paths: list[str], prompt: str) -> list[Any]:
    """两个输入：
        image_paths —— 本机图片的绝对路径列表
        prompt      —— 缺陷类型文本（中英文均可）

    一个输出：
        已画好缺陷框的结果图列表，顺序与 image_paths 一一对应
    """
```

**输入细节**

| 项 | 说明 |
| --- | --- |
| `image_paths` | 绝对路径；文件是后端的临时副本，可安全读取，任务结束后会被清理 |
| `prompt` | UTF-8 字符串，可能为空字符串 |

**返回值支持三种形式**（`backend/services/inference_runner.py` 负责统一转成 JPEG 字节）

| 形式 | 示例 |
| --- | --- |
| `bytes`（推荐） | `cv2.imencode(".jpg", img)[1].tobytes()` |
| `numpy.ndarray` | BGR/RGB 数组，由后端自动编码 |
| `PIL.Image.Image` | PIL 图像对象，由后端自动编码 |

**异常语义**（后端会翻译成中文显示在界面上）

| 异常 | 界面提示 |
| --- | --- |
| `NotImplementedError` | 模型尚未接入 / 请填写 inference.py |
| `FileNotFoundError` | 找不到模型文件：xxx |
| `ModuleNotFoundError` | 缺少 Python 依赖：xxx |
| 含 `out of memory` | 显存不足 / 请调小每批图片数 |
| 其它 | 模型推理失败：<原始异常文本> |

---

## 二、前端 ? 后端 HTTP 接口

基础地址：`http://127.0.0.1:8765`，统一前缀 `/api`。
所有错误响应体为 `{"detail": "中文错误说明"}`。

### `GET /api/health` — 健康检查

```json
{
  "backend": true,
  "torch_available": true,
  "torch_version": "2.14.0+cu126",
  "cuda_available": true,
  "model_status": "not_loaded",
  "model_message": null
}
```

`model_status`：`not_loaded` / `loading` / `ready` / `error`

### `GET /api/scan?folder=<路径>` — 预览文件夹

```json
{ "folder": "D:/imgs", "total": 80, "files": ["a.jpg", "b.jpg"] }
```

错误：`404` 文件夹不存在；`400` 路径不是文件夹

### `POST /api/jobs` — 创建检测任务

请求：

```json
{ "folder": "D:/imgs", "prompt": "裂纹" }
```

响应：

```json
{ "job_id": "a1b2c3d4e5f6" }
```

任务创建后立即在后端异步执行，前端随后轮询状态。

### `GET /api/jobs/{job_id}` — 查询进度与结果

```json
{
  "job_id": "a1b2c3d4e5f6",
  "status": "running",
  "total": 80,
  "processed": 12,
  "succeeded": 12,
  "failed": 0,
  "current_file": "bolt_013.jpg",
  "message": "正在检测第 2/10 批",
  "elapsed_ms": 4321,
  "results": ["bolt_001.jpg", "bolt_002.jpg"],
  "failures": [{ "filename": "bad.jpg", "error": "图片无法解码：..." }]
}
```

| 字段 | 说明 |
| --- | --- |
| `status` | `pending` / `running` / `done` / `failed` / `canceled` |
| `results` | 已完成的结果图**文件名**列表（增量返回，前端只增不减） |
| `failures` | 失败明细，单张失败不影响其它图片 |
| `elapsed_ms` | 已耗时（毫秒） |

### `POST /api/jobs/{job_id}/cancel` — 取消任务

```json
{ "canceled": true }
```

在批次之间生效，已完成的结果仍然保留。

### `GET /api/jobs/{job_id}/images/{name}` — 读取结果图

返回 JPEG 二进制，前端按需惰性拉取（只加载进入可视区域的缩略图）。
路径穿越访问会被拒绝（`400`）。

### `GET /api/config` / `PUT /api/config` — 参数读写

```json
{ "batch_size": 8, "max_side": 0, "jpeg_quality": 90, "host": "127.0.0.1", "port": 8765 }
```

`PUT` 只接受 `batch_size`（1~64）、`max_side`（0 或 256~8192）、`jpeg_quality`（50~100）。
修改后对**后续**任务生效，当前任务不受影响。

---

## 三、约定与限制

- 结果图一律以 JPEG 保存在 `backend/storage/results/<job_id>/`
- 推理在后端内单工作线程串行执行，避免 GPU 并发导致显存溢出
- 任务记录保存在内存中，超过 30 分钟结束后会被清理，最多保留 50 条历史
- 本项目不保存历史到磁盘、不做结果导出，关闭软件后结果图仍留在上述目录中
