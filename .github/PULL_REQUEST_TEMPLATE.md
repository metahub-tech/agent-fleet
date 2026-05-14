## Summary

<!-- What does this PR do, in 1-3 sentences? -->

## Changes

<!-- Bullet list of the concrete changes. -->

-

## Test plan

<!-- How did you verify this? Adjust to what your change touches. -->

```bash
# Python (CLI package)
cd cli && PYTHONPATH=src python3 -m pytest

# Shell scripts — syntax check
find platforms scripts -name '*.sh' -exec bash -n {} \;

# PowerShell scripts (requires pwsh 7+)
./scripts/check-ps-syntax.sh
```

## Checklist

- [ ] Tests pass locally
- [ ] Docs updated if behavior changed
- [ ] No version bump (unless this is the release PR)
- [ ] For new platforms / tool-contract changes: linked a discussion Issue first
