# Pinned mini-swe-agent distribution

The coding extra installs the Alibaba Function Compute fork, version `2.4.6+fc.1`, from the wheel in this directory. Its MIT license is included in the wheel.

Source: [aliyun-fc/mini-swe-agent](https://github.com/aliyun-fc/mini-swe-agent), tag `v2.4.6-fc.1`. The package was built from the source checkout reused by the existing Alibaba evaluation integration. This is a distribution of that fork; it is not claimed to be an unchanged wheel from upstream SWE-agent.

- File: `mini_swe_agent-2.4.6+fc.1-py3-none-any.whl`
- Bytes: 127941
- SHA-256: `18741a437c57bb36a0833b7d15a9e691bb51af0a3f4beafa4168bdaa90a4b3b5`

Keeping this small pinned wheel in Git makes `uv sync --locked --dev --extra coding` work from a fresh checkout, including GitHub Actions. Task outputs and credentials remain outside this directory.
