import os

# 必须在导入 app.* 之前：让模块级 engine 指向 sqlite，测试再用依赖覆盖注入独立内存库。
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SEED_ON_EMPTY", "false")
