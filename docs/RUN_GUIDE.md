# 使用与接入手册

面向两类读者：**使用者**（跑起来做检测）与**模型负责人**（把自己的模型接进来）。

---

## 第一部分：跑起来

### 1. 准备环境

要求：Windows + Python ≥ 3.10，且**当前环境已能使用 PyTorch**。

先验证：

```bash
python -c "import torch; print(torch.__version__)"
```

- 能打印版本号 → 继续
- 报错 `No module named 'torch'` → 说明你进错了环境（常见于装了多个 Python）。
  请先切换到你平时跑模型的那个环境（conda 用 `conda activate <环境名>`，venv 用对应的 activate 脚本）

### 2. 安装依赖

```bash
cd <项目根目录>
pip install -r requirements.txt
```

会安装：PySide6-Essentials（界面）、fastapi / uvicorn（后端）、requests、pydantic。
**不会安装 torch**，也不会动你现有的 PyTorch/CUDA。

> 如果 PySide6 下载失败（403 / 下载中断），多半是镜像源的问题，请去掉 `-i` 镜像参数，直接用官方源：
> `pip install -r requirements.txt`
>
> 若仍失败，可单独装界面库观察具体报错：`pip install PySide6-Essentials`

### 3. 安装检测模型 OEGT-CP

```bash
# 直接从 GitHub 安装
pip install "git+https://github.com/lyylovemwj/OEGT-CP.git"

# 或者先克隆到本地再安装（克隆遇到 SSL 报错时加 -c http.sslVerify=false）
git clone https://github.com/lyylovemwj/OEGT-CP.git
pip install -e ./OEGT-CP
```

这一步会自动装上 OEGT-CP 依赖的 opencv-python、transformers 等包。
**模型桥接已经写好了**，正常情况下无需再改代码，直接看本手册第二部分了解如何切换推理方式即可。

### 4. 启动

```bash
python -m client.main
```

或双击 `start.bat`。

启动流程：
1. 检查后端是否已在运行
2. 没有则后台拉起后端（控制台窗口会打印日志）
3. 等健康检查通过 → 打开主界面
4. 关闭界面时自动关掉它自己拉起的后端

### 5. 做一次检测

1. 点击「浏览」选择待检测图片文件夹（也可以直接把文件夹拖进窗口）
2. 在「缺陷类型」里填写要检测的缺陷，例如 `裂纹` 或 `crack`
3. 点击「开始检测」（快捷键 `Ctrl + Enter`）
4. 右侧图片墙会随结果逐张出现，点击任意一张可全屏查看（`Esc` 关闭，左右方向键切换）
5. 中途可随时点「停止」

---

## 第二部分：模型配置（OEGT-CP）

模型桥接代码已写在 `model/inference.py`（唯一接触 torch 的文件），软件与 OEGT-CP
之间的契约如下：

```python
load_model()                                    # 加载模型，只调用一次
run_inference(image_paths: list[str], prompt: str) -> list[bytes]
#   输入：本机图片绝对路径列表 + 缺陷类型文本（中英文均可）
#   输出：已画好缺陷框的结果图列表，顺序与输入一一对应
```

### 两种推理方式

| 方式 | 说明 | 是否需要权重 | 切换方法 |
| --- | --- | --- | --- |
| A（默认） | `IIDGPredictor`：14 个检测头 + 启发式融合 | 否，开箱即用 | 默认就是它 |
| B | `Predictor`：论文候选集合 Transformer ranker | 是，需 `.pt` 权重 | `USE_RANKER = True` |

### 配置区（`model/inference.py` 顶部）

```python
ASSETS_DIR = r"assets/models"   # 共享权重目录（方式 A 可选）
HEAD = "all"                    # 14 个头之一，或 "all" 融合

USE_RANKER = False              # 改为 True 使用方式 B
RANKER_CHECKPOINT = r""         # 方式 B 的 .pt 权重路径
DEVICE = "auto"                 # auto / cuda / cpu
```

### 可选：下载共享权重（提升方式 A 效果）

在 OEGT-CP 目录下执行，会下载 CLIP / DINOv2 / ResNet 三个共享模型到 `assets/models`：

```bash
python -m oegt_cp download-models --heads all
```

> 不下载也能跑（自动回退到传统图像处理算法），只是深度学习头的精度更高。
> 注意：`model/inference.py` 里的 `ASSETS_DIR` 要指向这个 `assets/models` 目录
> （相对路径相对的是软件项目根目录，建议改成绝对路径）。

### 命令行自检（不打开界面）

```bash
# 终端 1：单独启动后端，可直接看到 Python 报错
python -m backend.server

# 终端 2：健康检查
curl http://127.0.0.1:8765/api/health
```

`model_status` 字段含义：

| 值 | 含义 |
| --- | --- |
| `not_loaded` | 还没开始加载（正常，首次任务时才会加载） |
| `loading` | 正在加载权重 |
| `ready` | 就绪，可以检测 |
| `error` | 加载失败，`model_message` 里是原因 |

---

## 第三部分：参数说明

在界面「参数设置」里修改，也可编辑项目根目录的 `config.json`（首次运行自动生成）：

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `batch_size` | 8 | 每批送入模型的图片数。显存紧张就调小（1~64） |
| `max_side` | 0 | 图片长边超过该值时先缩放再送入模型；0 表示不缩放（需装 Pillow 或 opencv 才生效） |
| `jpeg_quality` | 90 | 结果图 JPEG 编码质量（50~100） |
| `port` | 8765 | 后端端口，被占用时可改 |

---

## 第四部分：排错表

| 现象 | 排查 |
| --- | --- |
| 界面提示"当前环境中找不到 torch" | 换到装了 PyTorch 的环境再启动 |
| 每张图都失败，提示"模型尚未接入" | `model/inference.py` 的 TODO 没实现 |
| 提示"找不到模型文件：xxx" | `MODEL_WEIGHTS` 路径错误，注意路径分隔符 |
| 提示显存不足 | 调小 `batch_size` 或设置 `max_side` |
| 提示"缺少 Python 依赖：xxx" | 在后端所在环境 `pip install xxx` |
| 扫描到 0 张图片 | 确认文件夹里确实是 jpg/png/bmp/tif/webp，且路径没选错 |
| 双击 start.bat 一闪而过 | 命令行里手动执行 `python -m client.main` 看报错 |
| 后端起不来（端口占用） | 改 `config.json` 里的 `port`，或结束占用 8765 的进程 |
| 图片全黑 / 颜色异常 | 通常是 RGB 与 BGR 顺序问题，检查你画框那一步的输入通道顺序 |

日志文件：`logs/backend.log`
结果图片：`backend/storage/results/<任务ID>/`
