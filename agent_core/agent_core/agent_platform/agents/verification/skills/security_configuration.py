from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from agent_core.agent_platform.agents.verification.contracts import (
    SecurityConfigurationAssessment,
    SecurityIssue,
    VerificationFinding,
)


@dataclass(frozen=True)
class _SecurityRule:
    rule_id: str
    category: str
    severity: Literal["warning", "error"]
    message: str
    pattern: re.Pattern[str]


_RULES = (
    _SecurityRule(
        rule_id="hardcoded_secret",
        category="secret",
        severity="error",
        message="A probable hard-coded credential was added.",
        pattern=re.compile(
            r"""(?ix)
            \b(api[_-]?key|access[_-]?token|auth[_-]?token|
            client[_-]?secret|secret(?:[_-]?(?:key|token))?|password|passwd)\b
            \s*[:=]\s*(?:[rubf]{0,2})?["'][^"'\s]{8,}["']
            """
        ),
    ),
    _SecurityRule(
        rule_id="private_key_material",
        category="secret",
        severity="error",
        message="Private key material was added to the repository.",
        pattern=re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    _SecurityRule(
        rule_id="tls_verification_disabled",
        category="transport_security",
        severity="error",
        message="TLS certificate or host verification was disabled.",
        pattern=re.compile(
            r"(?i)(verify\s*=\s*false|check_hostname\s*=\s*false|"
            r"_create_unverified_context|NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*[\"']?0)"
        ),
    ),
    _SecurityRule(
        rule_id="shell_execution_enabled",
        category="command_execution",
        severity="error",
        message="Shell command execution was enabled and requires injection review.",
        pattern=re.compile(r"(?i)\bshell\s*=\s*true\b"),
    ),
    _SecurityRule(
        rule_id="dynamic_code_execution",
        category="code_execution",
        severity="error",
        message="Dynamic code execution was added.",
        pattern=re.compile(r"\b(?:eval|exec)\s*\("),
    ),
    _SecurityRule(
        rule_id="permissive_cors",
        category="configuration",
        severity="warning",
        message="A wildcard cross-origin policy was added.",
        pattern=re.compile(
            r"""(?ix)
            (allow_origins\s*=\s*\[\s*["']\*["']|
            access-control-allow-origin\s*[:=]\s*["']?\*)
            """
        ),
    ),
    _SecurityRule(
        rule_id="debug_mode_enabled",
        category="configuration",
        severity="warning",
        message="Debug mode was explicitly enabled.",
        pattern=re.compile(r"(?i)\bdebug\s*[:=]\s*true\b"),
    ),
)


class SecurityConfigurationInput(BaseModel):
    repository_diff: str = ""
    enabled: bool = True


class SecurityConfigurationOutput(BaseModel):
    assessment: SecurityConfigurationAssessment
    findings: list[VerificationFinding] = Field(default_factory=list)


class SecurityConfigurationReviewSkill:
    name = "security_configuration_review"
    required_dependencies: tuple[str, ...] = ()

    async def run(
        self,
        input_data: SecurityConfigurationInput,
    ) -> SecurityConfigurationOutput:
        if not input_data.enabled:
            return SecurityConfigurationOutput(
                assessment=SecurityConfigurationAssessment(
                    enabled=False,
                    passed=True,
                )
            )

        added_lines = list(_iter_added_lines(input_data.repository_diff))
        issues: list[SecurityIssue] = []
        for relative_path, line_number, content in added_lines:
            stripped = content.strip()
            if not stripped or stripped.startswith(("#", "//")):
                continue
            for rule in _RULES:
                if not rule.pattern.search(content):
                    continue
                issues.append(
                    SecurityIssue(
                        rule_id=rule.rule_id,
                        category=rule.category,
                        severity=rule.severity,
                        message=rule.message,
                        relative_path=relative_path,
                        line_number=line_number,
                    )
                )

        findings = [
            VerificationFinding(
                severity=issue.severity,
                code=issue.rule_id,
                message=_issue_message(issue),
            )
            for issue in issues
        ]
        assessment = SecurityConfigurationAssessment(
            enabled=True,
            passed=not any(issue.severity == "error" for issue in issues),
            issues=issues,
            scanned_added_line_count=len(added_lines),
        )
        return SecurityConfigurationOutput(
            assessment=assessment,
            findings=findings,
        )


def _issue_message(issue: SecurityIssue) -> str:
    location = issue.relative_path or "repository diff"
    if issue.line_number is not None:
        location = f"{location}:{issue.line_number}"
    return f"{issue.message} Location: {location}."


def _iter_added_lines(repository_diff: str):
    relative_path: str | None = None
    new_line_number: int | None = None
    hunk_pattern = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

    for line in repository_diff.splitlines():
        if line.startswith("+++ "):
            path = line[4:].strip()
            relative_path = path[2:] if path.startswith("b/") else path
            continue
        hunk = hunk_pattern.match(line)
        if hunk:
            new_line_number = int(hunk.group(1))
            continue
        if line.startswith("+") and not line.startswith("+++"):
            yield relative_path, new_line_number, line[1:]
            if new_line_number is not None:
                new_line_number += 1
            continue
        if line.startswith("-") and not line.startswith("---"):
            continue
        if new_line_number is not None:
            new_line_number += 1
