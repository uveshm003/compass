"""Stack detector edge cases the fixtures do not cover."""

from __future__ import annotations

from compass.stack import build_profile, render_text
from conftest import write


def test_poetry_multiple_constraint_dependencies(make_repo):
    root = make_repo(
        files={
            "pyproject.toml": (
                '[tool.poetry]\nname = "app"\n\n[tool.poetry.dependencies]\npython = "^3.11"\n'
                'django = "^5.0"\n'
                'numpy = [{version = "^1.26", python = ">=3.9"}, {version = "^1.24", python = "<3.9"}]\n'
                'requests = {version = "^2.31", extras = ["socks"]}\n'
            ),
        }
    )
    package = build_profile(root)["stacks"]["python"]["packages"][0]
    assert package["name"] == "app" and package["runner"] == "poetry"
    assert package["frameworks"] == {"django": "^5.0", "numpy": "^1.26", "requests": "^2.31"}


def test_yarn_and_npm_lockfiles_resolve_versions(make_repo):
    root = make_repo(
        files={
            "package.json": '{"name": "web", "dependencies": {"react": "^18.2.0", "@nestjs/core": "^10"}}',
            "yarn.lock": (
                '# yarn lockfile v1\n\nreact@^18.2.0:\n  version "18.3.1"\n\n'
                '"@nestjs/core@^10":\n  version "10.4.1"\n'
            ),
        }
    )
    package = build_profile(root)["stacks"]["node"]["packages"][0]
    assert package["package_manager"] == "yarn"
    assert package["frameworks"] == {"@nestjs/core": "10.4.1", "react": "18.3.1"}
    (root / "yarn.lock").unlink()
    write(root, "package-lock.json", '{"packages": {"node_modules/react": {"version": "18.2.0"}}}')
    package = build_profile(root)["stacks"]["node"]["packages"][0]
    assert package["package_manager"] == "npm" and package["frameworks"]["react"] == "18.2.0"


AZURE_DOTNET = """\
trigger:
  - main
pool:
  vmImage: windows-latest
stages:
  - stage: build
    jobs:
      - job: build
        steps:
          - task: DotNetCoreCLI@2
            inputs:
              command: restore
          - task: DotNetCoreCLI@2
            displayName: Unit tests
            inputs:
              command: test
              projects: "**/*Tests.csproj"
              arguments: --configuration Release
          - task: PowerShell@2
            inputs:
              targetType: inline
              script: ./build.ps1 -Target Lint
          - task: VSBuild@1
            inputs:
              solution: Gateway.sln
          - template: templates/pack.yml
"""

AZURE_TEMPLATE = """\
steps:
  - bash: |
      npm ci
      npm run build
  - task: Npm@1
    inputs:
      command: custom
      customCommand: run lint
  - task: Gradle@3
    inputs:
      tasks: check
"""


def test_azure_pipelines_scripts_and_tasks(make_repo):
    root = make_repo(
        files={
            "azure-pipelines.yml": AZURE_DOTNET,
            "eng/pipelines/templates/pack.yml": AZURE_TEMPLATE,
            ".azuredevops/pull_request_template.md": "Describe the change.\n",
            "pipelines/not-a-pipeline.yaml": "name: just data\nvalues: [1, 2]\n",
        }
    )
    azure = build_profile(root)["stacks"]["azure_pipelines"]
    assert azure["files"] == ["azure-pipelines.yml", "eng/pipelines/templates/pack.yml"]
    assert azure["commands"] == [
        "dotnet test **/*Tests.csproj --configuration Release",
        "./build.ps1 -Target Lint",
        "msbuild Gateway.sln",
        "npm run build",
        "npm run lint",
        "./gradlew check",
    ]


def test_github_actions_workflows_and_composite_actions(make_repo):
    root = make_repo(
        files={
            ".github/workflows/ci.yml": "on: push\njobs:\n  t:\n    steps:\n      - run: npm ci\n      - run: npm test\n",
            ".github/actions/lint/action.yml": "runs:\n  using: composite\n  steps:\n    - run: npx eslint .\n",
        }
    )
    github = build_profile(root)["stacks"]["github_actions"]
    assert github["files"] == [".github/workflows/ci.yml", ".github/actions/lint/action.yml"]
    assert github["commands"] == ["npm test", "npx eslint ."]


def test_gitlab_ci(make_repo):
    root = make_repo(files={".gitlab-ci.yml": "test:\n  script:\n    - pip install -e .\n    - pytest -q\n"})
    assert build_profile(root)["stacks"]["gitlab_ci"] == {"files": [".gitlab-ci.yml"], "commands": ["pytest -q"]}


