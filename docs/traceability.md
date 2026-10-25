# Compass — Traceability of the Must requirements


Oct 15, 2026, updated Oct 16 · Compass 0.3.0 · 767 automated tests, plus five real-session checks in `tests/e2e/`

The Requirements Spec's first release-acceptance box reads: *"All Must requirements have an automated test or a documented manual check."* This page maps each one. For every Must requirement in C1 to C10, and for the non-functional rows whose check is a test, it lists:
- the most direct automated tests (`file::test`)
- the real-session check that exercises it, if any
- a manual check, where the automated evidence leaves an edge open

**Result.** Every Must requirement has automated evidence. Two are only partly met, and the release-acceptance box can be ticked only once their manual checks pass:
- ST-01: no organisation-wide standards source yet (decision D3).
- IN-13: the release jobs have never run, and the feeds don't exist yet (decisions D1a and D2).

The smaller gaps the first sweep found are closed. Six tests were added on Oct 15:
- a custom bypass prefix (PG-03), which also exposed a bug
- the query and context-pack switches (CF-03), which also exposed a bug
- `--json` on every query twin (QT-04)
- every hook handler failing open (NF-12)

On Oct 16, one more (PG-02): Claude Code's own notifications, such as a background agent finishing, reached the prompt gate as prompts. One became task T5's brief, and in strict mode one would have ended the hold before the developer answered. They are now ignored, with a test. And one for CP-02: a backticked path such as `C:\…\pytest.log` resolved to a function named after its extension (`log`); a path now resolves as a symbol only through a member separator (`file.py::test`).

The edges still open are listed under each row's manual check.

The real-session checks run with `uv run python tests/e2e/run_all.py`. Each starts headless Claude Code sessions with the developer's own login. The manual checks are written so that anyone can follow them.

Keep this page in step with the tests: when a Must requirement changes, or a test it names is renamed or removed, update its row.

## C1 Prompt gate

| ID | Automated tests | Real-session check | Manual check, where needed |
| --- | --- | --- | --- |
| PG-01 Rules only, no LLM call | `tests/test_gates.py::test_missing_fields`<br>`tests/test_gates.py::test_vague_requests_get_a_question`<br>`tests/test_gates.py::test_clear_requests_go_straight_through`<br>`tests/test_gates.py::test_a_new_rule_is_a_module_in_gate_rules` | `check_gates.py`: "improve the error handling" makes Claude ask and change nothing | The rules are in-process functions held to 100 ms by `tests/test_perf.py::test_prompt_gate_p95_under_100ms`. Optional: point `local_llm` at a fake endpoint, send "fix it", and confirm the endpoint gets no request |
| PG-02 Never reject; Claude asks; strict holds edits | `tests/test_gates.py::test_ask_mode_has_claude_check_before_assuming`<br>`tests/test_gates.py::test_what_claude_and_the_developer_are_told`<br>`tests/test_gates.py::test_strict_mode_holds_edits_until_the_developer_answers`<br>`tests/test_gates.py::test_off_mode_and_non_tasks_are_never_checked`<br>`tests/test_gates.py::test_claude_codes_own_notifications_are_not_prompts` | `check_gates.py`: ask mode, and strict mode with its hold | — |
| PG-03 Bypass prefix, every bypass logged | `tests/test_gates.py::test_quick_skips_the_check_and_is_logged_for_tuning`<br>`tests/test_gates.py::test_a_custom_bypass_prefix_is_honoured_and_named`<br>`tests/test_gates.py::test_the_spec_gate_names_a_custom_bypass_prefix`<br>`tests/test_gates.py::test_quick_lifts_the_spec_gate_for_one_turn` | — | — |
| PG-04 Rules and strictness from config | `tests/test_gates.py::test_required_fields_come_from_config`<br>`tests/test_gates.py::test_strictness_values`<br>`tests/test_gates.py::test_strict_mode_holds_edits_until_the_developer_answers` | `check_gates.py` step 2 sets `strictness: strict` | — |
| PG-05 `/compass:task` with the five fields | `tests/test_plugin.py::test_task_and_approve_are_the_developers_too`<br>`tests/test_gates.py::test_labels_inline_and_on_their_own_lines`<br>`tests/test_gates.py::test_task_briefs_start_small_and_large_tasks` | `check_install.py`: the command is listed in both modes | Run `/compass:task Goal: … Scope: … Non-goals: … Accept when: … Constraints: …`. Expected: "Task Tn started", and `compass task` shows Tn |

## C2 Context pack, C3 Spec gate

