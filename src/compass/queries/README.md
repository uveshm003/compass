# Language queries

One directory per language. Adding a language touches nothing else in the core:

| File | Required | Purpose |
| --- | --- | --- |
| `language.yaml` | yes | Grammar name, file matching, doc and visibility rules |
| `tags.scm` | yes | Definitions: what becomes a symbol row and a map-shard line |
| `imports.scm` | no | Import targets for the import graph (IX-11) |

A language only counts as supported once it also has a fixture repo under
`tests/fixtures/` and a passing snapshot test.

## `language.yaml`

```yaml
name: typescript               # must equal the directory name
grammar: typescript            # tree-sitter-language-pack grammar
grammar_by_extension: {.tsx: tsx}
extensions: [.ts, .tsx]
filenames: []                  # exact file names, e.g. Dockerfile
shebangs: [node]               # interpreters, for extensionless scripts
wrappers: [export_statement]   # nodes that wrap a definition; the symbol range
                               # and doc lookup extend to them
skip_before_doc: [decorator]   # siblings allowed between a doc comment and
                               # its definition; they also extend the range
docstring: body_first_string   # optional named docstring rule (see below)
index_files: [index.ts]        # a folder's purpose comes from this file's
                               # header when the folder has no README
visibility:
  modifiers: [["^private$", private]]  # regex over the @visibility capture
  names: [["^#", private]]             # regex over the symbol name
  exported_by: [export_statement]      # declarations are public only inside these
  default: public
tests:                         # test mapping for tests_for (IX-12)
  files: ["**/*.test.*"]       # globs marking test files
  name_prefixes: [test_]       # test_models.py tests models.py
  name_suffixes: [.test, _test]  # reconnect.test.ts tests reconnect.ts
  same_package: false          # Go: a test file covers its whole directory
  inline_module: tests         # Rust: `mod tests` inside the source file
imports:                       # import resolution for importers_of (IX-11)
  resolver: path               # path | module | package, see below
  extensions: [.ts, .tsx]
  extension_aliases: {.js: [.ts]}   # ESM: "./a.js" in TS source means a.ts
  index_files: [index.ts]      # a directory import means this file
  alias_files: [tsconfig.json] # path: compilerOptions.paths and baseUrl
  source_roots: [src]          # module: directories on the import path
```

Import resolvers (implemented in `index/resolve.py`):

- `path`: `./` and `../` specifiers relative to the importing file, trying
  `extensions`, `extension_aliases` and `index_files`. Bare specifiers go
  through the nearest `alias_files` entry up the tree (tsconfig.json or
  jsconfig.json, comments and trailing commas allowed, relative `extends`
  followed): its `compilerOptions.paths` (an exact pattern, else the longest
  `*` prefix), then its `baseUrl`. Anything else is a package and stays
  unresolved.
- `module`: module paths split on `separator` (`.` or `::`). Relative forms are
  anchored at the importing module: Python's leading dots (`leading_dots`) or
  words such as Rust's `self` and `super` (`relative_markers`, levels up), with
  `dir_modules` naming the files that own their directory (mod.rs). When no
  file under the anchor matches, the target is the anchor module's own file:
  its package file, the Rust 2018 `net.rs` beside `net/`, or a crate root.
  Absolute paths drop `strip_markers` (`crate`) and are matched by path suffix
  against `extensions` and `package_files`, dropping trailing segments that
  name items; a match whose root directory is itself a package is rejected. A
  lone module file (`os.py`, as opposed to `pkg/models.py`) only matches from
  a root the importer could have on its import path: the repo root, the
  importer's own directory or its ancestors, or a directory named in
  `source_roots`. So `scripts/os.py` is not what `import os` in `src/` means.
  `drop_leading` also tries without leading segments (an unknown crate name).
- `package`: the import names a directory under a module path read from a
  `module_files` entry, e.g. `go.mod: '^module\s+(\S+)'`.

An import of the importing file itself resolves to nothing. Editing a
`module_files` or `alias_files` entry (or a `tsconfig.*.json` beside it, which
an alias file may extend) re-resolves every import, as adding or deleting a
file does; other edits re-resolve only the edited file's imports.

Docstring rules: `body_first_string` takes the first string literal in the
definition's body (and the module's first statement for the file header), and
falls back to the leading comment.

Visibility is decided in this order: a `@visibility.<value>` capture, a
`@visibility` capture matched against `modifiers`, the `names` rules, the
`exported_by` rule for declarations that are not class-like members, the
enclosing interface or trait's visibility, then `default`.

## `tags.scm` captures

| Capture | Meaning |
| --- | --- |
| `@definition.<kind>` | The definition node; its rows are the symbol's line range |
| `@name` | The symbol name |
| `@parent` | Explicit parent name, for definitions not nested in their owner (Go methods) |
| `@visibility` | Modifier text, mapped through `visibility.modifiers` |
| `@visibility.<value>` | Sets visibility to `<value>` outright |
| `@signature` | The signature starts here instead of at `@name` |
| `@params` | The signature is the name followed by the text from here (functions assigned to variables) |
| `@body` | The signature ends where this node starts; the default is the definition's `body` field, else the end of the name's line |
| `@reference.call` | A call site; `@name` is the callee's name (for callers_of) |

Captures starting with `_` are helpers for predicates and are ignored.
References are matched by name only, like a text search restricted to call
sites; list the plain-call form first, then method calls (`obj.name()`).

Kinds in use: `class`, `interface`, `struct`, `enum`, `trait`, `impl`, `type`,
`function`, `method`, `constant`, `variable`, `module`, `namespace`, `macro`.

Rules the core applies to every language:

- When two patterns capture the same node, the earlier pattern wins, so put
  specific patterns first.
- A `function` whose nearest enclosing definition is a class, interface,
  struct, enum, trait or impl becomes a `method`.
- Definitions nested inside a function or method are local and are dropped.

## `imports.scm` captures

| Capture | Meaning |
| --- | --- |
| `@import` | A node whose text, with quotes stripped, is one import target |
| `@import.member` | A name imported from that target: the target becomes `@import` + `separator` + member, so `from pkg import models` targets `pkg.models` (the resolver falls back to `pkg` when `models` is not a module) and `use crate::t::{a, b}` targets `crate::t::a` and `crate::t::b` |

Only capture imports whose target is relative to the file: Rust's queries
match file-level `use` declarations only, because `use super::*` inside an
inline `mod tests` refers to the file itself.