def test_ci_text_rendering_covers_every_provider(make_repo):
    root = make_repo(
        files={
            "azure-pipelines.yml": "steps:\n  - script: make test\n",
            ".github/workflows/ci.yml": "jobs:\n  t:\n    steps:\n      - run: make lint\n",
        }
    )
    text = render_text(build_profile(root))
    assert "azure_pipelines:\n    run: make test\n    files: azure-pipelines.yml" in text
    assert "github_actions:\n    run: make lint\n    files: .github/workflows/ci.yml" in text


def test_broken_manifests_do_not_break_the_profile(make_repo):
    root = make_repo(files={"package.json": "{not json", "Cargo.toml": "[package\n", "go.mod": "module x\n"})
    profile = build_profile(root)
    assert "go" in profile["stacks"] and "node" not in profile["stacks"]
    render_text(profile)


SWIFT_MANIFEST = """\
// swift-tools-version: 5.7
import PackageDescription

let package = Package(
    name: "Kiosk",
    dependencies: [
        .package(url: "https://github.com/vapor/vapor", "4.89.0"..<"5.0.0"),
        .package(url: "git@github.com:Alamofire/Alamofire.git", branch: "main"),
        .package(path: "../Shared"),
        .package(id: "mona.LinkedList", exact: "1.2.0"),
    ],
    targets: [.executableTarget(name: "Kiosk"), .testTarget(name: "KioskTests")]
)
"""


def test_swiftpm_without_a_lockfile_keeps_declared_requirements(make_repo):
    root = make_repo(files={"app/Package.swift": SWIFT_MANIFEST, ".swift-format": "{}\n"})
    package = build_profile(root)["stacks"]["swiftpm"]["packages"][0]
    assert package["name"] == "Kiosk" and package["engines"] == {"swift": ">=5.7"}
    assert package["targets"] == ["Kiosk", "KioskTests"]
    assert package["frameworks"] == {"alamofire": "branch main", "vapor": ">=4.89.0"}
    assert package["dependencies"] == 4  # the local package and the registry one count too
    assert package["commands"] == {
        "build": "cd app && swift build", "test": "cd app && swift test",
        "format": "cd app && swift format lint --recursive .",
    }


def test_swiftpm_reads_package_resolved_format_1(make_repo):
    resolved = (
        '{"object": {"pins": [{"package": "Alamofire", "repositoryURL": "https://github.com/Alamofire/Alamofire.git",'
        ' "state": {"branch": null, "revision": "f455c2975872ccd2d9c81594c658af65716e9b9a", "version": "5.8.1"}},'
        ' {"package": "Vapor", "repositoryURL": "https://github.com/vapor/vapor",'
        ' "state": {"branch": "main", "revision": "0123456789abcdef", "version": null}}]}, "version": 1}\n'
    )
    root = make_repo(files={"Package.swift": SWIFT_MANIFEST, "Package.resolved": resolved})
    package = build_profile(root)["stacks"]["swiftpm"]["packages"][0]
    assert package["frameworks"] == {"alamofire": "5.8.1", "vapor": "branch main"}
    assert "Kiosk  [Package.swift]\n    package_manager: swiftpm\n    frameworks: alamofire 5.8.1, vapor branch main" \
        in render_text(build_profile(root))


def test_flutter_app_uses_flutter_commands_and_skips_sdk_packages(make_repo):
    root = make_repo(
        files={
            "pubspec.yaml": (
                "name: kiosk\nenvironment:\n  sdk: '>=3.4.0 <4.0.0'\n  flutter: '>=3.22.0'\n"
                "dependencies:\n  flutter:\n    sdk: flutter\n  flutter_riverpod: ^2.5.1\n"
                "dev_dependencies:\n  flutter_test:\n    sdk: flutter\n  flutter_lints: ^4.0.0\n"
            ),
            "pubspec.lock": (
                "packages:\n  flutter:\n    dependency: \"direct main\"\n    description: flutter\n"
                "    source: sdk\n    version: \"0.0.0\"\n  flutter_riverpod:\n    dependency: \"direct main\"\n"
                "    source: hosted\n    version: \"2.5.1\"\n"
            ),
            "lib/main.dart": "void main() {}\n",
        }
    )
    package = build_profile(root)["stacks"]["dart"]["packages"][0]
    assert package["package_manager"] == "flutter pub"
    assert package["engines"] == {"dart": ">=3.4.0 <4.0.0", "flutter": ">=3.22.0"}
    assert package["frameworks"] == {"flutter_riverpod": "2.5.1"}  # the SDK's 0.0.0 says nothing
    assert package["tools"] == {"flutter_lints": "^4.0.0"}  # not in the lock: the declared range
    assert package["dependencies"] == 2
    assert package["commands"] == {
        "test": "flutter test", "lint": "flutter analyze",
        "format": "dart format --output=none --set-exit-if-changed .",
    }


