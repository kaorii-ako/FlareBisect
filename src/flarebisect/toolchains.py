"""Toolchain detection and per-worktree preparation.

A fresh `git worktree` is a bare checkout: no `node_modules`, no `target/`,
no compiled binaries. Any command more involved than `pytest` fails at every
commit for reasons that have nothing to do with the bug being bisected. So
before running the command N times, each worktree gets a one-time *setup*
step — `npm ci`, `go mod download`, `cargo fetch`, whatever the repo needs.

Setup is inferred from marker files (or from the command itself, so `cargo
test` means Rust regardless of what's on disk) and is always overridable with
`--setup`. Package-manager caches are redirected to a shared directory so the
same dependencies aren't re-downloaded once per commit.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Toolchain:
    name: str
    markers: tuple[str, ...]
    test: str
    setup: str | None = None
    commands: tuple[str, ...] = ()
    # env var -> subdirectory under the shared cache root
    cache_env: dict[str, str] = field(default_factory=dict)


# Order matters: lockfile-specific entries come before the generic manifest
# they sit next to, and catch-all build systems (make, cmake) come last.
TOOLCHAINS: tuple[Toolchain, ...] = (
    Toolchain(
        name="node-pnpm",
        markers=("pnpm-lock.yaml",),
        setup="pnpm install --frozen-lockfile",
        test="pnpm test",
        commands=("pnpm",),
        cache_env={"npm_config_cache": "npm", "PNPM_HOME": "pnpm"},
    ),
    Toolchain(
        name="node-yarn",
        markers=("yarn.lock",),
        setup="yarn install --frozen-lockfile",
        test="yarn test",
        commands=("yarn",),
        cache_env={"YARN_CACHE_FOLDER": "yarn"},
    ),
    Toolchain(
        name="node-bun",
        markers=("bun.lockb", "bun.lock"),
        setup="bun install",
        test="bun test",
        commands=("bun", "bunx"),
        cache_env={"BUN_INSTALL_CACHE_DIR": "bun"},
    ),
    Toolchain(
        name="node-npm",
        markers=("package-lock.json", "package.json"),
        setup="npm ci || npm install",
        test="npm test",
        commands=("npm", "npx", "node", "jest", "vitest", "mocha"),
        cache_env={"npm_config_cache": "npm"},
    ),
    Toolchain(
        name="go",
        markers=("go.mod",),
        # Build during setup too — GOCACHE is shared and concurrency-safe, so
        # the parallel runs hit a warm cache instead of compiling N times.
        setup="go mod download && go build ./...",
        test="go test ./...",
        commands=("go", "gotestsum"),
        cache_env={"GOMODCACHE": "go-mod", "GOCACHE": "go-build"},
    ),
    Toolchain(
        name="rust",
        markers=("Cargo.toml",),
        # Compile the test binaries during setup, so the N parallel runs execute
        # them instead of each taking cargo's build lock in turn.
        setup="cargo test --no-run",
        test="cargo test",
        commands=("cargo",),
        # Only the registry is shared. A shared CARGO_TARGET_DIR would be worse
        # than none: consecutive commits have different sources, so they'd evict
        # each other's artifacts and serialize on the same lock.
        cache_env={"CARGO_HOME": "cargo"},
    ),
    Toolchain(
        name="python-uv",
        markers=("uv.lock",),
        setup="uv sync --frozen",
        test="uv run pytest",
        commands=("uv",),
        cache_env={"UV_CACHE_DIR": "uv"},
    ),
    Toolchain(
        name="python-poetry",
        markers=("poetry.lock",),
        setup="poetry install --no-interaction",
        test="poetry run pytest",
        commands=("poetry",),
        cache_env={"POETRY_CACHE_DIR": "poetry", "PIP_CACHE_DIR": "pip"},
    ),
    Toolchain(
        name="python",
        markers=("pyproject.toml", "setup.py", "requirements.txt", "tox.ini", "conftest.py"),
        # A plain Python checkout is usually importable as-is from the worktree
        # root, so there is nothing to build. Installing would fight whatever
        # venv the caller already activated.
        setup=None,
        test="pytest",
        commands=("pytest", "python", "python3", "tox", "nox", "unittest"),
        cache_env={"PIP_CACHE_DIR": "pip"},
    ),
    Toolchain(
        name="maven",
        markers=("pom.xml",),
        setup="mvn -B -q -DskipTests dependency:go-offline",
        test="mvn -B -q test",
        commands=("mvn", "mvnw"),
        cache_env={},
    ),
    Toolchain(
        name="gradle",
        markers=("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"),
        setup="./gradlew --quiet assemble -x test || gradle --quiet assemble -x test",
        test="./gradlew --quiet test || gradle --quiet test",
        commands=("gradle", "gradlew"),
        cache_env={"GRADLE_USER_HOME": "gradle"},
    ),
    Toolchain(
        name="ruby",
        markers=("Gemfile", "Rakefile", ".rspec"),
        setup="bundle install",
        test="bundle exec rspec",
        commands=("bundle", "rspec", "rake", "ruby"),
        cache_env={"BUNDLE_USER_CACHE": "bundler"},
    ),
    Toolchain(
        name="dotnet",
        markers=("*.sln", "*.csproj", "*.fsproj"),
        setup="dotnet restore",
        test="dotnet test",
        commands=("dotnet",),
        cache_env={"NUGET_PACKAGES": "nuget"},
    ),
    Toolchain(
        name="elixir",
        markers=("mix.exs",),
        setup="mix deps.get && mix compile",
        test="mix test",
        commands=("mix",),
        cache_env={"MIX_HOME": "mix", "HEX_HOME": "hex"},
    ),
    Toolchain(
        name="php",
        markers=("composer.json",),
        setup="composer install --no-interaction",
        test="vendor/bin/phpunit",
        commands=("composer", "phpunit", "php"),
        cache_env={"COMPOSER_CACHE_DIR": "composer"},
    ),
    Toolchain(
        name="swift",
        markers=("Package.swift",),
        setup="swift build",
        test="swift test",
        commands=("swift",),
        cache_env={},
    ),
    Toolchain(
        name="cmake",
        markers=("CMakeLists.txt",),
        setup="cmake -S . -B build && cmake --build build",
        test="ctest --test-dir build --output-on-failure",
        commands=("cmake", "ctest"),
        cache_env={},
    ),
    Toolchain(
        name="make",
        markers=("Makefile", "makefile", "GNUmakefile"),
        setup="make",
        test="make test",
        commands=("make", "gmake"),
        cache_env={},
    ),
)

BY_NAME = {tc.name: tc for tc in TOOLCHAINS}


def _marker_present(repo: Path, marker: str) -> bool:
    if "*" in marker:
        return any(repo.glob(marker))
    return (repo / marker).exists()


def _command_head(command: str) -> str:
    """First bare word of a shell command, minus any ./ or path prefix."""
    for token in command.split():
        # skip leading env assignments like `FOO=1 npm test`
        if "=" in token and not token.startswith("-"):
            continue
        return Path(token).name
    return ""


def detect_by_command(command: str) -> Toolchain | None:
    """`cargo test` means Rust whether or not Cargo.toml is where we looked."""
    head = _command_head(command)
    if not head:
        return None
    for tc in TOOLCHAINS:
        if head in tc.commands:
            return tc
    return None


def detect_by_markers(repo: Path) -> Toolchain | None:
    for tc in TOOLCHAINS:
        if any(_marker_present(repo, m) for m in tc.markers):
            return tc
    return None


def detect_all(repo: Path) -> list[Toolchain]:
    """Every toolchain whose markers are present — polyglot repos hit several."""
    return [tc for tc in TOOLCHAINS if any(_marker_present(repo, m) for m in tc.markers)]


def detect(repo: Path, command: str | None = None) -> Toolchain | None:
    """Identify the repo's toolchain, preferring the evidence in `command`."""
    if command:
        by_cmd = detect_by_command(command)
        if by_cmd is not None:
            return by_cmd
    return detect_by_markers(repo)


