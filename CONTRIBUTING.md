# Contributing

This project helps Claude Code users on Windows preserve their shared subscription allowance for chat. Bug reports and focused fixes are welcome. Open an issue to discuss a new platform, quota source, or provider before starting a larger change.

On Windows, run the existing checks from the checkout.

```powershell
python -B -m unittest -v
.\test-install-powershell.ps1
python -B limiter.py demo
```

The test suite and demo work without a Claude subscription. The installer smoke test uses a temporary profile and install location. When reporting a bug, share the Windows, PowerShell, Python, and Claude Code versions and the shortest steps that reproduce it. Remove credentials, prompt contents, and personal paths from logs.