| ID | Automated tests | Real-session check | Manual check, where needed |
| --- | --- | --- | --- |
| CP-01 Names resolved against the index | `tests/test_gates.py::test_the_pack_resolves_symbols_files_and_directories`<br>`tests/test_gates.py::test_candidates_are_code_names_not_words`<br>`tests/test_gates.py::test_the_pack_is_silent_about_names_that_are_not_the_projects` | — | — |
| CP-02 Map lines, stack, tests within a budget | `tests/test_gates.py::test_the_pack_resolves_symbols_files_and_directories`<br>`tests/test_gates.py::test_the_pack_names_stack_versions`<br>`tests/test_gates.py::test_the_pack_keeps_to_its_budget`<br>`tests/test_gates.py::test_a_quoted_path_is_not_read_as_a_symbol` | — | The default of 1,500 tokens is set in `config.py`, not asserted. `compass check-prompt` with 20+ code names should end with "left out to stay within the pack's budget" |
| SG-02 A spec for large tasks | `tests/test_gates.py::test_a_large_task_edits_nothing_but_its_spec_until_approved`<br>`tests/test_gates.py::test_a_spec_draft_starts_from_the_brief`<br>`tests/test_gates.py::test_size_classification` | `check_gates.py` step 3 | — |
| SG-03 Open questions section | `tests/test_gates.py::test_a_spec_draft_starts_from_the_brief`<br>`tests/test_gates.py::test_approve_warns_about_unticked_questions` | `check_gates.py` | — |
| SG-04 Edits held until approved | `tests/test_gates.py::test_a_large_task_edits_nothing_but_its_spec_until_approved`<br>`tests/test_gates.py::test_approving_a_large_task_whose_spec_went_missing`<br>`tests/test_gates.py::test_the_spec_gate_can_be_switched_off` | `check_gates.py`: no `src/` change before approval | — |
| SG-05 Approval records who and when | `tests/test_gates.py::test_approve_records_who_and_when`<br>`tests/test_plugin.py::test_task_and_approve_are_the_developers_too` | `check_gates.py` runs `compass approve` | Run `/compass:approve T1` in a session. Expected: one line of confirmation, and `approved_by` and `approved_at` in the spec |

## C4 Code map indexer, C5 Query tools

| ID | Automated tests | Real-session check | Manual check, where needed |
| --- | --- | --- | --- |
| IX-01 `git ls-files`, `.gitignore`, excludes | `tests/test_fixtures.py::test_files_and_stack_snapshot`<br>`tests/test_incremental.py::test_refresh_handles_added_deleted_and_excluded_files`<br>`tests/test_githooks_cli.py::test_files_and_stack_json` | — | — |
| IX-02 tree-sitter, ctags fallback | `tests/test_parser.py::test_python_nesting_docs_and_visibility`<br>`tests/test_fixtures.py::test_index_and_shards_snapshot`<br>`tests/test_ctags.py::test_ctags_covers_languages_without_a_query`<br>`tests/test_ctags.py::test_option_files_in_the_repository_are_ignored` | — | The ctags tests need Universal Ctags (`COMPASS_TEST_CTAGS`); CI installs it |
| IX-03 Symbol fields | `tests/test_parser.py::test_python_nesting_docs_and_visibility`<br>`tests/test_parser.py::test_rust_impls_attributes_and_visibility`<br>`tests/test_query.py::test_cli_twins` | — | — |
| IX-04 Doc comments | `tests/test_parser.py::test_blank_line_detaches_a_comment`<br>`tests/test_parser.py::test_a_doc_folded_into_the_header_before_a_definition_still_counts`<br>`tests/test_docs.py::test_summary_drops_dartdoc_xmldoc_and_javadoc_markup` | — | — |
| IX-05 SQLite at `.compass/index.db` | `tests/test_githooks_cli.py::test_init_writes_config_gitignore_hooks_and_index`<br>`tests/test_incremental.py::test_corrupt_index_is_rebuilt` | — | — |
| IX-06 One shard per directory, root index | `tests/test_shards.py::test_symbol_lines_follow_the_guide_format`<br>`tests/test_shards.py::test_large_directories_split_under_the_token_limit`<br>`tests/test_incremental.py::test_shard_names_never_collide` | — | — |
| IX-07 Re-parse changed files only | `tests/test_incremental.py::test_unchanged_content_is_not_reparsed`<br>`tests/test_incremental.py::test_editing_a_file_updates_its_shard`<br>`tests/test_incremental.py::test_skipped_files_are_remembered_not_reread` | — | — |
| IX-08 Update triggers | `tests/test_hooks.py::test_post_edit_reindexes_the_edited_file`<br>`tests/test_hooks.py::test_session_start_refreshes_stale_files_inline`<br>`tests/test_githooks_cli.py::test_git_hooks_keep_the_index_current_across_checkouts` (POSIX) | — | post-merge and post-rewrite, and any git hook on Windows: after `compass init`, merge a branch that adds `def zz(): pass`. Expected: `compass find-symbol zz` finds it. Rename it with `git commit --amend`. Expected: the new name is found and the old one is gone |
| IX-09 Folder tree with purposes | `tests/test_shards.py::test_index_is_a_tree_with_purposes`<br>`tests/test_shards.py::test_directory_header_counts_and_purpose`<br>`tests/test_query.py::test_map` | — | — |
| IX-10 Stack profile | `tests/test_stacks.py::test_yarn_and_npm_lockfiles_resolve_versions` (and the other stack tests)<br>`tests/test_stacks.py::test_azure_pipelines_scripts_and_tasks`<br>`tests/test_fixtures.py::test_files_and_stack_snapshot` | — | — |
| QT-01 The MCP tools | `tests/test_mcp.py::test_tools_and_instructions`<br>`tests/test_mcp.py::test_every_tool_answers`<br>`tests/test_query.py::test_tests_for_files` | `check_query_tools.py` and `check_install.py`: answered through Compass with zero Read calls | — |
| QT-02 `read_symbol` returns the range | `tests/test_query.py::test_read_symbol_returns_the_range_with_its_doc`<br>`tests/test_query.py::test_read_symbol_context_lines`<br>`tests/test_query.py::test_read_symbol_follows_edits_on_disk` | — | — |
| QT-04 CLI twins with `--json` | `tests/test_query.py::test_cli_twins`<br>`tests/test_query.py::test_every_cli_twin_answers_in_json`<br>`tests/test_githooks_cli.py::test_files_and_stack_json` | — | — |

