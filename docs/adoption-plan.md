# Compass adoption plan: nothing to learn


Oct 16, 2026 · @Uvesh · Status: **proposed**, for the owner's review (decisions D14 to D17)

The Proposal names adoption as the biggest risk: "If the gates feel slow or preachy, developers will bypass or disable them." There is a second way to lose developers, and it comes before any of that: **if using Compass means learning commands, concepts and docs first, most developers never start, and the rest drift off.** This plan makes Compass something a developer installs once and then simply works with, with nothing to learn.

The work items carry proposed IDs **UX-01 to UX-16**. They move into the Requirements Spec, as a new component C11, once the owner approves this plan.

## 1. The problem, measured

What a developer meets with Compass 0.3.0:

| | Today |
| --- | --- |
| CLI commands in `compass --help` | 28, of which a developer needs about 3 |
| Commands in Claude Code | 4 (`/compass:task`, `/compass:approve`, `/compass:accept`, `/compass:doctor`), 11 skills, and the `!quick` prefix |
| Concepts | task ids, four anchor kinds, the manifest, accepting, specs and approval, ask and strict modes, three subagents, seven modules in `config.yaml` |
| Moments that stop work until you know a command | **2.** A large task's plan holds every edit until `/compass:approve`. A commit is refused while review tags remain, until `/compass:accept` (or `git commit --no-verify`) |
| Docs | setup guide 225 lines, user guide 547, cheat sheet 179 |
| Setup | one command per machine; per repository, `compass init` or `compass install` in a terminal; a restart; PATH problems show up as hook errors |

Two facts shape the plan:

1. **The value needs none of it.** Most of the saving comes from Tier 0, the code map, and from delegation. Both work with no command, no concept and no change to how a developer works.
2. **A developer who learned nothing gets stuck in exactly two places**, the plan approval and the commit refusal. Everywhere else, Compass degrades gracefully: the prompt gate only makes Claude ask a question, and a developer who ignores tags and manifests loses nothing until they commit.

So the plan does not try to teach better. It removes the need to learn: the two stopping points become plain replies in the conversation, and everything else becomes optional.

## 2. The goal, and how we will know

**Goal: install once, then just talk to Claude.** After this plan, the whole manual a developer needs fits in five lines:

> Install: one command, once. Then work as usual. You may see three things:
> 1. Claude asks one question before changing code. Answer it.
> 2. Claude shows a plan for a big change. Reply **approve** when it's right.
> 3. Claude lists what it changed. Read it, and reply **accept** before you commit.
>
> Lost? Type `/compass`.

| Measure | Today | Target | Measured by |
| --- | --- | --- | --- |
| Steps to a working session on a new machine | one command and a restart, more when PATH goes wrong | one command and a restart | `tests/e2e/check_install.py` |
| Steps to switch Compass on in another repository | `compass init` in a terminal | say "switch Compass on here" | real session |
| Commands a developer must know in a normal week | 2, plus the `--no-verify` escape | **0** | the quick start names no required command |
| Docs to read before the first task | 225 to 547 lines | one page | `docs/quick-start.md` |
| Stuck moments: a hold or refusal the developer could not get past from what was on screen | not measured | 0 | friction telemetry (UX-16) and the week-1 check-in |
| Pilot developers with Compass still on, weeks 4 and 8 of the Compass weeks | not measured | at least 80% | telemetry: sessions with Compass on, per developer per week |
| Share of prompts with `!quick` | target exists | under 20% | `.compass/logs/gate.jsonl` |
| Commits that carried review tags anyway (`--no-verify`) | not measured | under 5% of commits in Compass tasks | post-commit check (UX-16) |

## 3. Principles

1. **Nothing to learn by default.** Value first, with no commands. Every command stays, for those who want it, but none is required.
2. **Say it, don't type it.** Every decision a developer makes, approving a plan or accepting changes, can be a plain reply in the conversation.
3. **Tell at the moment, not up front.** When Compass needs something from the developer, its message says what to reply, in words. No manual to read first.
4. **One door.** `/compass` in Claude Code and `compass` in a terminal show where things stand and what to do next.
5. **Fix, don't explain.** `doctor` repairs what it safely can; Compass repairs its own files.
6. **Start small, grow by choice.** A team can begin with only the parts that never hold work back, and switch on the rest when it wants them.
7. **The invariants hold** (CLAUDE.md): never turn a prompt away, fail open, no network in hooks, and approval stays the developer's act.

## 4. Work items

Effort is in developer-days, including tests and docs.

### A. Say it, don't type it: the two stopping points