def test_pub_workspace_member_uses_the_root_lock(make_repo):
    root = make_repo(
        files={
            "pubspec.yaml": "name: _workspace\nenvironment:\n  sdk: ^3.6.0\nworkspace:\n  - packages/server\n",
            "pubspec.lock": "packages:\n  shelf:\n    source: hosted\n    version: \"1.4.2\"\n",
            "packages/server/pubspec.yaml": (
                "name: server\nresolution: workspace\nenvironment:\n  sdk: ^3.6.0\n"
                "dependencies:\n  shelf: ^1.4.0\n  common:\n    path: ../common\n"
            ),
            "packages/server/bin/server.dart": "void main() {}\n",
        }
    )
    packages = build_profile(root)["stacks"]["dart"]["packages"]
    server = next(p for p in packages if p["name"] == "server")
    assert server["lockfile"] == "pubspec.lock" and server["frameworks"] == {"shelf": "1.4.2"}
    assert server["commands"] == {  # no package:test dependency, so no test command
        "build": "cd packages/server && dart compile exe bin/server.dart",
        "lint": "cd packages/server && dart analyze",
        "format": "cd packages/server && dart format --output=none --set-exit-if-changed .",
    }
    assert "server  [packages/server/pubspec.yaml]\n    package_manager: dart pub\n    frameworks: shelf 1.4.2" \
        in render_text(build_profile(root))


def test_dotnet_central_versions_properties_and_legacy_projects(make_repo):
    root = make_repo(
        files={
            "Directory.Packages.props": (
                "<Project><PropertyGroup><ManagePackageVersionsCentrally>true</ManagePackageVersionsCentrally>"
                "<SerilogVersion>3.1.1</SerilogVersion></PropertyGroup><ItemGroup>"
                '<PackageVersion Include="Serilog" Version="$(SerilogVersion)" />'
                '<PackageVersion Include="xunit" Version="2.9.0" /></ItemGroup></Project>\n'
            ),
            "src/Api/Api.csproj": (
                '﻿<Project Sdk="Microsoft.NET.Sdk.Web"><PropertyGroup>'
                "<TargetFrameworks>net8.0;net48</TargetFrameworks><AssemblyName>Plant.Api</AssemblyName>"
                '</PropertyGroup><ItemGroup><PackageReference Include="Serilog" />'
                '<PackageReference Include="Newtonsoft.Json"><Version>13.0.3</Version></PackageReference>'
                "</ItemGroup></Project>\n"
            ),
            "src/Api.Tests/Api.Tests.fsproj": (
                '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup>'
                '<PackageReference Include="xunit" VersionOverride="2.8.1" /></ItemGroup></Project>\n'
            ),
            "legacy/Legacy.csproj": (
                '<?xml version="1.0" encoding="utf-8"?>\n<Project ToolsVersion="15.0" '
                'xmlns="http://schemas.microsoft.com/developer/msbuild/2003"><PropertyGroup>'
                "<TargetFrameworkVersion>v4.7.2</TargetFrameworkVersion></PropertyGroup></Project>\n"
            ),
            "legacy/packages.config": '<?xml version="1.0"?>\n<packages><package id="Dapper" version="2.1.35" /></packages>\n',
            "broken/Broken.csproj": "<Project><ItemGroup>\n",
        }
    )
    dotnet = build_profile(root)["stacks"]["dotnet"]
    assert "more_packages" not in dotnet  # an unreadable project is skipped, not counted as cut off
    projects = {p["path"]: p for p in dotnet["packages"]}
    assert sorted(projects) == ["legacy/Legacy.csproj", "src/Api.Tests/Api.Tests.fsproj", "src/Api/Api.csproj"]
    api = projects["src/Api/Api.csproj"]
    assert api["name"] == "Plant.Api" and api["msbuild_sdk"] == "Microsoft.NET.Sdk.Web"
    assert api["engines"] == {"target": "net8.0;net48"}
    assert api["frameworks"] == {"Newtonsoft.Json": "13.0.3", "Serilog": "3.1.1"}  # central, through a property
    # Without a solution, each project carries its own lint command; only test projects get `dotnet test`.
    assert api["commands"] == {
        "build": "dotnet build src/Api/Api.csproj", "lint": "dotnet format src/Api/Api.csproj --verify-no-changes",
    }
    tests = projects["src/Api.Tests/Api.Tests.fsproj"]
    assert tests["tools"] == {"xunit": "2.8.1"} and tests["commands"]["test"] == "dotnet test src/Api.Tests/Api.Tests.fsproj"
    legacy = projects["legacy/Legacy.csproj"]
    assert legacy["engines"] == {"target": "v4.7.2"} and legacy["frameworks"] == {"Dapper": "2.1.35"}
    assert "Plant.Api  [src/Api/Api.csproj]\n    frameworks: Newtonsoft.Json 13.0.3, Serilog 3.1.1" in render_text(
        build_profile(root)
    )