## C6 Delegation, C7 Review output

| ID | Automated tests | Real-session check | Manual check, where needed |
| --- | --- | --- | --- |
| DL-01 Haiku subagents | `tests/test_plugin.py::test_subagents_match_their_contracts`<br>`tests/test_install.py::test_files_mode_maps_every_plugin_file` | `check_delegation.py`: a 600-test run goes to a Compass subagent | — |
| DL-02 Output contracts | `tests/test_delegation.py::test_answers_against_their_contracts`<br>`tests/test_delegation.py::test_an_answer_over_its_contract_is_sent_back_once`<br>`tests/test_delegation.py::test_scaffold_changes_only_the_files_it_was_given` | `check_delegation.py`: the answer is at most 20 lines and names both failures | — |
| DL-03 Delegation rules | `tests/test_delegation.py::test_session_start_hands_claude_the_delegation_rules`<br>`tests/test_install.py::test_session_start_names_the_agents_as_the_install_mode_does` | `check_delegation.py`: the main conversation never ran the suite itself | — |
| DL-06 Silent without a local model | `tests/test_mcp.py::test_the_local_model_tools_are_offered_only_while_a_model_answers`<br>`tests/test_llm.py::test_enrich_does_nothing_without_a_model`<br>`tests/test_llm.py::test_a_model_that_is_down_or_failing_is_unavailable` | `check_delegation.py --local-model` | — |
| RO-01 Replies of about 10 lines | `tests/test_review.py::test_session_start_hands_claude_the_rules_and_the_task`<br>`tests/test_review.py::test_session_rules_follow_the_config`<br>`tests/test_plugin.py::test_output_style_is_opt_in_and_keeps_coding_instructions` | `check_review_loop.py`: a reply of 12 lines at most | — |
| RO-02 Anchor tags | `tests/test_anchors.py::test_anchors_are_found_in_any_comment_syntax`<br>`tests/test_anchors.py::test_text_that_only_looks_like_an_anchor_is_ignored`<br>`tests/test_review.py::test_stop_asks_once_for_missing_anchors_and_writes_the_manifest` | `check_review_loop.py` on the Python, TypeScript and Go fixtures | — |
| RO-03 The manifest | `tests/test_manifest.py::test_manifest_groups_anchors_for_the_reviewer`<br>`tests/test_manifest.py::test_manifest_is_written_with_a_json_twin_and_reloads`<br>`tests/test_review.py::test_manifest_command_live_and_hosted_after_accept` | `check_review_loop.py` | — |
| RO-05 Accept; pre-commit refusal | `tests/test_review.py::test_accept_strips_the_task_and_archives_its_manifest`<br>`tests/test_review.py::test_pre_commit_refuses_leftover_anchors_until_accepted` (POSIX)<br>`tests/test_anchors.py::test_staged_anchors_are_only_the_added_lines` | `check_review_loop.py`: the commit with tags is refused, and the one after `compass accept` goes through | On Windows: commit a file with a tag. Expected: refused, naming the tag. Run `compass accept` and commit again. Expected: it goes through. (Done by hand on this repository for tasks T1, T2 and T4) |

