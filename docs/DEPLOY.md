# 部署到新电脑

本文档说明：如何把「工业缺陷检测系统」部署到一台**新的 Windows 电脑**上并正常使用。

---

## 适用场景

| 场景 | 新电脑上的情况 | 对应章节 |
| --- | --- | --- |
| A（最常见） | 已经有 OEGT-CP 源码 + 训练好的权重，只缺本软件 | 见下方「部署步骤」 |
| B | 什么都没有，从零开始 | 见文末「附录：从零部署」 |

---

## 前置条件

- Windows 10 / 11
- 已安装 Python 3.10 及以上
- **当前环境已能使用 PyTorch**，验证：

```bash
python -c "import torch; print(torch.__version__)"
```

能打印版本号即可。后续所有命令都要在**这个有 torch 的环境**里执行。
（若使用 conda，先 `conda activate <环境名>`）

---

## 部署步骤（场景 A）

### 第 1 步：拷贝软件

把整个「课设软件」项目文件夹复制到新电脑任意位置（U 盘 / 压缩包 / 网盘 / 局域网均可）。

> 提示：文件夹里的 `config.json`、`logs/`、`backend/storage/` 是旧电脑的运行时产物，
> 拷不拷都行，不影响。拷过去后也可以直接删掉，让它们在新电脑上重新生成。

### 第 2 步：安装本软件依赖

```bash
cd <课设软件目录>
pip install -r requirements.txt
```

安装：界面（PySide6-Essentials）、后端（fastapi / uvicorn）、requests、pydantic。
**不会安装或改动 torch**。

> 若 PySide6 下载失败（403 / 断连），去掉镜像参数、使用官方源重试：
> `pip install -r requirements.txt`

### 第 3 步：安装已有的 OEGT-CP

新电脑上已经有 OEGT-CP 源码，但本软件是通过 `import oegt_cp` 调用它，
所以必须把它**安装**到当前环境（可编辑安装，指向你已有的文件夹）：

```bash
pip install -e "<OEGT-CP 文件夹的绝对路径>"
```

例如：

```bash
pip install -e "D:/OEGT-CP"
```

这一步会自动补装 OEGT-CP 的依赖（opencv-python、transformers 等）。

### 第 4 步：配置模型（指向你的训练权重）

打开项目里的 **`model/inference.py`**，修改顶部配置区：

```python
USE_RANKER = True                                  # 启用论文原始 ranker
RANKER_CHECKPOINT = r"D:/你的权重路径/oegt_cp.pt"   # 训练好的 .pt 权重绝对路径
```

- 如果你的 `.pt` 是 OEGT-CP 自己 `oegt-cp train` 训出来的格式 → 用 `USE_RANKER = True`（精度最高）
- 如果你暂时没有可用的训练权重，或想先跑通 → 保持 `USE_RANKER = False`（开箱即用，14 个检测头 + 传统算法）

### 第 5 步：启动

```bash
python -m client.main
```

或双击项目根目录的 `start.bat`。

首次启动会自动拉起后端服务，几秒后弹出主界面，右上角状态灯变绿即可开始检测。

---

## 配置项说明（`model/inference.py`）

| 配置项 | 说明 |
| --- | --- |
| `USE_RANKER` | `True` 用训练好的 ranker 权重；`False` 用开箱即用方式 |
| `RANKER_CHECKPOINT` | 训练权重 `.pt` 的绝对路径（仅 `USE_RANKER=True` 时用到） |
| `ASSETS_DIR` | CLIP / DINOv2 / ResNet 共享权重目录，默认相对路径 `assets/models`；如放在别处需改成绝对路径 |
| `HEAD` | 14 个检测头之一，或 `all` 融合所有头 |
| `DEVICE` | `auto`（有 GPU 用 GPU）/ `cuda` / `cpu` |

---

## 常见问题

| 现象 | 处理 |
| --- | --- |
| 启动后提示"找不到 torch" | 终端进的不是有 torch 的环境，先 `conda activate` 或切换环境 |
| 提示"缺少 OEGT-CP 依赖" | 第 3 步没做，执行 `pip install -e <OEGT-CP路径>` |
| 提示"找不到 ranker 权重" | `RANKER_CHECKPOINT` 路径写错，或该 `.pt` 不是 OEGT-CP 格式；可先改 `USE_RANKER = False` 跑通 |
| 检测很慢 / 显存不足 | 界面「参数设置」里把每批图片数调小 |
| 双击 start.bat 一闪而过 | 命令行手动执行 `python -m client.main` 看报错 |

---

## 附录：从零部署（场景 B）

如果新电脑什么都没有（连 OEGT-CP 都没有）：

```bash
# 1. 拉取本软件
git clone <本软件仓库地址>
cd <仓库名>

# 2. 装本软件依赖
pip install -r requirements.txt

# 3. 从 GitHub 安装 OEGT-CP（或先克隆再本地安装）
pip install "git+https://github.com/lyylovemwj/OEGT-CP.git"

# 4.（可选）下载 OEGT-CP 共享权重以提升精度
python -m oegt_cp download-models --heads all

# 5. 启动
python -m client.main
```
