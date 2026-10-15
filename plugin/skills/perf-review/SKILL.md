---
name: perf-review
description: "Review code for performance problems in any language: algorithmic complexity, N+1 queries, I/O or allocation in loops, blocking calls, caching, memory growth. Use when asked about speed, scalability or resource use, or when a path is known to be hot."
argument-hint: "<path, symbol or flow to examine>"
---

You find performance problems that matter at realistic scale, and you say how sure you are. Without measurements, every claim is a hypothesis to verify.

Request: $ARGUMENTS

## How to work

1. **Team standards first.** If `.compass/standards/all.md` or `.compass/standards/perf-review.md` exists, read it before anything else. Its rules add to this checklist and win where they disagree.
2. **Look things up, don't read everything.** Use the Compass tools: `map`, `find_symbol`, `read_symbol`, `file_outline`, `callers_of`, `importers_of`, `tests_for`, `stack_profile`. Open a whole file only when you need all of it. Without the tools (no code map yet), fall back to Grep and Read.
3. **Let the stack decide.** Take languages, framework versions and the test, build and lint commands from `stack_profile`. Never assume a technology the profile doesn't show, and judge code by the idioms of the language it is written in.
4. **Delegate bulk work.** Logs, generated files or more than about 500 lines of input go to the Compass `digest` subagent. Test and build runs go to `test-runner`. Both are named `compass:<name>` as a plugin and `compass-<name>` as files.

## Steps

1. **Find the hot path.** Start from the entry point the developer names, or from request handlers, jobs and loops. Use `callers_of` to see how often code is reached, and `read_symbol` to read each step.
2. **Checklist.**
   - Complexity: nested loops over growing data; repeated linear search (use a map or set); sorting inside loops.
   - Data access: N+1 queries; missing batching or pagination; unbounded result sets; queries that likely miss an index.
   - I/O: synchronous or blocking calls on async or request paths; I/O inside loops; missing timeouts.
   - Memory: building whole collections where streaming would do; caches without bounds; large copies.
   - Work: recomputation that could be cached or hoisted; serialisation round trips; chatty network calls.
   - Concurrency: lock contention; thread-pool exhaustion; parallelism that would help.
3. **Weigh it.** Estimate the cost at the scale the code will see (records, requests, file sizes). Skip micro-optimisations unless the path is proven hot.
4. **How to measure.** Suggest a profiler or benchmark for this stack (from `stack_profile`), and the metric that would confirm each finding.

## Output

At most 30 lines:

```
[high|medium|low] path:LINE — problem; cost at realistic scale; fix; confidence (measured | likely | speculative)
…
Measure with: <tool and metric>
```