@dataclass
class Plan:
    """The resolved command + setup step for a run, and where each came from."""

    command: str
    setup: str | None
    toolchain: Toolchain | None
    command_source: str  # "flag" | "toolchain"
    setup_source: str  # "flag" | "toolchain" | "none" | "disabled"


def resolve_plan(
    repo: Path,
    command: str | None,
    setup: str | None,
    no_setup: bool = False,
) -> Plan:
    """Fill in whatever the caller didn't pass from the detected toolchain.

    Explicit flags always win; detection only supplies what's missing.
    """
    tc = detect(repo, command)

    if command:
        resolved_command, command_source = command, "flag"
    elif tc is not None:
        resolved_command, command_source = tc.test, "toolchain"
    else:
        raise ValueError(
            "no command given and no toolchain detected in this repo — "
            "pass --cmd \"<command to run>\" (e.g. --cmd \"npm test\")"
        )

    if no_setup:
        resolved_setup, setup_source = None, "disabled"
    elif setup:
        resolved_setup, setup_source = setup, "flag"
    elif tc is not None and tc.setup:
        resolved_setup, setup_source = tc.setup, "toolchain"
    else:
        resolved_setup, setup_source = None, "none"

    return Plan(
        command=resolved_command,
        setup=resolved_setup,
        toolchain=tc,
        command_source=command_source,
        setup_source=setup_source,
    )


def cache_root() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA", str(Path.home()))
    else:
        base = os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))
    return Path(base) / "flarebisect" / "toolchain"


def build_env(toolchain: Toolchain | None, share_cache: bool = True) -> dict[str, str]:
    """Environment for setup + command runs.

    Package-manager caches are pointed at one shared directory so a 12-commit
    bisection downloads its dependencies once instead of twelve times. An env
    var the caller already set is left alone — their cache location wins.
    """
    env = dict(os.environ)
    if not share_cache or toolchain is None:
        return env

    root = cache_root()
    for var, subdir in toolchain.cache_env.items():
        if var in os.environ:
            continue
        path = root / subdir
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        env[var] = str(path)
    return env