| ID | Item | Effort |
| --- | --- | --- |
| UX-04 | **Approve a plan by replying "approve".** While a large task's spec waits, a short reply such as "approve", "approved" or "approve the plan" approves it, exactly as `/compass:approve` does: the approver is git `user.name`, with the time, written to `state.json` and the spec's front matter. The developer sees one confirmation line, and Claude is told to go ahead. `/compass:approve` keeps working. | 1.5 |
| UX-05 | **Accept changes by replying "accept".** While the active task has review tags, "accept" (or "accept T3") runs what `compass accept` runs: tags stripped, manifest archived. The confirmation names the archived manifest, which keeps every note. | 1 |
| UX-06 | **No surprise at commit.** (a) When the developer asks Claude to commit while tags are still open, the prompt hook tells Claude to show the manifest and ask for "accept" first. (b) The pre-commit refusal's first line says what to do in one sentence, and is checked in the git panes of VS Code, JetBrains IDEs and Visual Studio, where hook output is often cut short. | 1 |

**Why a typed reply is safe as approval (decision D14).** It reaches Compass through UserPromptSubmit, which carries only what the developer typed. Claude cannot produce a prompt. Claude Code's own messages, such as background-agent notifications, are already recognised and ignored (the `notice` kind, Oct 16). The approval is still written by Compass's hook, never by Claude. `state.json` stays protected from Claude's edits. Only narrow phrases count, and only while something is waiting.

### B. One door

| ID | Item | Effort |
| --- | --- | --- |
| UX-07 | **`/compass` and `compass status`.** One screen: the active task, files changed and tags, whether a plan waits, the manifest, **what to do next**, and the things you can say. A bare `compass` prints this instead of the usage text. The command is model-invocable, so "what is Compass doing?" works too. | 1.5 |
| UX-08 | **A short `compass --help`.** The everyday commands first (`install`, `status`, `doctor`, `upgrade`, `uninstall`, `report`); everything else under `compass help --all`. `hook`, `mcp`, `update`, `check-anchors`, `enrich` and the query twins leave the default list. Names and behaviour stay the same, so scripts and hooks are unaffected. | 0.5 |
| UX-09 | **Skills by asking, not by name.** The eleven skills are already model-invocable. Check in real sessions that a plain request picks each one ("review my changes", "what breaks if I rename this?", "write the PR description"), and tune the descriptions that don't trigger. The docs lead with the request, not the slash command. | 1.5 |

### C. Tell at the moment

| ID | Item | Effort |
| --- | --- | --- |
| UX-10 | **A one-time welcome**, per developer and repository: three lines in the first session saying what changes, the two replies, and `/compass`. | 0.5 |
| UX-11 | **Every message that asks the developer to act says what to reply.** Audit the prompt gate's notice, the spec instructions and reminder, the Stop summary, the pre-commit refusal, `doctor` and the installer. Today, for example, a waiting plan says "until the developer runs /compass:approve T3". A test asserts that each blocking message offers a plain reply. | 1 |

### D. Setup with nothing to learn

| ID | Item | Effort |
| --- | --- | --- |
| UX-01 | **Switch a repository on by asking.** A model-invocable `/compass:setup` runs `compass init` for the current repository, so with a user-scope install a developer says "switch Compass on here". Optionally (decision D15), SessionStart in a git repository without `.compass/` shows a one-time line offering it; "not here" stops it for that repository. | 1.5 |
| UX-02 | **A teammate without the tool gets one clear line, not hook errors.** When a repository carries a project-scope install but `compass` is not on PATH, every hook fails today with a generic error notice. Find out whether the hook command can carry a portable fallback that prints the one install command, on Windows and POSIX, without putting logic in the plugin. | 1 |
| UX-03 | **Fix, don't explain.** `compass doctor --fix` (and `/compass:doctor fix`) rewrites outdated git hooks, rebuilds a broken or stale index, and prints the exact command for what it must not change itself, such as a second `compass` on PATH. SessionStart rewrites Compass's own outdated git hooks without asking. | 1.5 |

### E. Start small

| ID | Item | Effort |
| --- | --- | --- |
| UX-12 | **An `essentials` preset**: code map, context pack, delegation, telemetry and the prompt gate in ask mode, so nothing holds work back and nothing adds a step. Review and the spec gate are one config line, or `compass install --modules full`, away. Whether it becomes the default is decision D16. | 0.5 |
| UX-13 | **Review without tags in the code** (decide after pilot data, D17). Claude records each note through an MCP tool straight into the manifest. There is no strip step and no commit block, at the cost of notes that no longer sit next to the code. | 4 to 5, if taken |

### F. Docs and a try-out

| ID | Item | Effort |
| --- | --- | --- |
| UX-14 | **A one-page quick start** (`docs/quick-start.md`, linked first from the README): the five-line manual above, the install command, and how to switch Compass off. The user guide becomes the reference; the cheat sheet folds into the two, so there are fewer documents to choose from. | 1 |
| UX-15 | **`compass demo`**: a throwaway repository built from a fixture, already set up, with three prompts to try, deleted afterwards. It packages the user guide's ten-minute demo, so trying Compass takes no setup at all. | 1 |

