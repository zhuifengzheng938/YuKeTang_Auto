# 雨课堂自动看课助手

这是一个基于 **Python + Playwright + Anthropic 兼容 API** 的雨课堂自动化脚本。

它可以帮助你：

- 自动打开雨课堂课程目录页
- 自动展开课程目录
- 从目录靠前的未完成视频开始播放
- 按课程目录顺序继续下一节
- 播放完成后自动返回目录页
- 自动跳过已完成 / 100% / 已读的视频
- 遇到弹窗题目时调用大模型辅助作答并提交
- 题目答错后记录错误答案，并自动换一个答案继续重试
- 持续维持指定倍速，防止播放器自动回到 1 倍速
- 优先按你传入的目标倍速点击播放器 UI（例如 `--speed 2.0` 会优先点 `2x/2.00`）
- 输出实际媒体倍速状态，方便判断播放器是否真的吃到倍速
- 停滞或误判完成时输出主视频状态，方便继续适配
- 支持安静模式，降低风扇噪音

> 请合理使用。本项目仅供学习和个人辅助使用，请遵守学校、课程平台和任课老师的相关要求。

---

## 1. 项目文件说明

```text
yuketang_bot/
├── main.py      # 程序入口，解析命令行参数
├── bot.py       # 浏览器自动化、播放视频、切换课程、处理题目
├── solver.py    # 调用大模型解题
├── config.py    # 默认配置
└── README.md    # 使用说明
```

---

## 2. 环境要求

需要安装：

- Python 3.9 或以上
- Microsoft Edge 浏览器
- Python 依赖包：
  - `playwright`
  - `anthropic`

安装依赖：

```bash
pip install playwright anthropic
```

本项目默认使用本机 **Microsoft Edge**，一般不需要额外下载 Chromium。

---

## 3. 第一次使用：配置 API Key

脚本遇到题目时会调用 **Anthropic 兼容接口**，所以需要设置 API Key。

### PowerShell

```powershell
$env:ANTHROPIC_API_KEY="你的API_KEY"
$env:ANTHROPIC_BASE_URL="https://cloud.hongqiye.com"
$env:ANTHROPIC_MODEL="claude-sonnet-4-6"
$env:MODEL_WEB_SEARCH="0"
```

### Git Bash / Claude Code 终端

```bash
export ANTHROPIC_API_KEY="你的API_KEY"
export ANTHROPIC_BASE_URL="https://cloud.hongqiye.com"
export ANTHROPIC_MODEL="claude-sonnet-4-6"
export MODEL_WEB_SEARCH="0"
```

注意：

- 不要把自己的 API Key 发给别人
- 不要把 API Key 写进公开仓库
- 如果 Key 泄露了，请及时去服务商后台更换

---

## 4. 推荐使用课程目录页 URL

推荐传入 **课程目录页 URL**，不要传单个视频页 URL。

课程目录页一般长这样：

```text
https://www.yuketang.cn/v2/web/studentLog/课程ID?university_id=...&platform_id=...&classroom_id=...
```

示例：

```text
https://www.yuketang.cn/v2/web/studentLog/28932779?university_id=2930&platform_id=3&classroom_id=28932779
```

原因：雨课堂真正的课程顺序和完成状态在目录页里。脚本的主流程是：

```text
课程目录页 → 展开目录 → 找靠前的未完成视频 → 打开视频 → 播放/答题 → 返回目录页 → 下一节
```

---

## 5. 直接复制运行

下面命令二选一，看你项目放在哪个位置。

### 方式 A：运行 C 盘原项目

#### 普通模式

```powershell
python "C:\Users\25286\yuketang_bot\main.py" --course-url "https://www.yuketang.cn/v2/web/studentLog/28932779?university_id=2930&platform_id=3&classroom_id=28932779"
```

#### 指定 2 倍速

```powershell
python "C:\Users\25286\yuketang_bot\main.py" --course-url "https://www.yuketang.cn/v2/web/studentLog/28932779?university_id=2930&platform_id=3&classroom_id=28932779" --speed 2.0
```