## C8 Standards, C9 Telemetry and setup

| ID | Automated tests | Real-session check | Manual check, where needed |
| --- | --- | --- | --- |
| ST-01 Standards as skills, repo or org | `tests/test_plugin.py::test_the_skill_library_keeps_one_shape`<br>`tests/test_install.py::test_files_mode_maps_every_plugin_file` | `check_install.py` lists the skills | **Partly met.** Repo standards: put "flag every print()" in `.compass/standards/code-review.md`, then run `/compass:code-review` on a diff that adds one. Expected: a finding citing the rule. The org-wide source waits on decision D3 |
| ST-02 Dependency versions at SessionStart | `tests/test_gates.py::test_session_start_adds_the_stack_and_a_pending_spec`<br>`tests/test_stacks.py::test_yarn_and_npm_lockfiles_resolve_versions`<br>`tests/test_stacks.py::test_pub_workspace_member_uses_the_root_lock` | — | — |
| TM-01 Per-turn tokens, time, tools | `tests/test_telemetry.py::test_every_stop_appends_the_turn_since_the_last_one`<br>`tests/test_telemetry.py::test_each_message_counts_once_at_its_final_usage`<br>`tests/test_telemetry.py::test_rows_carry_the_task_and_its_tags` | `check_delegation.py`: the rows equal Claude Code's own per-model counts | — |
| TM-02 Local by default, export opt-in | `tests/test_telemetry.py::test_telemetry_can_be_off_or_exported`<br>`tests/test_telemetry.py::test_telemetry_fails_open` | — | — |
| CF-01 Marketplace plus one CLI package | `tests/test_plugin.py::test_the_marketplace_serves_this_plugin`<br>`tests/test_plugin.py::test_claude_code_accepts_the_plugin`<br>`tests/test_install.py::test_the_wheel_carries_the_plugin` | `check_install.py` plugin mode | — |
| CF-02 `compass init` | `tests/test_githooks_cli.py::test_init_writes_config_gitignore_hooks_and_index`<br>`tests/test_install.py::test_install_runs_init_with_the_preset` | Every e2e check runs it | — |
| CF-03 Every component can be switched off | `tests/test_telemetry.py::test_a_telemetry_only_baseline`<br>`tests/test_mcp.py::test_query_switched_off_offers_no_tools_and_says_so`<br>`tests/test_gates.py::test_the_context_pack_can_be_switched_off`<br>`tests/test_gates.py::test_the_spec_gate_can_be_switched_off` (and the review, delegation and contract switches) | — | — |

## C10 Installer

