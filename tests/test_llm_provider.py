#!/usr/bin/env python3
"""Test LLM provider connectivity and basic functionality.

Usage:
    # Test with .env configuration
    uv run python tests/test_llm_provider.py

    # Test specific provider
    LLM_PROVIDER=deepseek LLM_API_KEY=sk-xxx uv run python tests/test_llm_provider.py

    # Test all providers (requires API keys in .env)
    uv run python tests/test_llm_provider.py --all
"""

import argparse
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from geo_agent.config import load_config
from geo_agent.llm import create_llm_client, get_default_model


def test_provider(provider: str, api_key: str | None = None, base_url: str | None = None) -> bool:
    """Test a single provider."""
    print(f"\n{'='*60}")
    print(f"Testing provider: {provider}")
    print(f"{'='*60}")

    try:
        # Get default model
        default_model = get_default_model(provider)
        print(f"✓ Default model: {default_model}")

        # Create client
        client = create_llm_client(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
        )
        print(f"✓ Client created")

        # Health check
        if client.health_check():
            print(f"✓ Health check passed")
        else:
            print(f"✗ Health check failed")
            return False

        # List models (may not be supported by all providers)
        models = client.list_models()
        if models:
            print(f"✓ Available models: {len(models)}")
            for model in models[:5]:  # Show first 5
                print(f"  - {model}")
            if len(models) > 5:
                print(f"  ... and {len(models) - 5} more")
        else:
            print(f"ℹ Model listing not supported or no models found")

        # Test simple completion
        print(f"\nTesting completion...")
        resp = client.messages.create(
            model=default_model,
            messages=[{"role": "user", "content": "Say 'Hello' in JSON format: {\"message\": \"...\"}"}],
            temperature=0.0,
            max_tokens=100,
        )
        content = resp.choices[0].message.content
        print(f"✓ Completion successful")
        print(f"  Response: {content[:100]}...")

        print(f"\n✓ All tests passed for {provider}")
        return True

    except Exception as exc:
        print(f"\n✗ Test failed for {provider}: {exc}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Test LLM provider connectivity")
    parser.add_argument("--all", action="store_true", help="Test all providers (requires API keys)")
    parser.add_argument("--provider", help="Test specific provider")
    args = parser.parse_args()

    # Load config
    config = load_config()

    if args.all:
        # Test all providers
        providers = ["ollama", "deepseek", "qwen", "kimi", "minimax"]
        results = {}
        for provider in providers:
            # Skip if no API key for non-ollama providers
            if provider != "ollama" and not config.llm_api_key:
                print(f"\nSkipping {provider} (no API key in .env)")
                continue
            results[provider] = test_provider(provider, config.llm_api_key, config.llm_base_url)

        # Summary
        print(f"\n{'='*60}")
        print("Summary")
        print(f"{'='*60}")
        for provider, success in results.items():
            status = "✓ PASS" if success else "✗ FAIL"
            print(f"{status:8} {provider}")

        # Exit code
        sys.exit(0 if all(results.values()) else 1)

    elif args.provider:
        # Test specific provider
        success = test_provider(args.provider, config.llm_api_key, config.llm_base_url)
        sys.exit(0 if success else 1)

    else:
        # Test configured provider
        print(f"Testing configured provider from .env")
        print(f"Provider: {config.llm_provider}")
        print(f"Model: {config.llm_annotation_model}")
        if config.llm_base_url:
            print(f"Base URL: {config.llm_base_url}")

        success = test_provider(config.llm_provider, config.llm_api_key, config.llm_base_url)
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