#### 安静模式，推荐风扇声音大时使用

```powershell
python "C:\Users\25286\yuketang_bot\main.py" --course-url "https://www.yuketang.cn/v2/web/studentLog/28932779?university_id=2930&platform_id=3&classroom_id=28932779" --quiet
```

#### 安静模式 + 1 倍速

```powershell
python "C:\Users\25286\yuketang_bot\main.py" --course-url "https://www.yuketang.cn/v2/web/studentLog/28932779?university_id=2930&platform_id=3&classroom_id=28932779" --quiet --speed 1.0
```

---

### 方式 B：运行 D 盘副本

如果项目已经复制到了：

```text
D:\freshman\try\yuketang_bot
```

#### 普通模式

```powershell
python "D:\freshman\try\yuketang_bot\main.py" --course-url "https://www.yuketang.cn/v2/web/studentLog/28932779?university_id=2930&platform_id=3&classroom_id=28932779"
```

#### 指定 2 倍速

```powershell
python "D:\freshman\try\yuketang_bot\main.py" --course-url "https://www.yuketang.cn/v2/web/studentLog/28932779?university_id=2930&platform_id=3&classroom_id=28932779" --speed 2.0
```

#### 安静模式

```powershell
python "D:\freshman\try\yuketang_bot\main.py" --course-url "https://www.yuketang.cn/v2/web/studentLog/28932779?university_id=2930&platform_id=3&classroom_id=28932779" --quiet
```

#### 安静模式 + 1 倍速

```powershell
python "D:\freshman\try\yuketang_bot\main.py" --course-url "https://www.yuketang.cn/v2/web/studentLog/28932779?university_id=2930&platform_id=3&classroom_id=28932779" --quiet --speed 1.0
```

---

## 6. 如果你在 Claude Code 里运行

Claude Code 里建议在命令前加 `!`。

C 盘原项目：

```bash
! python "C:/Users/25286/yuketang_bot/main.py" --course-url "https://www.yuketang.cn/v2/web/studentLog/28932779?university_id=2930&platform_id=3&classroom_id=28932779" --quiet
```

D 盘副本：

```bash
! python "D:/freshman/try/yuketang_bot/main.py" --course-url "https://www.yuketang.cn/v2/web/studentLog/28932779?university_id=2930&platform_id=3&classroom_id=28932779" --quiet
```

---

## 7. 运行后会发生什么

1. 程序打开 Edge 浏览器
2. 用微信扫码登录雨课堂
3. 脚本进入课程目录页
4. 自动展开课程目录
5. 从目录顶部开始，寻找靠前的未完成视频
6. 如果视频已完成，会快速跳过
7. 如果视频未完成，会打开并播放
8. 播放中会持续维持指定倍速
9. 遇到弹窗题目时调用模型作答
10. 如果题目答错，会记录已错答案并自动尝试别的答案
11. 播放完成后返回目录页，继续下一节

---

## 8. 安静模式说明

如果电脑风扇声音很大，推荐加：

```bash
--quiet
```

安静模式会：

- 不自动选择页面最高倍速
- 默认使用 `1.25x` 倍速
- 降低视频监控频率
- 减少 CPU/GPU 压力和风扇噪音

如果想更安静：

```bash
--quiet --speed 1.0
```

如果想稍微快一点：

```bash
--quiet --speed 1.5
```

注意：如果加了 `--quiet`，脚本会故意降低播放压力，所以不要用它来测试最高倍速。

---

## 9. 倍速说明

普通模式下，脚本会：

- 优先在页面倍速菜单里选择你指定的目标倍速（例如 `--speed 2.0` 会优先点 `2x/2.00`）
- 如果页面菜单里找不到精确项，会自动尝试点击最接近目标值的倍速项
- 设置 `video/audio.playbackRate`
- 同时设置 `defaultPlaybackRate`
- 递归查找 iframe 和 shadow DOM 里的媒体元素
- 在页面内持续锁定目标倍速，防止播放器自动回到 1 倍速
- 播放监控期间持续重设倍速，防止播放器或页面脚本再次重置

