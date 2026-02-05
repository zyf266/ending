"""
生成 Backpack 交易所使用的 Ed25519 密钥对
运行后会生成公钥和私钥，格式符合 Backpack API 要求
"""
import base64
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

def generate_backpack_keypair():
    """生成 Backpack Ed25519 密钥对"""
    
    # 1. 生成私钥
    private_key = Ed25519PrivateKey.generate()
    
    # 2. 导出私钥（Raw格式，32字节）
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption()
    )
    
    # 3. 从私钥派生公钥
    public_key = private_key.public_key()
    
    # 4. 导出公钥（Raw格式，32字节）
    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw
    )
    
    # 5. 转换为 Base64 编码（Backpack API 要求的格式）
    private_key_b64 = base64.b64encode(private_bytes).decode('utf-8')
    public_key_b64 = base64.b64encode(public_bytes).decode('utf-8')
    
    return public_key_b64, private_key_b64


if __name__ == "__main__":
    print("=" * 80)
    print("🔐 Backpack 交易所 Ed25519 密钥对生成工具")
    print("=" * 80)
    print()
    
    # 生成密钥对
    public_key, private_key = generate_backpack_keypair()
    
    # 输出结果
    print("✅ 密钥生成成功！")
    print()
    print("-" * 80)
    print("📌 公钥（Public Key）- 需要添加到 Backpack 账户的 API 设置中")
    print("-" * 80)
    print(public_key)
    print()
    
    print("-" * 80)
    print("🔒 私钥（Private Key）- 请妥善保管，不要泄露给任何人！")
    print("-" * 80)
    print(private_key)
    print()
    
    print("=" * 80)
    print("📖 使用说明：")
    print("=" * 80)
    print("1. 登录 Backpack 交易所账户")
    print("2. 进入 API 管理页面")
    print("3. 点击「Add API Key」")
    print("4. 将上面的【公钥】粘贴到「Public Key」输入框")
    print("5. 设置权限（交易、查询等）")
    print("6. 保存后，Backpack 会返回一个 API Key（类似 OMLRZspf7Rs+...）")
    print()
    print("⚠️  重要提醒：")
    print("   - 私钥请保存到安全的地方（如密码管理器）")
    print("   - 在代码中使用时，通过环境变量或 Dashboard 输入框传递")
    print("   - 绝对不要将私钥提交到 Git 或分享给他人")
    print("=" * 80)
    print()
    
    # 保存到文件（可选）
    save = input("是否保存到文件？(y/n): ").strip().lower()
    if save == 'y':
        with open('backpack_keys.txt', 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write("Backpack 交易所密钥对\n")
            f.write("生成时间: " + __import__('datetime').datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n")
            f.write("=" * 80 + "\n\n")
            f.write("公钥（Public Key）:\n")
            f.write(public_key + "\n\n")
            f.write("私钥（Private Key）:\n")
            f.write(private_key + "\n\n")
            f.write("⚠️ 警告：此文件包含敏感信息，请勿分享或提交到版本控制！\n")
        
        print(f"✅ 密钥已保存到: backpack_keys.txt")
        print("⚠️  请立即将该文件移到安全位置或删除！")
    else:
        print("✅ 未保存到文件，请手动复制保存")