| ID | Automated tests | Real-session check | Manual check, where needed |
| --- | --- | --- | --- |
| IN-01 One command installs everything | `tests/test_install.py::test_the_cli_installs_and_uninstalls`<br>`tests/test_install.py::test_install_runs_init_with_the_preset`<br>`tests/test_install.py::test_the_npm_wrapper_installs_the_cli_then_hands_over` | `check_install.py`: `uvx --from <checkout> compass install` in both modes | `npx` and `uvx` from a published package, once the feeds exist (IN-13) |
| IN-02 Two modes from one source | `tests/test_install.py::test_files_mode_maps_every_plugin_file`<br>`tests/test_install.py::test_a_project_install_writes_files_hooks_mcp_and_record`<br>`tests/test_install.py::test_plugin_mode_defaults_to_the_bundled_marketplace` | `check_install.py`: both modes | — |
| IN-03 Scopes | `tests/test_install.py::test_a_user_install_goes_to_the_home_directory`<br>`tests/test_install.py::test_plugin_mode_goes_through_the_claude_cli`<br>`tests/test_install.py::test_files_mode_has_no_local_scope` | `check_install.py` (project scope) | User scope against real Claude Code: in a sandbox HOME, run `compass install --scope user --mode plugin --yes`. Expected: a session in another repository connects the MCP server. Then `compass uninstall --scope user`. Expected: `~/.claude/settings.json` is back to its original bytes |
| IN-05 Install record; upgrades keep edits | `tests/test_install.py::test_upgrade_keeps_edits_and_deletions`<br>`tests/test_install.py::test_an_upgrade_offers_no_new_version_of_an_edited_file_compass_did_not_change` | `check_install.py`: `compass upgrade` keeps an edited file | — |
| IN-07 Uninstall removes exactly what was installed | `tests/test_install.py::test_install_keeps_other_settings_and_uninstall_restores_the_exact_bytes`<br>`tests/test_install.py::test_plugin_mode_uninstall_restores_the_original_settings_bytes`<br>`tests/test_install.py::test_plugin_mode_uninstall_removes_a_settings_file_claude_code_created` | `check_install.py`: git status and the user's settings unchanged | — |
| IN-08 Non-destructive settings merges | `tests/test_install.py::test_install_keeps_other_settings_and_uninstall_restores_the_exact_bytes`<br>`tests/test_install.py::test_a_settings_file_that_does_not_parse_is_never_overwritten` | — | Atomic replacement is by construction (`settings.atomic_write`), not tested by forcing a failure |
| IN-10 One version everywhere | `tests/test_plugin.py::test_versions_agree`<br>`tests/test_install.py::test_the_npm_package_is_in_step`<br>`tests/test_release.py::test_this_checkout_is_consistent` | — | — |
| IN-11 Both agent names | `tests/test_install.py::test_files_mode_subagents_are_held_to_the_same_contracts`<br>`tests/test_install.py::test_session_start_names_the_agents_as_the_install_mode_does`<br>`tests/test_install.py::test_the_install_mode` | `check_install.py`: `compass:digest` and `compass-digest` | In a files-mode session, delegate a test run. Expected: the subagent's telemetry row reads `"install_mode": "files"` |
| IN-12 The npm wrapper holds no logic | `tests/test_install.py::test_the_npm_package_is_in_step`<br>`tests/test_install.py::test_the_npm_wrapper_installs_the_cli_then_hands_over` (on Windows too since Oct 15) | — | On a machine without uv, run `npx compass-cc install --yes` from PowerShell, cmd and bash. Expected: uv is installed, then the install continues |
| IN-13 Distribution through both hosts | `tests/test_release.py` (tag against versions, artifacts carry the plugin)<br>`tests/test_ci_configs.py::test_both_ci_systems_build_releases_the_same_way`<br>`tests/test_ci_configs.py::test_releases_run_on_version_tags_only_and_publish_nothing_otherwise` | — | **Partly met.** Push a `v<version>` tag (or run the release workflow by hand). Expected: both release jobs pass and attach the artifacts. Then install from each feed, and add the marketplace from GitHub `owner/repo` and from the Azure Repos URL |

## Non-functional requirements checked by tests

| ID | Automated tests | Manual check, where needed |
| --- | --- | --- |
| NF-05 Shards ≤ 2,000 tokens | `tests/test_shards.py::test_large_directories_split_under_the_token_limit`<br>`tests/test_shards.py::test_a_single_huge_file_splits_with_continued_headers`<br>`tests/test_perf.py::test_footprint_and_shard_size` (`--perf`) | — |
| NF-08 macOS, Linux, Windows | `tests/test_ci_configs.py::test_both_ci_systems_test_the_same_platforms` (CI runs the suite on all three) | Ten git-hook and permission tests are POSIX-only; on Windows, do the IX-08 and RO-05 manual checks |
| NF-09 Ten languages | `tests/test_fixtures.py::test_fixtures_cover_the_nf09_languages`<br>`tests/test_fixtures.py::test_index_and_shards_snapshot`<br>`tests/test_query.py::test_java_tests_imports_callers_and_outline` (and one per language) | — |
| NF-10 Privacy, NF-11 Security | `tests/test_executables.py`<br>`tests/test_llm.py::test_a_redirect_is_never_followed`<br>`tests/test_llm.py::test_code_never_leaves_the_machine` | The audit and review in [security-privacy-review.md](security-privacy-review.md) |
| NF-12 Fail open | `tests/test_hooks.py::test_every_hook_fails_open`<br>`tests/test_hooks.py::test_unexpected_hook_arguments_never_exit_2`<br>`tests/test_gates.py::test_the_gates_fail_open` (and the review, delegation and telemetry equivalents) | — |
| NF-13 Determinism | `tests/test_incremental.py::test_fresh_builds_are_byte_identical`<br>`tests/test_incremental.py::test_full_rebuild_over_an_existing_index_matches_a_fresh_one` | — |
| NF-16 GitHub and Azure DevOps | `tests/test_manifest.py::test_remotes_of_every_supported_host`<br>`tests/test_stacks.py::test_azure_pipelines_scripts_and_tasks`<br>`tests/test_ci_configs.py::test_both_ci_systems_run_the_same_commands` | Azure Pipelines has never run (no organisation yet); distribution as for IN-13 |
