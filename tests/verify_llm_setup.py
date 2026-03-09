#!/usr/bin/env python3
"""验证 LLM 配置和流程完整性

Usage:
    uv run python tests/verify_llm_setup.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from geo_agent.config import load_config
from geo_agent.llm import create_llm_client, get_default_model


def main():
    print("=" * 70)
    print("LLM 配置验证")
    print("=" * 70)

    # 1. 加载配置
    print("\n[1/5] 加载配置...")
    try:
        config = load_config()
        print(f"  ✓ Provider: {config.llm_provider}")
        print(f"  ✓ Model: {config.llm_annotation_model}")
        print(f"  ✓ Base URL: {config.llm_base_url or '(使用默认)'}")
        print(f"  ✓ API Key: {'已设置' if config.llm_api_key else '未设置'}")
    except Exception as e:
        print(f"  ✗ 配置加载失败: {e}")
        return False

    # 2. 验证 provider
    print("\n[2/5] 验证 provider...")
    try:
        default_model = get_default_model(config.llm_provider)
        print(f"  ✓ Provider '{config.llm_provider}' 支持")
        print(f"  ✓ 默认模型: {default_model}")
    except ValueError as e:
        print(f"  ✗ Provider 不支持: {e}")
        return False

    # 3. 创建客户端
    print("\n[3/5] 创建 LLM 客户端...")
    try:
        client = create_llm_client(config=config)
        print(f"  ✓ 客户端创建成功")
    except Exception as e:
        print(f"  ✗ 客户端创建失败: {e}")
        return False

    # 4. 健康检查
    print("\n[4/5] 健康检查...")
    try:
        if client.health_check():
            print(f"  ✓ API 连接正常")
        else:
            print(f"  ✗ API 连接失败")
            return False
    except Exception as e:
        print(f"  ✗ 健康检查失败: {e}")
        return False

    # 5. 测试调用
    print("\n[5/5] 测试 LLM 调用...")
    try:
        resp = client.messages.create(
            model=config.llm_annotation_model,
            messages=[{"role": "user", "content": "Say 'OK' if you can read this."}],
            temperature=0.0,
            max_tokens=10,
        )
        content = resp.choices[0].message.content
        print(f"  ✓ LLM 响应成功")
        print(f"  ✓ 响应内容: {content[:50]}...")
    except Exception as e:
        print(f"  ✗ LLM 调用失败: {e}")
        return False

    # 6. 检查输出目录
    print("\n[6/6] 检查输出目录...")
    output_dir = Path("tests/05_Test_multiomics_analysis/debug_multiomics_analysis")
    if output_dir.exists():
        print(f"  ✓ 输出目录存在: {output_dir}")

        # 列出现有结果文件
        json_files = list(output_dir.glob("*.json"))
        if json_files:
            print(f"  ✓ 找到 {len(json_files)} 个结果文件:")
            for f in sorted(json_files)[:5]:
                print(f"    - {f.name}")
            if len(json_files) > 5:
                print(f"    ... 还有 {len(json_files) - 5} 个文件")
        else:
            print(f"  ℹ 暂无结果文件")
    else:
        print(f"  ℹ 输出目录不存在（首次运行时会自动创建）")

    # 7. 检查输入文件
    print("\n[7/7] 检查输入文件...")
    input_file = Path("tests/04_Test_family_soft_parse/debug_family_soft_parse/family_soft_structured.json")
    if input_file.exists():
        import json
        data = json.loads(input_file.read_text())
        series_count = data.get("series_count", 0)
        print(f"  ✓ 输入文件存在")
        print(f"  ✓ 包含 {series_count} 个系列")
    else:
        print(f"  ✗ 输入文件不存在: {input_file}")
        print(f"  ℹ 请先运行: uv run python tests/04_Test_family_soft_parse/run_family_soft_parser_debug.py")
        return False

    print("\n" + "=" * 70)
    print("✓ 所有检查通过！配置正确，可以开始使用。")
    print("=" * 70)

    print("\n下一步:")
    print("  1. 测试单个系列:")
    print("     TARGET_SERIES=GSE266455 uv run python tests/05_Test_multiomics_analysis/run_multiomics_analysis_series.py")
    print("\n  2. 批量处理所有系列:")
    print("     uv run python tests/05_Test_multiomics_analysis/run_multiomics_analysis_series.py")

    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