def test_cmake_presets_conan_cpm_and_vendored_projects(make_repo):
    root = make_repo(
        files={
            "CMakeLists.txt": (
                "cmake_minimum_required(VERSION 3.24...3.29)\n"
                "PROJECT(plant_core VERSION 2.0.1 LANGUAGES CXX)  # comment ( with a paren\n"
                "set(CMAKE_CXX_STANDARD 20)\n"
                "find_package(Boost 1.83 REQUIRED COMPONENTS system)\nfind_package(spdlog CONFIG REQUIRED)\n"
                "find_package(Threads REQUIRED)\n"
                'CPMAddPackage("gh:fmtlib/fmt#10.2.1")\n'
                "#[[ find_package(Qt6 6.5 REQUIRED) ]]\n"
                "add_subdirectory(lib)\ninclude(CTest)\n"
            ),
            "lib/CMakeLists.txt": "project(core_lib)\nfind_package(GTest 1.14 EXACT)\n",
            "third_party/zlib/CMakeLists.txt": "project(zlib VERSION 1.3)\nfind_package(OpenSSL)\n",
            "conanfile.txt": "[requires]\nspdlog/1.13.0\nboost/1.84.0\n\n[generators]\nCMakeDeps\n",
            "CMakePresets.json": (
                '{"version": 6, "configurePresets": [{"name": "base", "hidden": true}, {"name": "dev"}],'
                ' "buildPresets": [{"name": "dev", "configurePreset": "dev"}],'
                ' "testPresets": [{"name": "dev", "configurePreset": "dev"}]}'
            ),
        }
    )
    cmake = build_profile(root)["stacks"]["cmake"]
    assert [p["path"] for p in cmake["packages"]] == ["CMakeLists.txt"]  # lib/ is part of it, third_party/ vendored
    project = cmake["packages"][0]
    assert project["name"] == "plant_core" and project["version"] == "2.0.1" and project["languages"] == ["CXX"]
    assert project["package_manager"] == "conan" and project["engines"] == {"cmake": ">=3.24", "c++": "20"}
    # conan pins win over find_package minimums; EXACT stays exact; Threads is CMake's own; the
    # bracket comment hides Qt.
    assert project["frameworks"] == {"boost": "1.84.0", "fmt": "10.2.1", "googletest": "1.14", "spdlog": "1.13.0"}
    assert project["dependencies"] == 4
    assert project["commands"] == {"build": "cmake --preset dev && cmake --build --preset dev", "test": "ctest --preset dev"}


def test_cmake_without_a_project_call_in_a_subdirectory(make_repo):
    root = make_repo(
        files={
            "native/CMakeLists.txt": (
                "add_library(codec codec.c)\nset(CMAKE_EXPORT_COMPILE_COMMANDS ON)\nset(CMAKE_C_STANDARD 11)\n"
                "find_package(ZLIB 1.2.11 REQUIRED)\n"
            ),
            "native/vcpkg.json": '{"name": "codec", "dependencies": [{"name": "zlib", "version>=": "1.3.1"}]}',
            ".clang-tidy": "Checks: '-*,bugprone-*'\n",
        }
    )
    project = build_profile(root)["stacks"]["cmake"]["packages"][0]
    assert "name" not in project and project["package_manager"] == "vcpkg"
    assert project["engines"] == {"c": "11"} and project["frameworks"] == {"zlib": ">=1.3.1"}
    # No tests registered, so no test command; clang-tidy needs the exported compile commands.
    assert project["commands"] == {
        "build": "cd native && cmake -S . -B build && cmake --build build",
        "lint": "cd native && run-clang-tidy -p build",
    }


