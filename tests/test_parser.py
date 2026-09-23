"""Targeted parser behaviour (IX-03, IX-04); the fixture snapshots cover breadth."""

from __future__ import annotations

import textwrap

import pytest

from compass.index.parser import normalize_signature, parse_source
from compass.languages import load_registry


def parse(lang: str, source: str, path: str | None = None):
    spec = load_registry().get(lang)
    ext = {"python": "py", "typescript": "ts", "javascript": "js", "go": "go", "rust": "rs"}[lang]
    return parse_source(spec, path or f"sample.{ext}", textwrap.dedent(source).lstrip().encode())


def by_name(result):
    return {(s.parent, s.name): s for s in result.symbols}


def test_python_nesting_docs_and_visibility():
    result = parse(
        "python",
        '''
        """Module summary."""

        # Leading comment wins when there is no docstring.
        @decorator
        def helper(a: int,
                   b: str = "x") -> bool:
            def inner():
                pass
            return True

        class Policy(Base):
            """Policy doc."""

            def _private(self):  # trailing comment
                """Private method."""

            class Nested:
                def deep(self): ...
        ''',
    )
    syms = by_name(result)
    assert result.doc == "Module summary."
    helper = syms[(None, "helper")]
    assert helper.kind == "function"
    assert helper.start_line == 4  # the decorator line, not the def line
    assert helper.signature == 'helper(a: int, b: str = "x") -> bool'
    assert helper.doc == "Leading comment wins when there is no docstring."
    assert (None, "inner") not in syms and ("helper", "inner") not in syms  # local: dropped
    assert syms[("Policy", "_private")].kind == "method"
    assert syms[("Policy", "_private")].visibility == "private"
    assert syms[("Policy", "_private")].doc == "Private method."
    assert syms[("Policy.Nested", "deep")].kind == "method"


def test_python_constants_are_upper_case_only():
    result = parse("python", "MAX = 5\n_LIMIT = 2\nstate = {}\n")
    names = {s.name: s.visibility for s in result.symbols}
    assert names == {"MAX": "public", "_LIMIT": "private"}


def test_comment_inside_signature_is_dropped():
    result = parse("python", "def get(self, key):  # explain\n    return 1\n")
    assert result.symbols[0].signature == "get(self, key)"


def test_typescript_members_exports_and_arrow_functions():
    result = parse(
        "typescript",
        """
        /** Retry strategy. */
        export class Policy extends Base {
          private secret = 1;
          #hidden(): void {}
          protected onTick(e: Event): void {}
          handler = (e: Event): void => {};
          single = x => x;
        }

        export const withRetry = async <T>(op: () => Promise<T>): Promise<T> => op();
        const helper = function (a: string) {};
        export interface Shape { area(): number; }
        function local() { function inner() {} }
        """,
    )
    syms = by_name(result)
    assert syms[(None, "Policy")].visibility == "public"
    assert syms[(None, "Policy")].doc == "Retry strategy."
    assert syms[("Policy", "#hidden")].visibility == "private"
    assert syms[("Policy", "onTick")].visibility == "protected"
    assert syms[("Policy", "handler")].signature == "handler(e: Event): void"
    assert syms[("Policy", "single")].signature == "single(x)"
    assert ("Policy", "secret") not in syms  # plain fields stay out of the map
    assert syms[(None, "withRetry")].signature == "withRetry<T>(op: () => Promise<T>): Promise<T>"
    assert syms[(None, "helper")].visibility == "private"
    assert syms[("Shape", "area")].visibility == "public"  # inherited from the interface
    assert (None, "inner") not in syms and ("local", "inner") not in syms


def test_tsx_uses_the_tsx_grammar():
    result = parse("typescript", "export const Button = ({ label }: P) => <b>{label}</b>;\n", "Button.tsx")
    assert [(s.name, s.signature) for s in result.symbols] == [("Button", "Button({label}: P)")]


def test_go_methods_name_their_receiver():
    result = parse(
        "go",
        """
        // Package demo is a demo.
        package demo

        // Stack holds items.
        type Stack[T any] struct{ items []T }

        // Push adds v.
        func (s *Stack[T]) Push(v T) {}

        func helper() {}
        """,
    )
    syms = by_name(result)
    assert result.doc == "Package demo is a demo."
    assert syms[(None, "Stack")].signature == "Stack[T any]"
    push = syms[("Stack", "Push")]
    assert (push.kind, push.visibility, push.doc) == ("method", "public", "Push adds v.")
    assert syms[(None, "helper")].visibility == "private"


def test_rust_impls_attributes_and_visibility():
    result = parse(
        "rust",
        """
        //! Crate docs.

        /// A point.
        #[derive(Debug)]
        pub struct Point { x: i32 }

        impl Point {
            /// Makes one.
            pub fn new() -> Self { Point { x: 0 } }
            fn hidden(&self) {}
        }

        impl std::fmt::Display for Point {
            fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result { Ok(()) }
        }

        pub(crate) trait Store { fn get(&self) -> u8; }
        """,
    )
    syms = [(s.kind, s.parent, s.name, s.visibility, s.signature) for s in result.symbols]
    assert result.doc == "Crate docs."
    point = result.symbols[0]
    assert (point.name, point.start_line, point.doc) == ("Point", 4, "A point.")  # starts at the attribute
    assert ("impl", None, "Point", None, "Point") in syms
    assert ("method", "Point", "new", "public", "new() -> Self") in syms
    assert ("method", "Point", "hidden", "private", "hidden(&self)") in syms
    assert ("impl", None, "Point", None, "std::fmt::Display for Point") in syms
    assert ("method", "Point", "fmt", "public", "fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result") in syms
    assert ("method", "Store", "get", "internal", "get(&self) -> u8") in syms


