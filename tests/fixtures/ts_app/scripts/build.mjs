#!/usr/bin/env node
// Build helper used by CI.
import { build } from "vite";

async function main() {
  await build();
}

main();