终端里现在可能看到几类倍速/播放日志：

```text
已切换到页面倍速 2x
页面倍速菜单命中项：2.00
已确认媒体倍速：目标 2.0x，当前 2, 2，defaultPlaybackRate 2, 2
```

这说明：

- 页面播放器 UI 已经切到了目标倍速
- 媒体元素当前也确实跑在目标倍速

如果看到：

```text
页面倍速菜单未找到精确 2x，改点最接近项：1.00X
```

说明页面菜单里的倍速文本或结构和预期不完全一致，脚本已退而求其次去点最接近的可见项，后续还可以继续适配选择器。

如果看到：

```text
页面倍速菜单已点击，但媒体当前仍为 1，defaultPlaybackRate 1，播放器可能已重置倍速
```

说明页面控件虽然点到了，但播放器没有真正保持目标倍速，脚本会继续尝试用媒体属性和页面内锁速把它拉回目标值。

---

## 10. 大模型答题说明

`solver.py` 现在仍是**模型优先**的通用解题链路，不靠本地写死题库。

处理流程：

```text
优先按当前模型 + 联网搜索请求作答
    ↓ 如果网关/模型不支持搜索参数
自动回退到同模型的普通作答
    ↓ 如果返回空
Streaming 流式请求再试一次
    ↓ 如果格式不对
换更严格 prompt 再问
    ↓ 如果页面判定答错
记录这次错误答案，下次提示模型不要重复
    ↓ 如果连续多次仍失败
强制关闭/跳过，避免死循环
```

也就是说：

- 默认模型是 `claude-sonnet-4-6`
- 联网搜索默认关闭，但可以用 `--web-search` 打开
- 如果当前 `base_url` 不支持搜索参数，会自动回退成普通作答，不会直接退出
- 单选、多选、判断、填空都继续走同一套解析逻辑
- 如果页面提示答错，会把这次错误答案加入黑名单，下一次不再重复
- 不会再因为解析不到就默认选 A

如果终端出现：

```text
模型侧联网搜索不受支持，已自动回退为普通作答
```

说明当前兼容网关不支持搜索参数，但脚本已经自动降级，后续题目仍会继续作答。

如果终端出现：

```text
模型返回空内容，原始响应摘要: ...
```

说明问题多半在 API 代理、模型名、余额、Key、接口兼容或流式支持上，而不是题目识别本身。

如果终端出现：

```text
已记录错误答案，稍后重试: B
```

说明页面已经明确判定本次答案不对，脚本会在下一轮要求模型换一个答案，而不是继续死循环提交同一个选项。

---

## 11. 常用参数

```bash
python main.py [参数]
```

| 参数 | 说明 | 示例 |
|---|---|---|
| `--course-url` | 课程目录页 URL | `--course-url "https://..."` |
| `--api-key` | API Key，也可以用环境变量 | `--api-key "sk-xxx"` |
| `--base-url` | Anthropic 兼容接口地址 | `--base-url "https://cloud.hongqiye.com"` |
| `--model` | 模型名称，默认 `claude-sonnet-4-6` | `--model "claude-sonnet-4-6"` |
| `--web-search` | 开启模型侧联网搜索 | `--web-search` |
| `--no-web-search` | 关闭模型侧联网搜索（默认） | `--no-web-search` |
| `--speed` | 播放倍速 | `--speed 1.5` |
| `--answer-delay` | 答题前等待秒数 | `--answer-delay 3` |
| `--login-timeout` | 等待扫码登录秒数 | `--login-timeout 120` |
| `--quiet` | 安静模式 | `--quiet` |

---

## 12. 常见问题

### 1）为什么推荐课程目录页，而不是单个视频页？

