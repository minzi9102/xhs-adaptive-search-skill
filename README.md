# xhs-adaptive-search-skill

Adaptive Xiaohongshu topic search guidance skill with a legacy automation dependency.

## Quick Start

1. Clone repository.
2. Initialize submodule dependency.

```powershell
git submodule update --init --recursive
```

3. Verify the automation entrypoint exists.

```powershell
Get-Item .\skills\xiaohongshu-automation\scripts\entrypoints\xhs.py
```

4. Run the readiness check.

```powershell
uv run --python .\.venv\Scripts\python.exe .\skills\xiaohongshu-automation\scripts\entrypoints\xhs.py doctor
```

## Notes

- The command path intentionally keeps `.\skills\xiaohongshu-automation\...`.
- If submodule is not initialized, adaptive search commands will fail.
