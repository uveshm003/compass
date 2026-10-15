#!/usr/bin/env node
// The npx entry point for Compass (IN-12). It holds no logic of its own:
// find uv (or install it, with consent), install the compass CLI of this
// package's version with `uv tool install`, then hand every argument to
// `compass install` (or `compass <command>` for upgrade, doctor, uninstall).
//
//   npx compass-cc install [--scope …] [--mode …] [--yes] …
//   npx compass-cc install --source git+https://dev.azure.com/<org>/<project>/_git/<repo>
//
// Plain Node with no dependencies; runs in PowerShell, cmd and POSIX shells.

"use strict";

const { spawnSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");
const readline = require("readline");

const VERSION = require("../package.json").version;
const WINDOWS = process.platform === "win32";
const COMMANDS = new Set(["install", "upgrade", "doctor", "uninstall"]);

function log(line) {
  process.stdout.write(line + "\n");
}

function fail(line) {
  process.stderr.write("compass-cc: " + line + "\n");
  process.exit(1);
}

function run(command, args, options = {}) {
  // shell: false everywhere, so no argument is ever re-parsed by a shell.
  return spawnSync(command, args, { stdio: "inherit", shell: false, ...options });
}

function onPath(name) {
  const exts = WINDOWS ? (process.env.PATHEXT || ".EXE;.CMD;.BAT").split(";") : [""];
  for (const dir of (process.env.PATH || "").split(path.delimiter)) {
    if (!dir) continue;
    for (const ext of exts) {
      const candidate = path.join(dir, name + ext.toLowerCase());
      const upper = path.join(dir, name + ext);
      for (const file of [candidate, upper]) {
        try {
          if (fs.statSync(file).isFile()) return file;
        } catch (_) {
          // not here
        }
      }
    }
  }
  return null;
}

function findUv() {
  const found = onPath("uv");
  if (found) return found;
  const exe = WINDOWS ? "uv.exe" : "uv";
  for (const dir of [path.join(os.homedir(), ".local", "bin"), path.join(os.homedir(), ".cargo", "bin")]) {
    const file = path.join(dir, exe);
    if (fs.existsSync(file)) return file;
  }
  return null;
}

function ask(question) {
  if (!process.stdin.isTTY) return Promise.resolve("");
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  return new Promise((resolve) => rl.question(question, (answer) => { rl.close(); resolve(answer); }));
}

async function installUv(yes) {
  const answer = yes ? "y" : await ask("compass-cc: uv is not installed. Install it with uv's official installer? [Y/n] ");
  if (answer.trim() && !answer.trim().toLowerCase().startsWith("y")) {
    fail("uv is needed for the compass CLI; see https://docs.astral.sh/uv/ to install it, then run this again");
  }
  const result = WINDOWS
    ? run("powershell", ["-NoProfile", "-ExecutionPolicy", "ByPass", "-Command", "irm https://astral.sh/uv/install.ps1 | iex"])
    : run("sh", ["-c", "curl -LsSf https://astral.sh/uv/install.sh | sh"]);
  if (result.status !== 0) fail("installing uv failed");
  const uv = findUv();
  if (!uv) fail("uv was installed but cannot be found; open a new terminal and run this again");
  return uv;
}

function takeOption(args, name) {
  const i = args.indexOf(name);
  if (i === -1) return null;
  const value = args[i + 1];
  if (value === undefined) fail(`${name} needs a value`);
  args.splice(i, 2);
  return value;
}

async function main() {
  const args = process.argv.slice(2);
  if (args.includes("--version")) {
    log(`compass-cc ${VERSION}`);
    return;
  }
  const command = COMMANDS.has(args[0]) ? args.shift() : "install";
  const yes = args.includes("--yes") || args.includes("-y");
  const dryRun = args.includes("--dry-run");
  // --source is the wrapper's own option for install: where uv gets the CLI.
  const source = command === "install" ? takeOption(args, "--source") : null;

  let compass = onPath("compass");
  if (command === "install") {
    let uv = findUv();
    if (!uv) {
      if (dryRun) fail("uv is not installed; a dry run installs nothing, so install uv first");
      uv = await installUv(yes);
    }
    const spec = source || `compass==${VERSION}`;
    log(`compass-cc ${VERSION}: installing the compass CLI (${spec}) with uv`);
    if (!dryRun) {
      const result = run(uv, ["tool", "install", "--force", "--compile-bytecode", spec]);
      if (result.status !== 0) fail(`\`uv tool install ${spec}\` failed`);
    }
    compass = onPath("compass");
    if (!compass) {
      run(uv, ["tool", "update-shell"]);
      const exe = WINDOWS ? "compass.exe" : "compass";
      const fallback = path.join(os.homedir(), ".local", "bin", exe);
      compass = fs.existsSync(fallback) ? fallback : null;
      log("compass-cc: added uv's tool folder to PATH; open a new terminal (and restart your IDE) before starting Claude Code");
    }
    if (!compass && dryRun) {
      log("compass-cc: dry run: would now run `compass install --skip-cli " + args.join(" ") + "`");
      return;
    }
    if (!compass) fail("the compass CLI is not on PATH; open a new terminal and run `compass install`");
    args.unshift("--skip-cli");
  }
  if (!compass) fail("the compass CLI is not installed; run `npx compass-cc install` first");
  const result = run(compass, [command, ...args]);
  process.exit(result.status === null ? 1 : result.status);
}

main().catch((error) => fail(error && error.message ? error.message : String(error)));
