"""CMake: CMakeLists.txt projects, with versions from vcpkg.json or a conanfile."""

from __future__ import annotations

import posixpath
import re

from compass.stack import MAX_PACKAGES, StackRepo, compact, in_dir, run_in

# Libraries worth naming at session start, by canonical (lowercase) name.
FRAMEWORKS = {
    "abseil", "asio", "benchmark", "boost", "catch2", "cli11", "curl", "doctest", "eigen", "fmt",
    "gflags", "glog", "googletest", "grpc", "nlohmann_json", "opencv", "openssl", "poco", "protobuf",
    "pybind11", "qt", "range-v3", "sdl2", "spdlog", "sqlite3", "tbb", "vulkan", "zlib",
}
# Other spellings of the same library, as find_package, vcpkg and conan write them.
ALIASES = {
    "absl": "abseil", "gtest": "googletest", "gmock": "googletest", "eigen3": "eigen", "qt5": "qt", "qt6": "qt",
    "nlohmann-json": "nlohmann_json", "sqlite": "sqlite3", "range_v3": "range-v3", "onetbb": "tbb",
}
# find_package modules that ship with CMake or the platform, not third-party libraries.
BUILTIN = {"threads", "pkgconfig", "git", "python", "python3", "perl", "doxygen"}
# Directories holding other people's projects.
VENDORED = {"third_party", "thirdparty", "3rdparty", "external", "extern", "vendor", "deps", "_deps"}

# Quoted arguments first, so a `#` inside one ("gh:fmtlib/fmt#10.2.1") is not a comment.
_COMMENT = re.compile(r'("(?:[^"\\]|\\.)*")|#\[(=*)\[.*?\]\2\]|#[^\n]*', re.DOTALL)
_ARG = re.compile(r'"[^"]*"|[^\s"]+')
_VERSION = re.compile(r"^v?\d+(\.\d+)*$")


def detect(repo: StackRepo) -> dict | None:
    lists = [p for p in repo.find("CMakeLists.txt") if not _vendored(p)]
    if not lists:
        return None
    texts = {p: _strip_comments(repo.read_text(p) or "") for p in lists}
    roots = [p for p in lists if _calls(texts[p], "project")] or lists[:1]
    projects: list[str] = []
    for path in roots:  # shallowest first: a project inside another is part of it
        base = posixpath.dirname(path)
        if not any(_inside(base, posixpath.dirname(p)) for p in projects):
            projects.append(path)
    packages = [_project(repo, path, texts) for path in projects[:MAX_PACKAGES]]
    out: dict = {"packages": [p for p in packages if p]}
    if len(projects) > MAX_PACKAGES:
        out["more_packages"] = len(projects) - MAX_PACKAGES
    return out if out["packages"] else None


def _project(repo: StackRepo, path: str, texts: dict[str, str]) -> dict | None:
    base = posixpath.dirname(path)
    text = texts[path]
    mine = [texts[p] for p in sorted(texts) if _inside(posixpath.dirname(p), base)]
    everything = "\n".join(mine)

    name = version = None
    languages: list[str] = []
    for args in _calls(text, "project")[:1]:
        name = args[0] if args and "${" not in args[0] else None
        keyword = None
        for arg in args[1:]:
            if arg in ("VERSION", "LANGUAGES", "DESCRIPTION", "HOMEPAGE_URL"):
                keyword = arg
            elif keyword == "VERSION" and _VERSION.match(arg):
                version = arg
            elif keyword in ("LANGUAGES", None):
                languages.append(arg)

    engines: dict[str, str] = {}
    for args in _calls(text, "cmake_minimum_required")[:1]:
        if len(args) >= 2 and args[0] == "VERSION":
            engines["cmake"] = ">=" + args[1].split("...")[0]
    for language, variable in (("c++", "CMAKE_CXX_STANDARD"), ("c", "CMAKE_C_STANDARD")):
        for args in _calls(everything, "set"):
            if len(args) >= 2 and args[0] == variable and args[1].isdigit():
                engines[language] = args[1]
                break

    declared = _cmake_dependencies(everything)
    manager, pinned = _package_manager(repo, base)
    versions = dict(declared)
    for dep, pin in pinned.items():
        _note(versions, dep, pin)
    frameworks = {n: v for n, v in sorted(versions.items()) if n in FRAMEWORKS}
    return compact(
        {
            "path": path,
            "name": name,
            "version": version,
            "languages": languages,
            "package_manager": manager,
            "engines": engines,
            "frameworks": frameworks,
            "dependencies": len(versions),
            "commands": _commands(repo, base, everything),
        }
    )


