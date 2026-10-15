""".NET: .csproj, .fsproj and .vbproj projects and the solutions that hold them.

Versions come from the project's packages.lock.json when it has one, else the
version the project asks for (central package management in
Directory.Packages.props included), else a legacy packages.config. The SDK
comes from global.json, and the target framework from the project or the
nearest Directory.Build.props. Both are reported as ``engines``, which the
session-start stack line shows the way it shows Node's.
"""


from __future__ import annotations

import posixpath
import re
import xml.etree.ElementTree as ET

from compass.stack import MAX_PACKAGES, StackRepo, compact, in_dir

PROJECT_SUFFIXES = (".csproj", ".fsproj", ".vbproj")
SOLUTION_SUFFIXES = (".sln", ".slnx")
FRAMEWORKS = {
    "AutoMapper", "Avalonia", "Azure.Messaging.ServiceBus", "Dapper", "FluentValidation",
    "Grpc.AspNetCore", "Grpc.Net.Client", "Hangfire.Core", "MassTransit", "MediatR",
    "Microsoft.Data.SqlClient", "Microsoft.Maui.Controls", "Microsoft.Orleans.Server",
    "Newtonsoft.Json", "Npgsql", "NServiceBus", "Polly", "Polly.Core", "Refit", "Serilog",
    "Serilog.AspNetCore", "StackExchange.Redis", "Swashbuckle.AspNetCore", "System.Reactive",
    "Xamarin.Forms",
}
FRAMEWORK_PREFIXES = (
    "Microsoft.AspNetCore.", "Microsoft.Azure.Functions.Worker", "Microsoft.EntityFrameworkCore",
    "Microsoft.Extensions.",
)
TOOLS = {
    "AutoFixture", "BenchmarkDotNet", "Bogus", "coverlet.collector", "coverlet.msbuild",
    "FluentAssertions", "Microsoft.NET.Test.Sdk", "Moq", "MSTest", "MSTest.TestAdapter",
    "MSTest.TestFramework", "NSubstitute", "NUnit", "NUnit3TestAdapter", "Roslynator.Analyzers",
    "Shouldly", "SonarAnalyzer.CSharp", "StyleCop.Analyzers", "Testcontainers", "Verify.Xunit",
    "xunit", "xunit.runner.visualstudio", "xunit.v3",
}
# A project referencing one of these is a test project, as `dotnet test` sees it.
TEST_PACKAGES = {"Microsoft.NET.Test.Sdk", "MSTest", "MSTest.TestFramework", "NUnit", "xunit", "xunit.v3"}
_PROPERTY = re.compile(r"\$\(([A-Za-z_][\w.]*)\)")


def detect(repo: StackRepo) -> dict | None:
    projects = sorted(
        {p for suffix in PROJECT_SUFFIXES for p in repo.find_suffix(suffix)},
        key=lambda p: (p.count("/"), p),
    )
    if not projects:
        return None
    sdk = _sdk_version(repo)
    entries = []
    solutions = sorted(
        {p for suffix in SOLUTION_SUFFIXES for p in repo.find_suffix(suffix)},
        key=lambda p: (p.count("/"), p),
    )
    for solution in solutions[:MAX_PACKAGES]:
        entries.append(compact({
            "path": solution,
            "engines": compact({"sdk": sdk}),
            "commands": {
                "build": f"dotnet build {solution}",
                "test": f"dotnet test {solution}",
                "lint": f"dotnet format {solution} --verify-no-changes",
            },
        }))
    budget = max(0, MAX_PACKAGES - len(entries))
    for path in projects[:budget]:
        project = _project(repo, path, sdk, lint=not solutions)
        if project:
            entries.append(project)
    if not entries:
        return None
    out: dict = {"packages": entries}
    skipped = max(0, len(solutions) - MAX_PACKAGES) + max(0, len(projects) - budget)
    if skipped:
        out["more_packages"] = skipped
    return out


