import os

# 在 pytest 任何 import 之前设置环境变量
os.environ["MOCK_MODE"] = "true"

# 直接修改 Settings 类属性（因为类属性在 import 时即已绑定 os.getenv）
from app.config import Settings
Settings.MOCK_MODE = True


def pytest_sessionstart(session):
    """确保 MOCK_MODE 已设置。"""
    os.environ["MOCK_MODE"] = "true"
    Settings.MOCK_MODE = True
