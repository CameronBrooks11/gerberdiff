# Contributing

Thank you for your interest in contributing to **gerberdiff**!

## Development setup

Requires Python >= 3.11 and [uv](https://docs.astral.sh/uv/).

```sh
git clone https://github.com/CameronBrooks11/gerberdiff.git
cd gerberdiff
uv sync --dev
```

## Running the test suite

```sh
uv run pytest tests/ -q
```

With coverage:

```sh
uv run pytest tests/ --cov=gerberdiff --cov-report=term-missing
```

## Lint and type checking

```sh
uv run ruff check gerberdiff/ tests/
uv run ruff format gerberdiff/ tests/
uv run mypy gerberdiff/ tests/
```

All three must pass with no errors before a PR will be merged. CI enforces this on every push.

## Commit messages

- Single-sentence subject, imperative mood, no trailing period
- [Conventional-commit](https://www.conventionalcommits.org/) type prefixes
  (`feat:`, `fix:`, `docs:`, `test:`, `perf:`, `chore:`, `ci:`) are
  encouraged and used throughout recent history
  (e.g. `feat(geometry): add geometry diff engine core`)

## Pull request checklist

- [ ] Tests added or updated for every changed behaviour
- [ ] `uv run ruff check` and `uv run mypy` pass locally
- [ ] `CHANGELOG.md` `[Unreleased]` section updated

## Versioning

This project follows [Semantic Versioning](https://semver.org/).  
The version is set in **both** `pyproject.toml` and `gerberdiff/__init__.py`; keep them in sync.

## Character usage

All tracked files must be pure ASCII (U+0000--U+007F). This covers Python
source, tests, TOML, YAML, Markdown, and any other text file in the repo.

Non-ASCII characters cause silent encoding failures in terminals, diff tools,
and CI environments that default to a non-UTF-8 locale. They are invisible in
many fonts and meaningless to grep.

**Banned characters and their ASCII replacements:**

| Character         | Codepoint | Use instead |
| ----------------- | --------- | ----------- |
| em dash           | U+2014    | `--`        |
| en dash           | U+2013    | `-`         |
| ellipsis          | U+2026    | `...`       |
| right arrow       | U+2192    | `->`        |
| left arrow        | U+2190    | `<-`        |
| multiplication    | U+00D7    | `x`         |
| minus sign        | U+2212    | `-`         |
| greater-or-equal  | U+2265    | `>=`        |
| less-or-equal     | U+2264    | `<=`        |
| almost-equal      | U+2248    | `~=`        |
| plus-minus        | U+00B1    | `+/-`       |
| degree            | U+00B0    | `deg`       |
| superscript 2     | U+00B2    | `^2`            |
| box-drawing chars | U+2500+   | `-`, `\|`, `+`  |

To check a branch before committing:

```sh
python - <<'EOF'
import subprocess, sys
out = subprocess.run(["git","ls-files"], capture_output=True, text=True).stdout.splitlines()
skip = {".gbr",".drl",".png",".lock",".pyc",".whl"}
bad = 0
for p in out:
    if any(p.endswith(s) for s in skip) or ".venv" in p:
        continue
    try:
        t = open(p, encoding="utf-8").read()
    except Exception:
        continue
    for i, ch in enumerate(t):
        if ord(ch) > 127:
            line = t[:i].count("\n") + 1
            print(f"{p}:{line} U+{ord(ch):04X} {ch!r}")
            bad += 1
print(f"\n{bad} violation(s)" if bad else "clean")
sys.exit(1 if bad else 0)
EOF
```

## License

By contributing you agree that your contributions will be licensed under the
[Apache-2.0](https://github.com/CameronBrooks11/gerberdiff/blob/main/LICENSE)
licence.