def _project(repo: StackRepo, path: str, sdk: str | None, lint: bool) -> dict | None:
    root = _parse(repo, path)
    if root is None:
        return None
    base = posixpath.dirname(path)
    build_props = _parse(repo, _nearest(repo, base, "Directory.Build.props"))
    central = _parse(repo, _nearest(repo, base, "Directory.Packages.props"))
    properties = {**_properties(build_props), **_properties(central), **_properties(root)}

    declared: dict[str, str] = {}
    for scope in (build_props, root):
        for item in _items(scope, "PackageReference"):
            name = item.get("Include") or item.get("Update")
            if name:
                declared[name] = _expand(item.get("VersionOverride") or item.get("Version") or "", properties)
    central_versions = {
        (item.get("Include") or item.get("Update") or ""): _expand(item.get("Version") or "", properties)
        for item in _items(central, "PackageVersion")
    }
    for name, version in declared.items():
        if not version and central_versions.get(name):
            declared[name] = central_versions[name]
    lockfile = in_dir(base, "packages.lock.json")
    locked = _lock_versions(repo, lockfile)
    legacy = _packages_config(repo, in_dir(base, "packages.config"))
    for name, version in legacy.items():
        declared.setdefault(name, version)
    versions = {name: locked.get(name) or version for name, version in declared.items()}

    targets = properties.get("TargetFrameworks") or properties.get("TargetFramework") or properties.get(
        "TargetFrameworkVersion"
    )
    is_test = properties.get("IsTestProject", "").lower() == "true" or bool(TEST_PACKAGES & set(declared))
    commands = {"build": f"dotnet build {path}"}
    if is_test:
        commands["test"] = f"dotnet test {path}"
    if lint:
        commands["lint"] = f"dotnet format {path} --verify-no-changes"
    return compact({
        "path": path,
        "name": properties.get("AssemblyName") or posixpath.splitext(posixpath.basename(path))[0],
        "msbuild_sdk": root.get("Sdk"),
        "version": properties.get("Version"),
        "engines": compact({"sdk": sdk, "target": targets}),
        "lockfile": lockfile if locked else None,
        "frameworks": {name: versions[name] for name in sorted(versions) if _is_framework(name)},
        "tools": {name: versions[name] for name in sorted(versions) if name in TOOLS},
        "dependencies": len(declared),
        "commands": commands,
    })


def _is_framework(name: str) -> bool:
    return name in FRAMEWORKS or name.startswith(FRAMEWORK_PREFIXES)


def _sdk_version(repo: StackRepo) -> str | None:
    data = repo.read_json("global.json")
    sdk = data.get("sdk") if isinstance(data, dict) else None
    version = sdk.get("version") if isinstance(sdk, dict) else None
    return version if isinstance(version, str) else None


def _nearest(repo: StackRepo, directory: str, name: str) -> str | None:
    """``name`` in ``directory`` or the closest directory above it, as MSBuild finds it."""
    while True:
        candidate = in_dir(directory, name)
        if repo.exists(candidate):
            return candidate
        if not directory:
            return None
        directory = posixpath.dirname(directory)


def _parse(repo: StackRepo, path: str | None) -> ET.Element | None:
    text = repo.read_text(path) if path else None
    if text is None:
        return None
    try:
        return ET.fromstring(text.lstrip("﻿"))
    except ET.ParseError:
        return None


def _local(tag: str) -> str:
    """``{http://schemas.microsoft.com/developer/msbuild/2003}Version`` -> ``Version``."""
    return tag.rsplit("}", 1)[-1]


def _items(root: ET.Element | None, kind: str) -> list[ET.Element]:
    if root is None:
        return []
    found = []
    for element in root.iter():
        if _local(element.tag) == kind:
            # `<PackageReference Include="x"><Version>1.0</Version></PackageReference>`
            for child in element:
                if _local(child.tag) in ("Version", "VersionOverride") and child.text and _local(child.tag) not in element.attrib:
                    element.set(_local(child.tag), child.text.strip())
            found.append(element)
    return found


def _properties(root: ET.Element | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if root is None:
        return out
    for group in root.iter():
        if _local(group.tag) != "PropertyGroup" or group.get("Condition"):
            continue
        for prop in group:
            if prop.text and prop.text.strip():
                out[_local(prop.tag)] = prop.text.strip()
    return out


def _expand(value: str, properties: dict[str, str]) -> str:
    """``$(XunitVersion)`` from the properties MSBuild would have seen; anything
    else stays as written."""
    return _PROPERTY.sub(lambda m: properties.get(m.group(1), m.group(0)), value)


def _lock_versions(repo: StackRepo, path: str) -> dict[str, str]:
    data = repo.read_json(path)
    targets = data.get("dependencies") if isinstance(data, dict) else None
    out: dict[str, str] = {}
    if not isinstance(targets, dict):
        return out
    for target in sorted(targets):
        packages = targets[target]
        if not isinstance(packages, dict):
            continue
        for name, entry in packages.items():
            if isinstance(entry, dict) and isinstance(entry.get("resolved"), str):
                out.setdefault(name, entry["resolved"])
    return out


def _packages_config(repo: StackRepo, path: str) -> dict[str, str]:
    """A pre-SDK project's packages.config: ``<package id="x" version="1.0" />``."""
    root = _parse(repo, path)
    if root is None:
        return {}
    return {
        element.get("id", ""): element.get("version", "")
        for element in root.iter()
        if _local(element.tag) == "package" and element.get("id")
    }
