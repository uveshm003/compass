"""Import resolution rules (IX-11), per strategy."""

from __future__ import annotations

import pytest

from compass.index.resolve import Resolver
from compass.languages import load_registry
from conftest import write


def resolver(tmp_path, files: dict[str, str | None], texts: dict[str, str] | None = None) -> Resolver:
    for rel, text in (texts or {}).items():
        write(tmp_path, rel, text)
    return Resolver(tmp_path, files, load_registry())


@pytest.mark.parametrize(
    ("importer", "target", "expected"),
    [
        ("src/app.ts", "./util", "src/util.ts"),
        ("src/app.ts", "./util.js", "src/util.ts"),  # ESM style names the emitted file
        ("src/app.ts", "./widgets", "src/widgets/index.tsx"),
        ("src/deep/x.ts", "../util", "src/util.ts"),
        ("src/app.ts", "./styles.css", None),
        ("src/app.ts", "react", None),
        ("src/app.ts", "../../outside", None),
    ],
)
def test_path_resolver(tmp_path, importer, target, expected):
    files = {
        "src/app.ts": "typescript", "src/util.ts": "typescript", "src/widgets/index.tsx": "typescript",
        "src/deep/x.ts": "typescript",
    }
    assert resolver(tmp_path, files).resolve(importer, "typescript", target) == expected


@pytest.mark.parametrize(
    ("importer", "target", "expected"),
    [
        ("src/pkg/a.py", ".mod", "src/pkg/mod.py"),
        ("src/pkg/sub/a.py", "..mod", "src/pkg/mod.py"),
        ("src/pkg/a.py", ".", "src/pkg/__init__.py"),
        ("tests/test_a.py", "pkg.mod", "src/pkg/mod.py"),
        ("tests/test_a.py", "pkg", "src/pkg/__init__.py"),
        ("tests/test_a.py", "pkg.mod.Thing", "src/pkg/mod.py"),  # trailing segments name items
        ("tests/test_a.py", "mod", None),  # src/pkg is a package, so `mod` alone is not importable
        ("tests/test_a.py", "os.path", None),
        # `from pkg import mod` / `from . import mod`: the submodule, else the package
        ("tests/test_a.py", "pkg.mod", "src/pkg/mod.py"),
        ("tests/test_a.py", "pkg.Thing", "src/pkg/__init__.py"),
        ("src/pkg/sub/a.py", "..mod", "src/pkg/mod.py"),
        ("src/pkg/a.py", ".Thing", "src/pkg/__init__.py"),
        ("src/pkg/__init__.py", ".Thing", None),  # an import of the file itself
        # a lone module file only matches where it is on the importer's path
        ("src/pkg/a.py", "os.path", None),  # not scripts/os.py
        ("scripts/run.py", "os.path", "scripts/os.py"),  # a script's own directory comes first
        ("tests/test_a.py", "flat", "src/flat.py"),  # src/ is a source root
        ("tests/test_a.py", "helpers", "tests/helpers.py"),
        ("tests/unit/test_b.py", "helpers.make", "tests/helpers.py"),
        ("src/pkg/a.py", "helpers", None),
    ],
)
def test_module_resolver_python(tmp_path, importer, target, expected):
    files = {
        "src/pkg/__init__.py": "python", "src/pkg/a.py": "python", "src/pkg/mod.py": "python",
        "src/pkg/sub/__init__.py": "python", "src/pkg/sub/a.py": "python", "tests/test_a.py": "python",
        "scripts/os.py": "python", "scripts/run.py": "python", "src/flat.py": "python",
        "tests/helpers.py": "python", "tests/unit/test_b.py": "python",
    }
    assert resolver(tmp_path, files).resolve(importer, "python", target) == expected


@pytest.mark.parametrize(
    ("importer", "target", "expected"),
    [
        ("src/main.rs", "crate::transport::retry::Backoff", "src/transport/retry.rs"),
        ("src/transport/retry.rs", "super::util", "src/transport/util.rs"),
        ("src/transport/mod.rs", "self::util", "src/transport/util.rs"),
        ("src/transport/retry.rs", "self::inner", "src/transport/retry/inner.rs"),
        ("tests/it.rs", "my_crate::transport::retry", "src/transport/retry.rs"),  # crate name dropped
        ("src/main.rs", "crate::transport::{retry, util}", "src/transport/mod.rs"),
        ("src/main.rs", "std::fmt", None),
        ("src/main.rs", "tokio::sync::mpsc", None),
    ],
)
def test_module_resolver_rust(tmp_path, importer, target, expected):
    files = {
        "src/main.rs": "rust", "src/transport/mod.rs": "rust", "src/transport/retry.rs": "rust",
        "src/transport/util.rs": "rust", "src/transport/retry/inner.rs": "rust", "tests/it.rs": "rust",
    }
    assert resolver(tmp_path, files).resolve(importer, "rust", target) == expected


