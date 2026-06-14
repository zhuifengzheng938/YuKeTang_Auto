# 雨课堂自动看课助手

基于 **Python + Playwright + AI 大模型** 的雨课堂自动化脚本，支持视频自动播放、弹窗题目作答、习题页作答。

## 功能特性

- 自动打开课程目录，按顺序播放未完成视频
- 维持指定倍速，防止播放器自动降速
- 视频中弹窗题目 AI 自动作答，答错自动重试
- **习题/测验页面自动作答** — OCR 识别题目 + AI 联网搜索解题
- 主模型不可用时自动回退到备用模型
- 联网搜索不支持时自动降级为普通作答
- 支持安静模式降低 CPU 占用

> 请合理使用。本项目仅供学习交流和个人辅助使用。

## 项目结构

```
yuketang_bot/
├── main.py        # 程序入口，命令行参数解析
├── bot.py         # 编排层，串联各模块
├── browser.py     # Playwright 浏览器会话管理
├── catalog.py     # 课程目录导航、展开、课时选择
├── video.py       # 视频播放、监控、完成检测
├── questions.py   # 弹窗题目处理（检测→提取→解题→提交）
├── exercises.py   # 习题/测验页面处理（OCR识别→AI解题→翻页）
├── solver.py      # AI 大模型解题器，支持联网搜索和图片输入
├── ocr.py         # EasyOCR 本地识别（绕过字体反爬）
├── selectors.py   # CSS 选择器统一管理
├── utils.py       # 文本清理、URL 工具函数
├── config.py      # 默认配置
└── README.md
```

## 快速开始

### 环境要求

- Python 3.9+
- Microsoft Edge 浏览器
- 兼容 Anthropic Messages API 的 AI 接口

### 安装

```bash
pip install playwright anthropic easyocr pillow numpy torch
```

### 配置

推荐使用本地配置文件（不会被上传到 Git）：

```bash
# 创建 config_local.py（已在 .gitignore 中，不会被提交）
cat > config_local.py << 'EOF'
ANTHROPIC_API_KEY = "your-api-key"
ANTHROPIC_BASE_URL = "https://your-api-proxy.com"
ANTHROPIC_MODEL = "claude-opus-4-6"
ANTHROPIC_FALLBACK_MODEL = "claude-sonnet-4-6"
MODEL_WEB_SEARCH = "1"
EOF
```

> `config_local.py` 已在 `.gitignore` 中，不会被推送到 GitHub。把 `your-api-key` 和 `your-api-proxy.com` 换成你自己的即可。

或者通过环境变量配置（适合 CI/自动化场景）：

```bash
export ANTHROPIC_API_KEY="your-api-key"
export ANTHROPIC_BASE_URL="https://your-api-proxy.com"
export ANTHROPIC_MODEL="claude-opus-4-6"
export ANTHROPIC_FALLBACK_MODEL="claude-sonnet-4-6"
export MODEL_WEB_SEARCH="1"
```

环境变量优先级高于 `config_local.py`。所有配置项也可通过命令行参数传入。

### 运行

```bash
python main.py \
  --course-url "https://www.yuketang.cn/v2/web/studentLog/..." \
  --speed 2.0 \
  --web-search
```

推荐使用课程目录页 URL（`studentLog` 页面），脚本会自动展开目录并按顺序播放。

## 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--course-url` | 课程目录页 URL | - |
| `--api-key` | API Key | 环境变量 |
| `--base-url` | API 接口地址 | 环境变量 |
| `--model` | 主模型名称 | `gpt-5.5` |
| `--fallback-model` | 备用模型 | `claude-opus-4-6` |
| `--web-search` | 开启联网搜索 | 开启 |
| `--no-web-search` | 关闭联网搜索 | - |
| `--speed` | 播放倍速 | `2.0` |
| `--answer-delay` | 答题前等待秒数 | `3` |
| `--login-timeout` | 扫码登录超时秒数 | `120` |
| `--quiet` | 安静模式 | 关闭 |
| `--solve-exercises` | 启用习题页自动作答 | 开启 |
| `--no-solve-exercises` | 关闭习题页作答 | - |

## 答题机制

### 弹窗题目（视频播放中弹出）

```
检测弹窗 → 提取题干/题型/选项 → AI 解题 → 点击答案 → 提交
→ 答错自动记录错误答案 → 换答案重试（最多 3 次）
```

### 习题页题目（独立习题/测验页面）

```
检测习题页 → 截图题目块 → EasyOCR 本地识别文字
→ AI 联网搜索解题 → 点击选项 → 提交 → 自动翻页
```

雨课堂对页面文字做了**自定义字体混淆**（DOM 中是乱码，渲染后才是真文字），本项目通过 EasyOCR 对页面截图做本地 OCR 识别来绕过。

## 题型支持

- 单选题 — 选择正确选项字母
- 多选题 — 选择所有正确选项
- 判断题 — 判断对错（✓/✗ 图标选项）
- 填空题 — 填写答案文本

## 提示词策略

1. **普通提示词** — 礼貌请求，给出选项
2. **严格 JSON** — 要求模型输出 `{"answer":"..."}`
3. **超严格** — 限制输出字符集

如果之前答错，提示词会包含"以下答案已试过且错误"，引导模型换答案。

## 降级策略

所有降级均静默处理，不中断运行：

| 场景 | 降级行为 |
|------|----------|
| API 不支持联网搜索 | 自动关闭搜索，改为普通作答 |
| API 不支持图片输入 | 自动关闭图片，改为纯文本 |
| 主模型调用失败 | 自动切换到备用模型 |
| OCR 识别失败 | 回退到 DOM 文字 |
| 题目块无法识别 | 遍历可点击元素兜底查找 |

## 常见问题

### 程序停在扫码页面？

确认已用微信扫码登录。脚本会继续尝试访问课程页。

### 视频直接跳过？

页面显示"已完成""100%"等标记时会自动跳过。

### 题目答错？

- 检查 API Key 和 base_url 是否有效
- 尝试开启 `--web-search` 联网搜索
- 尝试更换 `--model` 模型

### 视频看起来还是 1 倍速？

确认未使用 `--quiet` 模式，终端应显示倍速切换日志。

## 免责声明

本项目仅供学习交流和个人辅助使用。使用者应自行确认使用行为符合课程平台、学校和任课老师的要求。因使用本脚本造成的任何后果，由使用者自行承担。
