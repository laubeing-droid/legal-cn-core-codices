"""
法律法规库多源核验系统 - 入口脚本
===================================
支持断点续跑、进度输出、终态汇总。
"""

import argparse
import logging
import sys
from pathlib import Path

# 添加当前目录到路径
sys.path.insert(0, str(Path(__file__).parent))

import config
from scheduler import VerificationScheduler


def setup_logging(verbose: bool = False):
    """配置日志。"""
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(message)s"

    # 控制台输出
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(logging.Formatter(fmt))

    # 文件输出
    file_handler = logging.FileHandler(config.LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(fmt))

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(console)
    root.addHandler(file_handler)


def main():
    parser = argparse.ArgumentParser(
        description="法律法规库多源核验系统"
    )
    parser.add_argument(
        "--phase",
        nargs="*",
        choices=["local_cross", "yuandian", "url_check", "local_gov", "wechat_case"],
        help="指定要执行的阶段（默认全部）",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="从已有检查点恢复",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="限制处理数量（0=不限）",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="详细输出",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("法律法规库多源核验系统启动")
    logger.info("=" * 60)

    # 检查必要依赖
    try:
        import requests
        logger.info("requests 模块已加载")
    except ImportError as e:
        logger.error(f"缺少必要依赖: {e}")
        logger.error("请安装 requests: pip install requests")
        sys.exit(1)

    # 创建调度器
    scheduler = VerificationScheduler()

    # 如果有限制，截取记录
    if args.limit > 0:
        scheduler.load_input()
        scheduler.records = scheduler.records[:args.limit]
        scheduler.stats.total = len(scheduler.records)
        logger.info(f"限制处理数量: {args.limit}")

    # 执行
    try:
        scheduler.run(phases=args.phase)
    except KeyboardInterrupt:
        logger.info("用户中断，保存检查点...")
        from checkpoint import save_checkpoint
        save_checkpoint(scheduler.checkpoint)
        logger.info("检查点已保存")
    except Exception as e:
        logger.error(f"执行异常: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
