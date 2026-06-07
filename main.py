import asyncio
import argparse
import sys
import config
from bot import YuketangBot


def parse_args():
    p = argparse.ArgumentParser(description="雨课堂自动看课机器人")
    p.add_argument("--course-url", default=config.COURSE_URL,
                   help="课程 URL，例如 https://www.yuketang.cn/v2/web/course/12345")
    p.add_argument("--api-key", default=config.ANTHROPIC_API_KEY,
                   help="兼容接口 API Key（建议通过环境变量 ANTHROPIC_API_KEY 提供）")
    p.add_argument("--base-url", default=config.ANTHROPIC_BASE_URL,
                   help="兼容接口地址，例如 https://cloud.hongqiye.com")
    p.add_argument("--model", default=config.ANTHROPIC_MODEL,
                   help="模型名，例如 claude-sonnet-4-6")
    p.add_argument("--web-search", dest="web_search", action="store_true",
                   default=config.MODEL_WEB_SEARCH,
                   help="优先启用模型侧联网搜索（默认开启）")
    p.add_argument("--no-web-search", dest="web_search", action="store_false",
                   help="关闭模型侧联网搜索")
    p.add_argument("--speed", type=float, default=config.PLAYBACK_SPEED,
                   help="视频倍速，默认 2.0")
    p.add_argument("--answer-delay", type=int, default=config.ANSWER_DELAY,
                   help="答题前等待秒数（模拟思考），默认 3")
    p.add_argument("--login-timeout", type=int, default=config.LOGIN_TIMEOUT,
                   help="等待微信扫码登录的超时秒数，默认 120")
    p.add_argument("--quiet", action="store_true",
                   help="安静模式：降低倍速和监控频率，不自动选择最高倍速，减少风扇噪音")
    return p.parse_args()


async def run(args):
    if not args.api_key:
        print("错误：未设置兼容接口 API Key。\n"
              "请先轮换泄露过的 key，\n"
              "然后通过环境变量 ANTHROPIC_API_KEY 或 --api-key 传入。")
        sys.exit(1)

    if not args.course_url:
        args.course_url = input("请输入课程 URL：").strip()

    if args.quiet and args.speed == config.PLAYBACK_SPEED:
        args.speed = 1.25

    print("启动配置：")
    print(f"- course_url: {args.course_url or '未提供'}")
    print(f"- base_url: {args.base_url}")
    print(f"- model: {args.model}")
    print(f"- web_search: {args.web_search}")
    print(f"- speed: {args.speed}")
    print(f"- quiet: {args.quiet}")
    print(f"- answer_delay: {args.answer_delay}")
    print(f"- login_timeout: {args.login_timeout}")

    try:
        async with YuketangBot(
            api_key=args.api_key,
            base_url=args.base_url,
            model=args.model,
            web_search=args.web_search,
            speed=args.speed,
            answer_delay=args.answer_delay,
            quiet=args.quiet,
        ) as bot:
            await bot.login(timeout=args.login_timeout)
            await bot.watch_course(args.course_url)
    except KeyboardInterrupt:
        print("\n已手动中断。")
        raise
    except Exception as exc:
        print(f"\n运行失败：{exc}")
        sys.exit(1)

    print("\n全部课程已处理完毕。")


def main():
    args = parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
