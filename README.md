# 工业缺陷检测系统（Industrial Defect Detection System）

一个用于课程设计的 Windows 桌面软件：选择本地图片文件夹、输入缺陷类型文本（中英文均可），
软件调用**本机本地的 PyTorch 模型**完成推理，并把模型输出的、已标注好缺陷位置的图片展示出来。

整套流程都在一台电脑上完成，**不依赖网络、不需要另一台电脑**。

---

## 一、它能做什么

| 功能 | 说明 |
| --- | --- |
| 选择图片文件夹 | 浏览选择或直接把文件夹拖到窗口里，自动扫描 jpg / jpeg / png / bmp / tif / webp 并显示数量 |
| 缺陷类型文本输入 | 中英文均可，例如"裂纹""crack"，文本作为 prompt 直接参与模型推理 |
| 本地模型推理 | 后端进程直接 `import torch` 调用本地模型，分批送入，模型权重常驻内存 |
| 实时进度 | 进度条 + "正在检测 12/80：xxx.jpg"，随时可停止 |
| 结果展示 | 右侧图片墙随检测逐张出现，点击可全屏放大、上下张切换 |
| 环境自检 | 启动时自动检测 torch 是否可用、CUDA 是否可用、模型是否就绪 |
| 参数调节 | 每批图片数、超大图缩放上限、结果 JPEG 质量 |

明确不做：远程/跨机器调用、界面上的模型切换、原图对比、结果导出、历史记录、用户登录。

---

## 二、工作原理

```
┌────────────────────┐   localhost HTTP   ┌──────────────────────┐
│  PySide6 桌面界面   │  ───────────────? │  本机 FastAPI 后端    │
│  （只负责显示交互） │  ?───────────────  │  （扫描/分批/进度/落盘）│
└────────────────────┘   127.0.0.1:8765   └──────────┬───────────┘
                                                     │ 同进程函数调用
                                          ┌──────────▼───────────┐
                                          │  model/inference.py  │
                                          │  （唯一接触 torch）  │
                                          └──────────────────────┘
```

之所以分成"界面 + 后端"两个进程：检测可能持续几分钟，把重活放在后端进程里，
界面只负责每秒问一次进度，因此永远不会卡死。

---

## 三、环境要求

- Windows 10 / 11
- **Python 3.10 及以上**（已在 Python 3.14 上验证通过）
- **当前 Python 环境里必须已经能用 PyTorch**，请先确认：

```bash
python -c "import torch; print(torch.__version__)"
```

能正常打印版本号即可。本项目**不会**为你安装 torch（`requirements.txt` 里没有它），
也就意味着你不需要重装 PyTorch。

---

## 四、三步启动

```bash
# 1. 安装界面与后端依赖（在你平时跑模型的那个环境里执行）
pip install -r requirements.txt

# 2. 安装缺陷定位模型 OEGT-CP（单独安装）
pip install "git+https://github.com/lyylovemwj/OEGT-CP.git"
# 也可以先克隆再本地安装：pip install -e <OEGT-CP 路径>

# 3. 启动
python -m client.main
```

或者双击项目根目录下的 **`start.bat`**。

> 首次启动时会自动拉起后端服务（约几秒），界面右上角状态灯变绿表示模型就绪。
> 启动过程中请勿关闭弹出的命令行窗口（后端进程在其中运行）。

---

## 五、模型已接入 OEGT-CP

本项目已经把缺陷定位模型 **OEGT-CP** 接好了，桥接代码在 `model/inference.py`（唯一接触 torch 的文件）。

它提供两种推理方式，在 `model/inference.py` 顶部配置区切换：

- **方式 A（默认，开箱即用）**：`IIDGPredictor`，14 个检测头 + 启发式融合。
  不需要训练权重，装好依赖就能跑；如果下载了 CLIP / DINOv2 / ResNet 共享权重会自动用深度学习特征，
  没下载则回退到传统图像处理算法（仍能输出缺陷框）。

- **方式 B（论文原始方法）**：`Predictor`（候选集合 Transformer ranker），精度更高，
  需要训练好的 `.pt` 权重。把 `USE_RANKER = True` 并填 `RANKER_CHECKPOINT` 路径即可。

```python
# model/inference.py 顶部配置区
ASSETS_DIR = r"assets/models"   # 共享权重目录（可选）
HEAD = "all"                    # 14 个头之一，或 "all" 融合

USE_RANKER = False              # True 则使用论文 ranker
RANKER_CHECKPOINT = r""         # ranker 的 .pt 权重路径
```

> 可选：下载共享权重以获得更好的效果（在 OEGT-CP 目录下执行）：
> `python -m oegt_cp download-models --heads all`

**不需要改动项目的其它任何文件。**

---

## 六、目录结构

```
├── client/                 桌面界面（PySide6）
│   ├── main.py             启动入口：拉起后端 + 打开主窗口
│   ├── api_client.py       对后端 HTTP 接口的封装
│   ├── workers.py          后台线程（健康检查、轮询进度、加载缩略图）
│   ├── resources/theme.qss 深色工业科技风样式表
│   └── ui/                 主窗口 / 控制面板 / 图片墙 / 大图查看器 / 设置弹窗
├── backend/                本机后端（FastAPI）
│   ├── server.py           服务入口
│   ├── routers/            jobs（任务）· images（结果图）· system（健康检查/配置）
│   ├── services/           scanner（扫描）· inference_runner（模型调用）· detection_service（编排）
│   └── jobs/job_store.py   任务状态表
├── model/
│   └── inference.py        对接 OEGT-CP 的桥接文件（唯一接触 torch）
├── shared/schemas.py       前后端共用的字段定义
├── docs/
│   ├── API_CONTRACT.md     接口契约
│   ├── RUN_GUIDE.md        详细使用与排错手册
│   └── DEPLOY.md           部署到新电脑的步骤
├── config.example.json     配置文件示例（首次运行会自动生成本地 config.json）
├── requirements.txt        依赖清单（不含 torch）
└── start.bat               一键启动
```

---

## 七、常见问题

| 现象 | 原因与处理 |
| --- | --- |
| 界面提示"找不到 torch" | 当前 Python 环境没有 PyTorch，请在你装了 torch 的环境里重新执行安装与启动 |
| 状态灯红色，提示"缺少 OEGT-CP 依赖" | OEGT-CP 没装好，执行 `pip install -e <OEGT-CP 路径>` |
| 提示"找不到 ranker 权重" | 用了方式 B 但 `RANKER_CHECKPOINT` 路径不对，检查 `model/inference.py` |
| 提示显存不足 | 在"参数设置"里把「每批图片数」调小，或开启超大图缩放 |
| 启动时卡住不动 | 端口 8765 被占用，或依赖没装全；可直接看控制台报错 |
| 安装 PySide6 报 403 / 下载中断 | 国内镜像对大文件有限制，请去掉 `-i` 参数使用官方源 |

更多细节见 [`docs/RUN_GUIDE.md`](docs/RUN_GUIDE.md)。

要部署到另一台电脑？见 [`docs/DEPLOY.md`](docs/DEPLOY.md)。

---

## 八、开源说明

本项目为课程设计作品，代码开源仅供学习与交流使用。
模型权重、业务数据等不在本仓库范围内，请自行准备。
