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
- [ ] **All commits are `Signed-off-by:` (DCO)** — use `git commit -s` or `git rebase --signoff main`
- [ ] If AI-assisted: added `Co-Authored-By:` trailer (see `CONTRIBUTING.md` § AI-assisted contributions)
- [ ] Docs updated if behavior changed
- [ ] If touching platform code: also ran `./scripts/gen-blueprint-map.sh` and `./scripts/gen-blueprint-interface.sh` (蓝图同步)
- [ ] No version bump (unless this is the release PR)
- [ ] For new platforms / tool-contract changes: linked a discussion Issue first