因为雨课堂真正的课程顺序和完成状态在目录页里。目录页驱动比单视频页里找“下一节”更稳定。

---

### 2）程序停在扫码登录页面怎么办？

先确认你已经用微信扫码登录。

如果终端显示：

```text
在等待时间内未检测到明确的登录成功信号，继续尝试访问课程页…
```

不用太担心，脚本会继续尝试访问课程页。

---

### 3）一进去就跳过视频怎么办？

如果页面或目录里显示：

- `已完成`
- `100%`
- `已读`
- `学习完成`

脚本会认为这个视频已经完成，并立刻跳到下一个未完成视频。

---

### 4）还是从后面的课开始怎么办？

脚本现在会先回到目录顶部，再逐屏向下找第一个未完成视频。如果还是从后面开始，可能是雨课堂页面用了虚拟列表或目录结构变化，需要提供目录截图继续适配。

---

### 5）题目答不了怎么办？

看终端输出，重点看：

```text
题型:
选项:
答案:
调用解题器失败:
模型返回空内容，原始响应摘要:
已记录错误答案，稍后重试:
```

如果是“模型返回空内容”，优先检查：

- API Key 是否有效
- `ANTHROPIC_BASE_URL` 是否正确
- 模型名是否被代理支持
- 代理是否支持 Anthropic Messages API
- 代理是否支持 streaming 流式响应
- 账号余额是否正常

如果反复出现“已记录错误答案”，说明题面识别是通的，但模型给出的答案没过页面校验，此时应重点看题目提取、选项提取或该题是否存在特殊交互。

---

### 6）视频看起来还是 1 倍速怎么办？

先确认没有加 `--quiet`。

普通模式下终端应该能看到类似：

```text
已切换到页面倍速 2x
页面倍速菜单命中项：2.00
已确认媒体倍速：目标 2.0x，当前 2, 2，defaultPlaybackRate 2, 2
```

如果页面 UI 仍然显示 1 倍速，或者日志里出现：

```text
页面倍速菜单已点击，但媒体当前仍为 1，defaultPlaybackRate 1，播放器可能已重置倍速
```

说明雨课堂播放器自己的状态机把倍速改回去了，脚本会继续用媒体属性和页面内锁速尝试拉回目标值。

---

### 7）一直提示“检测到播放停滞，尝试恢复”怎么办？

现在脚本会在停滞和完成时打印主视频状态，类似：

```text
检测到播放停滞，尝试恢复 | source=video[0] paused=True current=12.3 duration=600.0 readyState=4 ended=False
```

重点看：

- `paused=True`：大概率是页面暂停了，需要继续找播放按钮或遮罩层
- `duration` 很小或不合理：可能抓到的不是主视频，而是预加载/隐藏元素
- `ended=True` 但目录仍显示未完成：大概率是页面进度同步逻辑和实际视频元素不一致

如果你贴出这类日志，就可以继续针对性适配。

使用安静模式：

```bash
python main.py --course-url "课程目录页URL" --quiet
```

或者降低倍速：

```bash
python main.py --course-url "课程目录页URL" --quiet --speed 1.0
```

---

## 13. 使用建议

- 优先使用课程目录页 URL
- 第一次运行时盯着浏览器看一会儿，确认它按顺序播放
- 如果页面结构变了，脚本可能需要调整选择器
- 不要把 API Key 发给别人
- 如果电脑太吵，使用 `--quiet`
- 如果题目经常空响应，优先排查 API 代理，而不是改题目逻辑
- 如果题目反复答错，先看终端里有没有“已记录错误答案”日志，它能帮助定位是模型问题还是页面交互问题
- 如果视频反复停滞，优先贴出带 `source/paused/current/duration/readyState/ended` 的状态日志

---

## 14. 免责声明

本项目仅供学习交流和个人辅助使用。使用者应自行确认使用行为符合课程平台、学校和任课老师的要求。因使用本脚本造成的任何后果，由使用者自行承担。
