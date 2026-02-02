import sys
import os

# 将当前目录添加到 Python 路径，确保能找到 backpack_quant_trading 包
sys.path.append(os.getcwd())

from backpack_quant_trading.database.models import Base, db_manager, User

def init_db():
    print("正在连接数据库并更新表结构...")
    try:
        # 由于 users 表刚创建且 password_hash 长度不足，我们先删除它以便重建
        # 注意：这会删除 users 表中的所有现有数据
        User.__table__.drop(db_manager.engine, checkfirst=True)
        print("已删除旧的 users 表")
        
        # 重新创建所有表
        Base.metadata.create_all(db_manager.engine)
        print("✅ 数据库表初始化/更新成功！")
    except Exception as e:
        print(f"❌ 初始化失败: {e}")

if __name__ == "__main__":
    init_db()