def test_lint_directives_are_not_docs():
    result = parse(
        "typescript",
        "class A {\n  // eslint-disable-next-line complexity\n  run(): void {}\n"
        "  /** Real doc. */\n  // @ts-expect-error legacy\n  stop(): void {}\n}\n",
    )
    assert {s.name: s.doc for s in result.symbols} == {"A": None, "run": None, "stop": "Real doc."}


def test_where_clauses_lose_their_trailing_comma():
    result = parse("rust", "impl<E> Ext for E\nwhere\n    E: Send,\n{\n    fn f(&self) {}\n}\n")
    assert result.symbols[0].signature == "Ext for E where E: Send"


def test_every_name_in_a_multi_name_declaration_is_a_symbol():
    result = parse("go", "package p\n\nvar MinRetries, MaxRetries int\n\nconst (\n\tA, B = 1, 2\n)\n")
    assert sorted((s.name, s.signature) for s in result.symbols) == [
        ("A", "A, B = 1, 2"),
        ("B", "A, B = 1, 2"),
        ("MaxRetries", "MinRetries, MaxRetries int"),
        ("MinRetries", "MinRetries, MaxRetries int"),
    ]


def test_symbol_order_is_total():
    from compass.index.model import Symbol

    a = Symbol("f", "method", "C", "f(int x)", 3, 3, "public", None)
    b = Symbol("f", "method", "C", "f(String s)", 3, 3, "public", None)
    assert sorted([a, b], key=Symbol.sort_key) == sorted([b, a], key=Symbol.sort_key) == [b, a]


def test_blank_line_detaches_a_comment():
    result = parse("go", "package p\n\n// Unrelated note.\n\nfunc F() {}\n")
    assert result.symbols[0].doc is None


def test_trailing_comment_is_not_a_doc():
    result = parse("typescript", "const a = 1; // not a doc\nexport function f() {}\n")
    assert [s.doc for s in result.symbols if s.name == "f"] == [None]


@pytest.mark.parametrize(
    ("lang", "source", "calls"),
    [
        ("python", "import x\n\n@app.route('/')\ndef f():\n    helper(1)\n    obj.method()\n", {("route", 3), ("helper", 5), ("method", 6)}),
        ("typescript", "const a = run();\nnew Policy(1);\nthis.#tick();\nobj.save?.();\n", {("run", 1), ("Policy", 2), ("#tick", 3)}),
        ("javascript", "go();\nmodule.load('x');\n", {("go", 1), ("load", 2)}),
        ("go", "package p\n\nfunc f() {\n\tRetry()\n\tpkg.Do(x)\n}\n", {("Retry", 4), ("Do", 5)}),
        (
            "rust",
            "fn f() {\n    run();\n    x.next();\n    Point::new();\n    parse::<u8>();\n    assert!(ok(1));\n}\n",
            {("run", 2), ("next", 3), ("new", 4), ("parse", 5), ("ok", 6)},
        ),
    ],
)
def test_call_references_are_captured(lang, source, calls):
    refs = {(r.name, r.line) for r in parse(lang, source).refs}
    assert calls <= refs


def test_imports_are_captured():
    # `from m import x` targets m.x: a submodule when one exists, else m itself (the resolver decides)
    python = "import os.path\nimport a as b\nfrom . import x\nfrom .. import y as z\nfrom .a.b import c, d\nfrom e import *\n"
    assert parse("python", python).imports == ("..y", ".a.b.c", ".a.b.d", ".x", "a", "e", "os.path")
    assert parse("typescript", 'import a from "./a";\nexport * from "./b";\nconst c = require("c");\n').imports == (
        "./a",
        "./b",
        "c",
    )
    assert parse("go", 'package p\nimport (\n\t"fmt"\n\tx "net/http"\n)\n').imports == ("fmt", "net/http")
    rust = (
        "use std::io;\nuse crate::a::{b, c::d, e as f};\nuse crate::util as u;\nuse super::*;\nextern crate g;\n"
        "mod tests {\n    use super::*;\n    use crate::inner;\n}\n"
    )
    # only file-level uses: `super` inside an inline module means the file itself
    assert parse("rust", rust).imports == (
        "crate::a::b", "crate::a::c::d", "crate::a::e", "crate::util", "g", "std::io", "super",
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("foo(\n    a,\n    b,\n) -> int:", "foo(a, b) -> int"),
        ("Point<T> {", "Point<T>"),
        ("MAX: u32 = 5;", "MAX: u32 = 5"),
        ("handler =>", "handler"),
    ],
)
def test_normalize_signature(raw, expected):
    assert normalize_signature(raw) == expected


def test_long_signatures_are_capped():
    sig = normalize_signature("f(" + ", ".join(f"arg{i}: int" for i in range(40)) + ")")
    assert len(sig) == 160 and sig.endswith("…")
