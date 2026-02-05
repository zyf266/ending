"""创建 user_instances 表（不删除任何现有数据）"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from backpack_quant_trading.database.models import Base, db_manager, UserInstance

if __name__ == "__main__":
    print("创建 user_instances 表...")
    try:
        UserInstance.__table__.create(db_manager.engine, checkfirst=True)
        print("✅ user_instances 表就绪")
    except Exception as e:
        print(f"❌ 失败: {e}")