### G. Measure the friction

| ID | Item | Effort |
| --- | --- | --- |
| UX-16 | **Friction counts in telemetry**, counts only, as every row is today: spec-gate holds and the time to approval, strict-mode holds, pre-commit refusals, commits that carried tags anyway (a post-commit check, which also reveals `--no-verify`), approvals and accepts by reply against by command, `/compass` uses, and `doctor` failures. `compass report` gets an **Adoption** section: developers and sessions with Compass on per week, stuck moments, and bypasses. | 2 |

The pilot's survey (Evaluation Plan, week 8) gains two questions, and a two-question check-in follows the first week with Compass on:
- Did you have to look anything up to use Compass? What?
- Did Compass ever stop you, and did you know how to get past it?

## 5. Order of work

| Phase | When | Items | Effort |
| --- | --- | --- | --- |
| **1. The core** | before the pilot starts | UX-04, UX-05, UX-07, UX-11, UX-14: the two replies, the one door, the messages, the one page. After these, the five-line manual is true | about 5.5 days |
| **2. The rest of the pre-pilot set** | before the pilot's Compass weeks (week 3) | UX-06, UX-08, UX-10, UX-16, then UX-01, UX-02, UX-03, UX-09, UX-12, UX-15 | about 11 days |
| **3. From the data** | after the week-4 checkpoint | UX-13 if D17 says so; tips for the features developers never found; whatever the friction counts point at | to be sized |

Everything in phases 1 and 2 must land before the pilot's Compass weeks start, and the Compass version is pinned from then on: telemetry and benchmark rows record the version, and numbers are never compared across versions (CLAUDE.md, Conventions).

**Practice for the pilot**, which costs no code:
- A 15-minute live demo at kick-off instead of reading the docs.
- One champion per team, and one chat channel for questions.
- Office hours in the first week with Compass on.
- The owner reads the report's Adoption section every week and tunes from it.

## 6. Decisions needed

| # | Decision | Recommendation |
| --- | --- | --- |
| D14 | May a typed reply ("approve", "accept") count as the developer's approval and acceptance (UX-04, UX-05)? It changes SG-05 and RO-05 | **Yes**, on the reasoning in section 4A. It removes both stopping points |
| D15 | May Compass speak, once, in a git repository that is not set up, when it is installed for the user (UX-01)? Today the hooks stay silent there | **Yes**, once per repository, with "not here" to stop it |
| D16 | The default preset for new installs (UX-12) | **`essentials`** for installs outside the pilot. The pilot keeps `full`, with phase 1 done, so the Evaluation Plan's comparison stays as written |
| D17 | Review without tags in the code (UX-13) | Decide at the week-4 checkpoint, from the friction counts |

## 7. Risks

| Risk | Mitigation |
| --- | --- |
| A reply is read as approval when it was not meant as one | Narrow phrases only, only while something waits, and a confirmation line every time. An accidental accept loses no notes: the archived manifest keeps them |
| More messages make Compass noisier | The welcome shows once; status only on request; the message audit (UX-11) removes as much text as it adds |
| Hiding commands breaks someone's script | Only the help listing changes; every command name and behaviour stays |
| The prompt hook gets slower | The new checks run only when something waits (a spec or open tags), on the slow path that already loads state; the perf tests cover them |
| Easier review becomes weaker review | Accepting stays an explicit act by the developer, and the manifest link is shown every time. Tag-free review comes only with D17, and only with data |

## 8. What does not change

The invariants in CLAUDE.md hold for every item:
- the prompt is never turned away, and every hook fails open;
- no network calls in hooks;
- approval and acceptance stay the developer's own acts;
- the plugin holds no logic;
- every module can still be switched off.

Nothing here touches the code map, the query tools or the measurement.

## 9. Related work that also decides adoption

- **Hook speed on Windows.** On this laptop a prompt costs 0.3–0.7 s and an edit 0.75–1.25 s, against budgets of 100 ms and 500 ms. A slow tool gets switched off however easy it is to use. The reference run on pilot machines is item 7.4 in the Status doc, and profiling start-up comes before the pilot.
- **Setup failures that look like Compass bugs**, such as the stale `compass` on PATH found on Oct 16, which `doctor` now reports. UX-03 turns such reports into fixes.

## 10. Spec changes once approved

- **Requirements Spec:** a new component C11 "Ease of use" with UX-01 to UX-16. SG-05 and RO-05 gain "or a plain reply" (D14), and IN-15 gains `essentials` (D16).
- **Evaluation Plan:** the adoption measures in section 2, the two survey questions and the week-1 check-in.
- **Proposal:** the adoption risk's mitigation points here.
- **Getting Started guide:** a Step 11 with the work breakdown.
- **Status doc:** D14 to D17 and the items in section 7.
