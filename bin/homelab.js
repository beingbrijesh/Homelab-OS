#!/usr/bin/env node
"use strict";

const { spawnSync } = require("child_process");
const path = require("path");
const readline = require("readline");

const PKG_ROOT = path.resolve(__dirname, "..");

function findPython() {
  const candidates =
    process.platform === "win32"
      ? [
          ["py", ["-3"]],
          ["python", []],
          ["python3", []],
        ]
      : [
          ["python3", []],
          ["python", []],
        ];

  for (const [cmd, prefix] of candidates) {
    const res = spawnSync(
      cmd,
      [...prefix, "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}'); sys.exit(0 if sys.version_info >= (3, 9) else 1)"],
      { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }
    );
    if (res.status === 0) {
      return { cmd, prefix, version: (res.stdout || "").trim() };
    }
  }
  return null;
}

function commandExists(cmd) {
  const checker = process.platform === "win32" ? "where" : "which";
  return spawnSync(checker, [cmd], { stdio: "ignore" }).status === 0;
}

function promptYesNo(question) {
  return new Promise((resolve) => {
    if (!process.stdin.isTTY) {
      resolve(false);
      return;
    }
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    rl.question(`${question} [Y/n] `, (ans) => {
      rl.close();
      const norm = ans.trim().toLowerCase();
      resolve(norm === "" || norm === "y" || norm === "yes");
    });
  });
}

function getPythonInstallCommands() {
  const isRoot = typeof process.getuid === "function" && process.getuid() === 0;
  const withSudo = (cmd, args) => (isRoot || !commandExists("sudo") ? [cmd, args] : ["sudo", [cmd, ...args]]);

  if (process.platform === "linux") {
    if (commandExists("apt-get")) {
      return [
        withSudo("apt-get", ["update"]),
        withSudo("apt-get", ["install", "-y", "python3", "python3-venv", "python3-pip"]),
      ];
    }
    if (commandExists("dnf")) {
      return [withSudo("dnf", ["install", "-y", "python3", "python3-pip"])];
    }
    if (commandExists("yum")) {
      return [withSudo("yum", ["install", "-y", "python3"])];
    }
    if (commandExists("pacman")) {
      return [withSudo("pacman", ["-S", "--noconfirm", "python"])];
    }
    if (commandExists("apk")) {
      return [withSudo("apk", ["add", "--no-cache", "python3"])];
    }
  } else if (process.platform === "darwin") {
    if (commandExists("brew")) {
      return [["brew", ["install", "python@3.12"]]];
    }
  } else if (process.platform === "win32") {
    if (commandExists("winget")) {
      return [[
        "winget",
        ["install", "--id", "Python.Python.3.12", "-e", "--accept-source-agreements", "--accept-package-agreements"],
      ]];
    }
    if (commandExists("scoop")) {
      return [["scoop", ["install", "python"]]];
    }
    if (commandExists("choco")) {
      return [["choco", ["install", "python", "-y"]]];
    }
  }
  return [];
}

async function ensurePythonFirst(args) {
  const existing = findPython();
  if (existing) {
    return existing;
  }

  console.error("[MISSING] Python 3.9+ is required by the Homelab OS CLI before setup can continue.");
  if (args.includes("--no-install-deps")) {
    console.error("Aborted (--no-install-deps). Install Python 3.9+ and re-run.");
    process.exit(1);
  }

  const autoYes = args.includes("-y") || args.includes("--yes");
  if (!autoYes) {
    const confirmed = await promptYesNo("Install Python 3 automatically now?");
    if (!confirmed) {
      console.error("Aborted: Python 3.9+ must be installed first.");
      process.exit(1);
    }
  }

  const plan = getPythonInstallCommands();
  if (plan.length === 0) {
    console.error("No supported package manager found to auto-install Python 3. Please install Python 3.9+ manually.");
    process.exit(1);
  }

  for (const [cmd, cmdArgs] of plan) {
    console.log(`-> Running: ${cmd} ${cmdArgs.join(" ")}`);
    spawnSync(cmd, cmdArgs, { stdio: "inherit" });
  }

  const verified = findPython();
  if (!verified) {
    console.error("Python 3.9+ is still not available in PATH after install. Open a new terminal and retry.");
    process.exit(1);
  }
  return verified;
}

async function main() {
  let args = process.argv.slice(2);
  // Support `npx homelab-os` or `npx homelab-os -y --start` directly defaulting to `init`
  if (
    args.length === 0 ||
    (args[0].startsWith("-") && !["-h", "--help", "--version"].includes(args[0]))
  ) {
    args = ["init", ...args];
  }

  const py = await ensurePythonFirst(args);

  const env = { ...process.env };
  env.HOMELAB_STACK_SRC = PKG_ROOT;
  env.PYTHONPATH = env.PYTHONPATH
    ? `${PKG_ROOT}${path.delimiter}${env.PYTHONPATH}`
    : PKG_ROOT;

  const res = spawnSync(py.cmd, [...py.prefix, "-m", "homelab_os", ...args], {
    stdio: "inherit",
    env,
  });

  process.exit(res.status === null ? 1 : res.status);
}

main();
