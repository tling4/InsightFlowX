"""DAGents-InsightFlow backend application package.

在包初始化时设置 Windows 事件循环策略，确保 uvicorn 导入链中最早执行。
"""

import asyncio
import platform

if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
