"""
诊断脚本：查看 XYZ DEX 的实际内容
运行: python backpack_quant_trading/test_xyz_meta.py
"""
import asyncio
import aiohttp
import json

INFO_URL = "https://api.hyperliquid.xyz/info"

async def post_info(session, data):
    async with session.post(INFO_URL, json=data, headers={'Content-Type': 'application/json'}) as resp:
        text = await resp.text()
        return json.loads(text)

async def main():
    async with aiohttp.ClientSession() as session:
        # 1. 查看所有 perpDexs
        print("=" * 60)
        print("【1】perpDexs 列表:")
        dexs = await post_info(session, {"type": "perpDexs"})
        print(json.dumps(dexs, indent=2, ensure_ascii=False))

        # 2. 查看 Perps meta（主账户）
        print("\n" + "=" * 60)
        print("【2】Perps meta（前5个资产）:")
        perps_meta = await post_info(session, {"type": "meta"})
        universe = perps_meta.get('universe', [])
        print(f"  总共 {len(universe)} 个资产")
        for c in universe[:5]:
            print(f"  - {c['name']}")

        # 3. 用 dex="xyz" 查 meta
        print("\n" + "=" * 60)
        print("【3】meta dex=xyz:")
        xyz_meta = await post_info(session, {"type": "meta", "dex": "xyz"})
        xyz_universe = xyz_meta.get('universe', [])
        print(f"  返回资产数量: {len(xyz_universe)}")
        if xyz_universe:
            print("  资产列表:")
            for c in xyz_universe:
                print(f"    - {c.get('name')} (szDecimals={c.get('szDecimals')})")
        else:
            print("  ⚠️  universe 为空！")
            print("  完整响应:", json.dumps(xyz_meta, indent=2, ensure_ascii=False)[:500])

        # 4. 逐个 dex 试 meta
        if isinstance(dexs, list):
            for dex_item in dexs:
                dex_name = dex_item if isinstance(dex_item, str) else dex_item.get('name', '')
                if not dex_name:
                    continue
                print(f"\n【4】meta dex='{dex_name}':")
                try:
                    meta = await post_info(session, {"type": "meta", "dex": dex_name})
                    u = meta.get('universe', [])
                    print(f"  资产数量: {len(u)}")
                    for c in u:
                        if 'CRCL' in c.get('name', '').upper():
                            print(f"  ✅ 找到 CRCL: {c}")
                except Exception as e:
                    print(f"  错误: {e}")

asyncio.run(main())
