#!/usr/bin/env python3
"""
OpenAkita 内存优化基准测试

测试内容:
1. 启动内存基线
2. 懒加载延迟测试（浏览器、Embedding）
3. 功能回归测试（飞书、微信、语义搜索）
4. 内存泄漏检测

输出：JSON 格式报告
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

# 尝试导入 psutil，如果不存在则使用备用方法
try:
    import psutil

    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    print("⚠️  psutil 未安装，使用备用内存检测方法")

    print("⚠️  psutil 未安装，使用备用内存检测方法")

from openakita.config import settings
from openakita.memory import MemoryManager
from openakita.tools.browser.manager import BrowserManager


class MemoryBenchmark:
    """内存基准测试"""

    def __init__(self):
        self.results = {
            "timestamp": datetime.now().isoformat(),
            "optimization_phase": "phase1",
            "metrics": {},
            "config": {
                "desktop_mode": settings.desktop_mode,
                "search_backend": settings.search_backend,
                "embedding_provider": settings.embedding_api_provider,
                "enabled_channels": self._get_enabled_channels(),
            },
            "tests_passed": {},
        }
        self.process_id = os.getpid()

    def _get_enabled_channels(self) -> list[str]:
        """获取已启用的 IM 通道"""
        channels = []
        if settings.feishu_enabled:
            channels.append("feishu")
        if settings.wechat_enabled:
            channels.append("wechat")
        if settings.telegram_enabled:
            channels.append("telegram")
        if settings.dingtalk_enabled:
            channels.append("dingtalk")
        return channels

    def get_memory_mb(self) -> float:
        """获取当前进程内存占用 (MB)"""
        if HAS_PSUTIL:
            process = psutil.Process(self.process_id)
            return process.memory_info().rss / 1024 / 1024
        else:
            # 备用方法：读取 /proc/self/status (Linux) 或使用 resource 模块
            try:
                import resource

                # resource.getrusage 返回最大 resident set size (KB)
                rusage = resource.getrusage(resource.RUSAGE_SELF)
                return rusage.ru_maxrss / 1024  # macOS 返回的是 KB
            except Exception:
                return 0.0

    async def test_startup_memory(self):
        """测试 1: 启动内存基线"""
        print("\n📊 测试 1: 启动内存基线")

        # 等待 5 秒让系统稳定
        await asyncio.sleep(5)

        startup_memory = self.get_memory_mb()
        print(f"   启动内存：{startup_memory:.1f} MB")

        self.results["metrics"]["startup_memory_mb"] = {
            "value": round(startup_memory, 1),
            "target": "< 600 MB (优化后)",
        }

    async def test_browser_lazy_load(self):
        """测试 2: 浏览器懒加载延迟"""
        print("\n🌐 测试 2: 浏览器懒加载延迟")

        browser_mgr = BrowserManager()

        # 首次启动浏览器（包含懒加载延迟）
        start = time.time()
        success = await browser_mgr.start(visible=False)
        elapsed_ms = (time.time() - start) * 1000

        print(f"   首次启动耗时：{elapsed_ms:.0f} ms")
        print(f"   启动结果：{'✅ 成功' if success else '❌ 失败'}")

        self.results["metrics"]["first_browser_use_latency_ms"] = {
            "value": round(elapsed_ms, 0),
            "includes_playwright_load": True,
            "target": "2000-5000 ms (含懒加载)",
        }

        self.results["tests_passed"]["browser_lazy_load"] = success

        # 清理
        await browser_mgr.stop()

    async def test_semantic_search(self):
        """测试 3: 语义搜索（DashScope API）"""
        print("\n🔍 测试 3: 语义搜索（DashScope API）")

        try:
            # 创建记忆管理器
            memory_mgr = MemoryManager(
                data_dir=settings.data_dir_path,
                memory_md_path=settings.data_dir_path / "MEMORY.md",
                search_backend=settings.search_backend,
                embedding_api_provider=settings.embedding_api_provider,
                embedding_api_key=settings.embedding_api_key,
                embedding_api_model=settings.embedding_api_model,
            )

            # 保存测试记忆
            from openakita.memory.types import SemanticMemory, MemoryType, MemoryPriority

            test_memory = SemanticMemory(
                id="test_benchmark_001",
                type=MemoryType.FACT,
                priority=MemoryPriority.LONG_TERM,
                content="OpenAkita 是一个多智能体 AI 助手，支持飞书和微信集成",
            )
            memory_mgr.store.save_semantic(test_memory)

            # 搜索测试
            start = time.time()
            results = memory_mgr.store.search.search("AI 助手", limit=5)
            elapsed_ms = (time.time() - start) * 1000

            print(f"   搜索耗时：{elapsed_ms:.0f} ms")
            print(f"   找到 {len(results)} 条结果")

            self.results["metrics"]["first_semantic_search_latency_ms"] = {
                "value": round(elapsed_ms, 0),
                "includes_api_call": True,
                "target": "200-500 ms (DashScope API)",
            }

            self.results["tests_passed"]["semantic_search"] = len(results) > 0

            # 清理测试数据
            memory_mgr.store.delete_semantic("test_benchmark_001")

        except Exception as e:
            print(f"   ❌ 测试失败：{e}")
            self.results["tests_passed"]["semantic_search"] = False
            self.results["metrics"]["first_semantic_search_latency_ms"] = {
                "error": str(e),
            }

    async def test_im_channels(self):
        """测试 4: IM 通道可用性"""
        print("\n💬 测试 4: IM 通道可用性")

        from openakita.channels.gateway import MessageGateway
        from openakita.sessions import SessionManager

        gateway = MessageGateway(
            session_manager=SessionManager(),
            agent_handler=lambda s, m: asyncio.ensure_future(asyncio.sleep(0)),
        )

        adapters_tested = 0
        adapters_passed = 0

        # 测试飞书
        if settings.feishu_enabled and settings.feishu_app_id:
            print("   测试飞书通道...")
            try:
                from openakita.channels.adapters.feishu import FeishuAdapter

                adapter = FeishuAdapter(
                    app_id=settings.feishu_app_id,
                    app_secret=settings.feishu_app_secret,
                )
                await gateway.register_adapter(adapter)
                adapters_tested += 1
                adapters_passed += 1
                print("   ✅ 飞书通道注册成功")
            except Exception as e:
                print(f"   ❌ 飞书通道失败：{e}")
                adapters_tested += 1

        # 测试微信
        if settings.wechat_enabled and settings.wechat_token:
            print("   测试微信通道...")
            try:
                from openakita.channels.adapters.wechat import WeChatAdapter

                adapter = WeChatAdapter(token=settings.wechat_token)
                await gateway.register_adapter(adapter)
                adapters_tested += 1
                adapters_passed += 1
                print("   ✅ 微信通道注册成功")
            except Exception as e:
                print(f"   ❌ 微信通道失败：{e}")
                adapters_tested += 1

        self.results["tests_passed"]["im_channels"] = adapters_passed == adapters_tested
        self.results["metrics"]["im_channels_registered"] = {
            "tested": adapters_tested,
            "passed": adapters_passed,
        }

    def generate_report(self, output_path: Path):
        """生成 JSON 报告"""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 计算总评分
        tests_total = len(self.results["tests_passed"])
        tests_passed = sum(1 for v in self.results["tests_passed"].values() if v)
        self.results["summary"] = {
            "tests_passed": f"{tests_passed}/{tests_total}",
            "pass_rate": round(tests_passed / tests_total * 100, 1) if tests_total > 0 else 0,
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)

        print(f"\n📄 报告已保存到：{output_path}")

        # 打印摘要
        print("\n" + "=" * 60)
        print("📊 基准测试摘要")
        print("=" * 60)
        print(
            f"启动内存：{self.results['metrics'].get('startup_memory_mb', {}).get('value', 'N/A')} MB"
        )
        print(
            f"浏览器首次加载：{self.results['metrics'].get('first_browser_use_latency_ms', {}).get('value', 'N/A')} ms"
        )
        print(
            f"语义搜索延迟：{self.results['metrics'].get('first_semantic_search_latency_ms', {}).get('value', 'N/A')} ms"
        )
        print(
            f"IM 通道：{self.results['metrics'].get('im_channels_registered', {}).get('passed', 0)}/{self.results['metrics'].get('im_channels_registered', {}).get('tested', 0)}"
        )
        print(f"测试通过率：{self.results['summary']['pass_rate']}%")
        print("=" * 60)


async def main():
    """主测试函数"""
    print("=" * 60)
    print("🚀 OpenAkita 内存优化基准测试")
    print("=" * 60)

    benchmark = MemoryBenchmark()

    # 运行测试
    await benchmark.test_startup_memory()
    await benchmark.test_browser_lazy_load()
    await benchmark.test_semantic_search()
    await benchmark.test_im_channels()

    # 生成报告
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = (
        Path(__file__).parent / "data" / "benchmarks" / f"memory_benchmark_{timestamp}.json"
    )
    benchmark.generate_report(report_path)


if __name__ == "__main__":
    asyncio.run(main())
