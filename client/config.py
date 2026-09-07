"""桌面前端的运行参数（一般不需要改）。"""

from pathlib import Path

# 本机后端地址（后端与界面在同一台机器上，走回环地址即可）
BACKEND_URL = "http://127.0.0.1:8765"

# 任务进度轮询间隔（毫秒）
POLL_INTERVAL_MS = 800

# 图片墙缩略图尺寸
THUMB_WIDTH = 220
THUMB_HEIGHT = 160

# 单个 HTTP 请求超时（秒）
HTTP_TIMEOUT = 10

# 拉取超时设置（联网请求一律较短，避免界面长时间等待）
FETCH_IMAGE_TIMEOUT = 20

RESOURCES_DIR = Path(__file__).resolve().parent / "resources"
THEME_PATH = RESOURCES_DIR / "theme.qss"