@pytest.mark.parametrize(
    ("importer", "target", "expected"),
    [
        ("src/net/conn.rs", "super::shared", "src/net.rs"),  # the parent module's file sits beside its directory
        ("src/net/conn.rs", "super::super::util", "src/util.rs"),
        ("src/util.rs", "super::net", "src/net.rs"),
        ("src/util.rs", "super::VERSION", "src/lib.rs"),  # an item of the crate root
        ("src/net/conn.rs", "crate::util", "src/util.rs"),  # `use crate::util as u` captures the path
        ("src/net.rs", "self::conn::open", "src/net/conn.rs"),
        ("src/net.rs", "self::shared", None),  # an item of the file itself
    ],
)
def test_module_resolver_rust_2018_layout(tmp_path, importer, target, expected):
    files = {"src/lib.rs": "rust", "src/util.rs": "rust", "src/net.rs": "rust", "src/net/conn.rs": "rust"}
    assert resolver(tmp_path, files).resolve(importer, "rust", target) == expected


TSCONFIG = """{
  // comments and trailing commas are allowed in tsconfig.json
  "extends": "./tsconfig.base.json",
  "compilerOptions": {
    "paths": {
      "@/*": ["./src/*"],
      "@ui/*": ["./src/components/ui/*", "./vendor/ui/*"],
      "config": ["./src/config/index.ts"],
    },
  },
}
"""


@pytest.mark.parametrize(
    ("importer", "target", "expected"),
    [
        ("web/src/app/page.ts", "@/lib/utils", "web/src/lib/utils.ts"),
        ("web/src/app/page.ts", "@ui/button", "web/src/components/ui/button.tsx"),  # the longer prefix wins
        ("web/src/app/page.ts", "@ui/legacy", "web/vendor/ui/legacy.ts"),  # the next substitution
        ("web/src/app/page.ts", "config", "web/src/config/index.ts"),
        ("web/src/app/page.ts", "shared/format", "web/shared/format.ts"),  # baseUrl from the extended file
        ("web/src/app/page.ts", "react", None),
        ("other/x.ts", "@/lib/utils", None),  # outside that tsconfig's tree
    ],
)
def test_path_resolver_tsconfig_aliases(tmp_path, importer, target, expected):
    files = {
        "web/tsconfig.json": None, "web/tsconfig.base.json": None, "web/src/app/page.ts": "typescript",
        "web/src/lib/utils.ts": "typescript", "web/src/components/ui/button.tsx": "typescript",
        "web/vendor/ui/legacy.ts": "typescript", "web/src/config/index.ts": "typescript",
        "web/shared/format.ts": "typescript", "other/x.ts": "typescript",
    }
    texts = {"web/tsconfig.json": TSCONFIG, "web/tsconfig.base.json": '{"compilerOptions": {"baseUrl": "."}}'}
    assert resolver(tmp_path, files, texts).resolve(importer, "typescript", target) == expected


def test_jsconfig_aliases_for_javascript(tmp_path):
    files = {"jsconfig.json": None, "app/main.js": "javascript", "lib/log.js": "javascript"}
    texts = {"jsconfig.json": '{"compilerOptions": {"baseUrl": ".", "paths": {"~/*": ["lib/*"]}}}'}
    assert resolver(tmp_path, files, texts).resolve("app/main.js", "javascript", "~/log") == "lib/log.js"


def test_unreadable_alias_files_are_ignored(tmp_path):
    files = {"tsconfig.json": None, "a.ts": "typescript", "b.ts": "typescript"}
    texts = {"tsconfig.json": "{ not json"}
    r = resolver(tmp_path, files, texts)
    assert r.resolve("a.ts", "typescript", "@/b") is None
    assert r.resolve("a.ts", "typescript", "./b") == "b.ts"


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("github.com/acme/app/pkg/api", "pkg/api"),
        ("github.com/acme/app/tools/gen", "tools/gen"),  # the nested module wins
        ("github.com/acme/app", ""),
        ("github.com/acme/app/missing", None),
        ("github.com/other/lib", None),
        ("fmt", None),
    ],
)
def test_package_resolver_go(tmp_path, target, expected):
    files = {
        "go.mod": None, "main.go": "go", "pkg/api/api.go": "go", "tools/go.mod": None,
        "tools/gen/gen.go": "go",
    }
    texts = {"go.mod": "module github.com/acme/app\n\ngo 1.22\n", "tools/go.mod": "module github.com/acme/app/tools\n"}
    assert resolver(tmp_path, files, texts).resolve("main.go", "go", target) == expected


def test_languages_without_a_resolver_resolve_nothing(tmp_path):
    assert resolver(tmp_path, {"a.rb": "ruby"}).resolve("a.rb", "ruby", "./b") is None
