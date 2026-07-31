# Phase 8 Verification Skills Results

## Summary

The Verification Agent now evaluates implementation evidence through modular, typed skills instead
of embedding acceptance, test, regression, and security rules directly in LangGraph nodes. The
agent remains independently executable, owns its workflow and checkpoint state, and returns the
same four verdicts and orchestrator transitions.

This milestone preserves the existing default pass behavior. Test-command requirements and
regression warnings that could affect existing callers are configuration-driven. Failed commands,
unmet acceptance criteria, and detected high-severity security defects request changes.

## Skill Boundary

The agent-local skills are under
`agent_core/agent_platform/agents/verification/skills`:

| Skill | Typed output | Responsibility |
| --- | --- | --- |
| `AcceptanceEvaluationSkill` | `AcceptanceCoverageAssessment` | Builds a per-criterion mandatory coverage matrix and records supporting evidence sources. |
| `TestAdequacySkill` | `TestAdequacyAssessment` | Classifies quality commands, detects failures and timeouts, and optionally requires test execution or source-change evidence. |
| `RegressionRiskSkill` | `RegressionRiskAssessment` | Scores warning terms, sensitive paths, change size and breadth, and rollback availability. |
| `SecurityConfigurationReviewSkill` | `SecurityConfigurationAssessment` | Scans added diff lines for probable secrets and unsafe security/configuration changes without retaining secret values. |
| `EvidenceSummarySkill` | `VerificationEvidenceSummary` | Aggregates the prior assessments into a compact persisted summary. |

Every skill has a Pydantic input and output contract, declares its required dependencies, and can
run without an agent instance. These skills are currently deterministic and require no
infrastructure dependencies.

## Workflow

The Verification Agent still owns a separately compiled `verification-agent-workflow`:

```text
load_evidence
  -> inspect_result
  -> inspect_quality_commands
  -> evaluate_acceptance_criteria
  -> review_risk
  -> review_security_configuration
  -> return_verdict
```

The graph composes a `VerificationSkillSet`. Nodes adapt the typed request to skill input and append
the returned findings; they do not contain the evaluation algorithms.

Each assessment is persisted in `VerificationAgentState` after its node completes. The final
`VerificationAgentResult` contains:

- `acceptance_coverage`
- `test_adequacy`
- `regression_risk`
- `security_review`
- `evidence_summary`
- The existing `verdict` and `findings`

Historical or manually constructed result payloads remain valid because the assessment fields have
safe defaults.

## Verdict Rules

- A `blocked` finding produces `blocked` and escalation.
- An `error` finding produces `changes_requested` and coding rework.
- A `warning` finding produces `passed_with_warnings`.
- No findings produces `passed`.

All supplied acceptance criteria are currently mandatory because `AcceptanceCriterionSpec` does not
define an optional-criterion flag. Every unsatisfied criterion therefore creates an error finding
and prevents completion.

The security review examines added lines only. It identifies probable hard-coded credentials,
private key material, disabled TLS verification, shell execution, dynamic code execution, wildcard
CORS, and enabled debug mode. Findings contain rule and location metadata, not matched secret
content. This is a deterministic guardrail, not a replacement for a dedicated SAST or secret
scanner.

## Configuration

The following `VerificationAgentConfig` settings are materialized from each agent's `settings`
object:

| Setting | Default | Effect |
| --- | --- | --- |
| `require_diff_for_pass` | `true` | Blocks completion without an actual diff. |
| `require_test_command_for_pass` | `false` | Requires a recognized executed test command when enabled. |
| `require_test_evidence_for_source_changes` | `false` | Requires a test command, external test evidence, or test-file change for source changes. |
| `security_review_enabled` | `true` | Runs deterministic security/configuration checks. |
| `warn_on_sensitive_changes` | `false` | Promotes sensitive-path risk into a warning finding. |
| `warn_on_missing_rollback` | `false` | Promotes missing rollback risk into a warning finding. |
| `large_change_line_threshold` | `500` | Adds a warning when the changed-line threshold is met. |
| `large_change_file_threshold` | `20` | Adds a warning when the changed-file threshold is met. |

The expanded settings are recorded in `agent_core/agent-platform.example.json`.

## Compatibility

- Existing agent request fields and factory registration are unchanged.
- Existing result import paths continue to expose `VerificationFinding` and
  `VerificationVerdict`.
- The orchestrator still receives one typed result and routes by `next_action`; agents do not call
  one another.
- Existing callers that do not record quality commands retain prior behavior unless stricter test
  settings are enabled.
- Existing PostgreSQL result JSON remains readable because new result fields are defaulted.

## Validation

Coverage includes:

- Mandatory acceptance coverage with supported and unsupported criteria.
- Failed commands, test-command requirements, and source changes without test evidence.
- Regression scoring across sensitive, broad, large, warning-term, and rollback factors.
- Security findings, source locations, comment exclusion, disablement, and secret redaction.
- Typed final evidence aggregation.
- Agent-level `changes_requested` verdicts for test inadequacy and security defects.
- Existing factory, orchestration, transition, workflow, and checkpoint compatibility.

Commands:

```powershell
.venv/Scripts/python.exe -m ruff check <changed Python files>
.venv/Scripts/python.exe -m json.tool agent_core/agent-platform.example.json
.venv/Scripts/python.exe -m pytest -q tests/test_verification_skills.py tests/test_agent_platform.py tests/test_agent_internal_workflows.py tests/test_agent_transition_resolver.py
.venv/Scripts/python.exe -m pytest -q
```

Results:

- Changed-file Ruff and example JSON validation: passed.
- Verification skill tests: 7 passed.
- Focused verification, factory, workflow, and transition tests: 33 passed.
- Full suite with live PostgreSQL integration gates enabled: 205 passed, 1 skipped, and 4
  pre-existing warnings.

## Follow-On Completion

- Verification-specific override and audit are complete; see
  `docs/phase-8-verification-override-results.md`.
- Verification status, evidence summary, and override history projection to OpenProject is
  complete; see `docs/phase-8-openproject-verification-results.md`.