def test_maven_modules_inherit_from_their_parent_pom(make_repo):
    pom = '<project xmlns="http://maven.apache.org/POM/4.0.0"><modelVersion>4.0.0</modelVersion>{}</project>\n'
    root = make_repo(
        files={
            "mvnw": "#!/bin/sh\n",
            "pom.xml": pom.format(
                "<parent><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-parent</artifactId>"
                "<version>3.3.5</version></parent><groupId>com.example</groupId><artifactId>plant</artifactId>"
                "<version>2.1.0-SNAPSHOT</version><packaging>pom</packaging><modules><module>core</module></modules>"
                "<properties><java.version>17</java.version><guava.version>33.2.1-jre</guava.version></properties>"
                "<dependencyManagement><dependencies><dependency><groupId>com.google.guava</groupId>"
                "<artifactId>guava</artifactId><version>${guava.version}</version></dependency></dependencies>"
                "</dependencyManagement>"
            ),
            "core/pom.xml": pom.format(
                "<parent><groupId>com.example</groupId><artifactId>plant</artifactId><version>2.1.0-SNAPSHOT</version>"
                "</parent><artifactId>plant-core</artifactId><dependencies>"
                "<dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-web</artifactId>"
                "</dependency><dependency><groupId>com.google.guava</groupId><artifactId>guava</artifactId></dependency>"
                "<dependency><groupId>org.mockito</groupId><artifactId>mockito-core</artifactId><version>5.14.2</version>"
                "<scope>test</scope></dependency></dependencies>"
            ),
            "broken/pom.xml": "<project><dependencies>\n",
        }
    )
    packages = {p["path"]: p for p in build_profile(root)["stacks"]["maven"]["packages"]}
    assert sorted(packages) == ["core/pom.xml", "pom.xml"]  # an unparseable pom is skipped
    parent = packages["pom.xml"]
    assert parent["engines"] == {"java": "17"} and parent["modules"] == ["core"]
    assert parent["frameworks"] == {"spring-boot": "3.3.5"}
    assert parent["commands"] == {"build": "./mvnw package", "test": "./mvnw test"}
    core = packages["core/pom.xml"]
    # The module takes the parent's version, properties, managed versions and Spring Boot parent.
    assert core["name"] == "plant-core" and core["version"] == "2.1.0-SNAPSHOT" and core["engines"] == {"java": "17"}
    assert core["frameworks"] == {"guava": "33.2.1-jre", "spring-boot": "3.3.5"} and core["tools"] == {"mockito": "5.14.2"}
    assert core["commands"] == {"build": "./mvnw -pl core -am package", "test": "./mvnw -pl core -am test"}


def test_gradle_groovy_multi_project_without_a_wrapper(make_repo):
    root = make_repo(
        files={
            "settings.gradle": "rootProject.name = 'inventory'\ninclude 'api', ':core'\n",
            "build.gradle": (
                "plugins {\n    id 'java'\n    id 'org.springframework.boot' version '3.3.5'\n"
                "    id 'com.diffplug.spotless' version '6.25.0'\n}\n\njava {\n"
                "    sourceCompatibility = JavaVersion.VERSION_17\n}\n\ndependencies {\n"
                "    implementation 'org.springframework.boot:spring-boot-starter-web'\n"
                "    implementation platform('com.fasterxml.jackson:jackson-bom:2.18.2')\n"
                "    testImplementation 'org.junit.jupiter:junit-jupiter:5.10.2'\n}\n"
            ),
            "core/build.gradle": "plugins { id 'java-library' }\ndependencies {\n    api 'com.google.guava:guava:33.2.1-jre'\n}\n",
        }
    )
    packages = {p["path"]: p for p in build_profile(root)["stacks"]["gradle"]["packages"]}
    main = packages["build.gradle"]
    assert main["name"] == "inventory" and main["modules"] == ["api", "core"] and main["engines"] == {"java": "17"}
    # The Spring Boot plugin's version fills in the starter's; a platform() BOM counts with its version.
    assert main["frameworks"] == {"jackson": "2.18.2", "spring-boot": "3.3.5"}
    assert main["tools"] == {"junit": "5.10.2", "spotless": "6.25.0"}
    assert main["commands"] == {"build": "gradle build", "test": "gradle test", "lint": "gradle spotlessCheck"}
    core = packages["core/build.gradle"]
    assert core["name"] == "core" and core["frameworks"] == {"guava": "33.2.1-jre"}
    assert core["commands"] == {"build": "gradle :core:build", "test": "gradle :core:test"}
    text = render_text(build_profile(root))
    assert "inventory  [build.gradle]\n    frameworks: jackson 2.18.2, spring-boot 3.3.5" in text