def _cmake_dependencies(text: str) -> dict[str, str]:
    """Libraries the build asks for, with the version it asks for ("" when none)."""
    found: dict[str, str] = {}
    for args in _calls(text, "find_package"):
        if not args:
            continue
        name = _canonical(args[0])
        if name in BUILTIN:
            continue
        wanted = args[1] if len(args) > 1 and _VERSION.match(args[1].split("...")[0]) else ""
        exact = "EXACT" in args[2:]
        _note(found, name, (wanted if exact else ">=" + wanted.split("...")[0]) if wanted else "")
    for args in _calls(text, "FetchContent_Declare"):
        if args:
            tag = _keyword(args, "GIT_TAG")
            _note(found, _canonical(args[0]), tag if tag and _VERSION.match(tag) else "")
    for args in _calls(text, "CPMAddPackage"):
        if len(args) == 1:  # CPMAddPackage("gh:fmtlib/fmt#10.2.1") or "fmt@10.2.1"
            m = re.match(r"^(?:\w+:)?(?:[^/#@]+/)?([^/#@]+)[#@](.+)$", args[0])
            if m:
                _note(found, _canonical(m.group(1)), m.group(2) if _VERSION.match(m.group(2)) else "")
        elif _keyword(args, "NAME"):
            _note(found, _canonical(_keyword(args, "NAME") or ""), _keyword(args, "VERSION") or "")
    return found


def _package_manager(repo: StackRepo, base: str) -> tuple[str | None, dict[str, str]]:
    """vcpkg or conan, and the versions they pin (exact where they say so)."""
    for directory in dict.fromkeys([base, ""]):
        manifest = repo.read_json(in_dir(directory, "vcpkg.json"))
        if isinstance(manifest, dict):
            pins: dict[str, str] = {}
            for dep in manifest.get("dependencies") or []:
                name = dep if isinstance(dep, str) else dep.get("name") if isinstance(dep, dict) else None
                if isinstance(name, str):
                    minimum = dep.get("version>=") if isinstance(dep, dict) else None
                    pins[_canonical(name)] = f">={minimum}" if isinstance(minimum, str) else ""
            for override in manifest.get("overrides") or []:
                if isinstance(override, dict) and isinstance(override.get("name"), str):
                    exact = override.get("version") or override.get("version-semver") or override.get("version-string")
                    if isinstance(exact, str):
                        pins[_canonical(override["name"])] = exact
            return "vcpkg", pins
        for conanfile in ("conanfile.txt", "conanfile.py"):
            text = repo.read_text(in_dir(directory, conanfile))
            if text is not None:
                pins = {}
                for name, version in re.findall(r"""^\s*["']?([A-Za-z0-9_.+-]+)/([^@"'\s,\]]+)""", text, re.MULTILINE):
                    pins[_canonical(name)] = version
                for name, version in re.findall(r"""requires\(\s*["']([A-Za-z0-9_.+-]+)/([^@"'\s]+)""", text):
                    pins[_canonical(name)] = version
                return "conan", pins
    return None, {}


def _commands(repo: StackRepo, base: str, text: str) -> dict[str, str]:
    tests = any(_calls(text, c) for c in ("enable_testing", "add_test", "gtest_discover_tests", "catch_discover_tests"))
    tests = tests or any(args and args[0] == "CTest" for args in _calls(text, "include"))
    presets = repo.read_json(in_dir(base, "CMakePresets.json"))
    if isinstance(presets, dict):
        configure = _first_preset(presets, "configurePresets")
        build = _first_preset(presets, "buildPresets")
        if configure and build:
            commands = {"build": run_in(base, f"cmake --preset {configure} && cmake --build --preset {build}")}
            test = _first_preset(presets, "testPresets")
            if tests and test:
                commands["test"] = run_in(base, f"ctest --preset {test}")
            return commands
    commands = {"build": run_in(base, "cmake -S . -B build && cmake --build build")}
    if tests:
        commands["test"] = run_in(base, "ctest --test-dir build")
    exports = "CMAKE_EXPORT_COMPILE_COMMANDS" in text
    if exports and (repo.exists(in_dir(base, ".clang-tidy")) or repo.exists(".clang-tidy")):
        commands["lint"] = run_in(base, "run-clang-tidy -p build")
    return commands


def _first_preset(presets: dict, key: str) -> str | None:
    for preset in presets.get(key) or []:
        if isinstance(preset, dict) and isinstance(preset.get("name"), str) and not preset.get("hidden"):
            return preset["name"]
    return None


def _calls(text: str, command: str) -> list[list[str]]:
    """The arguments of every call to ``command`` (CMake commands ignore case)."""
    out = []
    for m in re.finditer(rf"(?<![\w$]){re.escape(command)}\s*\(([^()]*)\)", text, re.IGNORECASE):
        out.append([a.strip('"') for a in _ARG.findall(m.group(1))])
    return out


def _keyword(args: list[str], keyword: str) -> str | None:
    for i, arg in enumerate(args[:-1]):
        if arg == keyword:
            return args[i + 1]
    return None


def _note(found: dict[str, str], name: str, version: str) -> None:
    if name and (version or name not in found):
        found[name] = version


def _canonical(name: str) -> str:
    lowered = name.lower()
    return ALIASES.get(lowered, lowered)


def _strip_comments(text: str) -> str:
    return _COMMENT.sub(lambda m: m.group(1) or "", text)


def _vendored(path: str) -> bool:
    return any(part in VENDORED for part in path.split("/")[:-1])


def _inside(directory: str, root: str) -> bool:
    return root == "" or directory == root or directory.startswith(root + "/")
