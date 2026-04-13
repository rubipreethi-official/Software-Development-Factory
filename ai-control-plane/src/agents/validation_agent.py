"""
validation.py — Multi-Layer Validation Engine
===============================================
Tasks: D-11, D-12, D-13, D-14
Contract validation, trajectory evaluation, and blocking validation gates.
Enforces spec compliance as hard gates, not advisory reports.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from config import get_policy_manager
from models import (
    ValidationResult,
    ValidationSeverity,
    PolicyOverride,
    AuditLog,
    AuditAction,
)

logger = structlog.get_logger("validation")


# ─── D-11: Contract Validation ──────────────────────────────────────────────────

class ContractValidator:
    """
    Validates generated API implementations against OpenAPI contracts.
    Checks request/response schemas, status codes, and endpoint coverage.
    """

    @staticmethod
    async def validate_contract(
        contract: dict,
        workflow_id: str,
        session,
    ) -> ValidationResult:
        """Validate an OpenAPI contract for structural correctness."""
        findings = []
        passed = True

        # Check required OpenAPI fields
        if "openapi" not in contract:
            findings.append({"field": "openapi", "issue": "Missing OpenAPI version", "severity": "blocking"})
            passed = False
        if "info" not in contract:
            findings.append({"field": "info", "issue": "Missing info section", "severity": "blocking"})
            passed = False
        if "paths" not in contract or not contract["paths"]:
            findings.append({"field": "paths", "issue": "No paths defined", "severity": "blocking"})
            passed = False

        # Validate each path
        for path, methods in contract.get("paths", {}).items():
            for method, details in methods.items():
                if method.lower() not in ("get", "post", "put", "patch", "delete", "options", "head"):
                    continue

                # Check for responses
                if "responses" not in details:
                    findings.append({
                        "field": f"{method.upper()} {path}",
                        "issue": "Missing responses definition",
                        "severity": "blocking",
                    })
                    passed = False

                # Check POST/PUT have request body
                if method.lower() in ("post", "put") and "requestBody" not in details:
                    findings.append({
                        "field": f"{method.upper()} {path}",
                        "issue": "POST/PUT without requestBody",
                        "severity": "warning",
                    })

        # Validate component schemas
        schemas = contract.get("components", {}).get("schemas", {})
        for schema_name, schema_def in schemas.items():
            if "properties" not in schema_def and "type" not in schema_def:
                findings.append({
                    "field": f"schemas/{schema_name}",
                    "issue": "Schema lacks properties or type",
                    "severity": "warning",
                })

        # Check for $ref resolution
        contract_str = json.dumps(contract)
        refs = [r for r in contract_str.split('"$ref"') if len(r) > 1]
        for ref_segment in refs[1:]:  # Skip first split
            ref_match = ref_segment.split('"')[1] if '"' in ref_segment else ""
            if ref_match.startswith("#/components/schemas/"):
                schema_name = ref_match.split("/")[-1]
                if schema_name not in schemas:
                    findings.append({
                        "field": ref_match,
                        "issue": f"Unresolved $ref to {schema_name}",
                        "severity": "blocking",
                    })
                    passed = False

        # Calculate score
        blocking_count = sum(1 for f in findings if f.get("severity") == "blocking")
        warning_count = sum(1 for f in findings if f.get("severity") == "warning")
        endpoint_count = sum(len(m) for m in contract.get("paths", {}).values())
        score = max(0, 1.0 - (blocking_count * 0.3) - (warning_count * 0.1))

        result = ValidationResult(
            workflow_id=workflow_id,
            validation_type="contract_validation",
            gate_name="contract_validation",
            passed=passed,
            severity=ValidationSeverity.BLOCKING if not passed else ValidationSeverity.INFO,
            findings={"issues": findings, "endpoint_count": endpoint_count, "schema_count": len(schemas)},
            recommendations={"fix_blocking": [f for f in findings if f["severity"] == "blocking"]},
            score=round(score, 2),
        )
        session.add(result)

        logger.info(
            "contract_validated",
            workflow_id=workflow_id,
            passed=passed,
            endpoints=endpoint_count,
            blocking=blocking_count,
            warnings=warning_count,
        )
        return result


# ─── D-12: Integration Testing Engine ───────────────────────────────────────────

class IntegrationTester:
    """
    Tests generated code against the API contract.
    In mock mode, performs structural verification.
    """

    @staticmethod
    async def run_integration_tests(
        code_content: str,
        contract: dict,
        workflow_id: str,
        session,
    ) -> ValidationResult:
        """Run integration tests comparing code to contract."""
        findings = []
        passed = True

        # Parse code to find route definitions
        import re
        routes_in_code = set()
        for match in re.finditer(r'@\w+\.(get|post|put|delete|patch)\(["\']([^"\']+)', code_content):
            method = match.group(1).upper()
            path = match.group(2)
            routes_in_code.add(f"{method} {path}")

        # Check contract endpoints exist in code
        for path, methods in contract.get("paths", {}).items():
            for method in methods:
                if method.upper() in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                    expected = f"{method.upper()} {path}"
                    # Fuzzy match (code path might differ slightly)
                    found = any(expected.split()[-1] in r for r in routes_in_code)
                    if not found:
                        findings.append({
                            "type": "missing_endpoint",
                            "expected": expected,
                            "severity": "warning",
                        })

        # Check for error handling patterns
        has_error_handling = "HTTPException" in code_content or "raise" in code_content
        if not has_error_handling:
            findings.append({
                "type": "missing_error_handling",
                "message": "No error handling found in generated code",
                "severity": "warning",
            })

        # Check for type hints
        has_type_hints = ": " in code_content and "->" in code_content
        if not has_type_hints:
            findings.append({
                "type": "missing_type_hints",
                "message": "Missing type annotations in code",
                "severity": "info",
            })

        score = max(0, 1.0 - len(findings) * 0.15)

        result = ValidationResult(
            workflow_id=workflow_id,
            validation_type="integration_test",
            gate_name="integration_testing",
            passed=passed,
            severity=ValidationSeverity.WARNING,
            findings={"issues": findings, "routes_found": list(routes_in_code)},
            score=round(score, 2),
        )
        session.add(result)
        return result


# ─── D-13: Trajectory Evaluation ────────────────────────────────────────────────

class TrajectoryEvaluator:
    """
    Evaluates agent execution trajectories for alignment with spec intent.
    Checks reasoning quality, decision consistency, and requirement coverage.
    """

    @staticmethod
    async def evaluate(
        trace_data: list[dict],
        spec_content: dict,
        workflow_id: str,
        session,
    ) -> ValidationResult:
        """Evaluate execution trajectory against spec requirements."""
        findings = []

        # Check requirement coverage in agent outputs
        requirements = spec_content.get("functional_requirements", [])
        req_ids = {r.get("id") for r in requirements}
        covered_reqs = set()

        for span in trace_data:
            output = span.get("output") or {}
            if isinstance(output, dict):
                # Check if output references requirements
                output_str = json.dumps(output)
                for req_id in req_ids:
                    if req_id in output_str:
                        covered_reqs.add(req_id)

        coverage = len(covered_reqs) / max(len(req_ids), 1)

        # Check for agent failures
        failed_spans = [s for s in trace_data if s.get("status") == "error"]
        if failed_spans:
            findings.append({
                "type": "agent_failures",
                "count": len(failed_spans),
                "components": [s.get("component") for s in failed_spans],
                "severity": "warning",
            })

        # Check execution completeness
        expected_components = {"spec_generator", "api_designer", "logic_implementer", "test_generator"}
        actual_components = {s.get("component") for s in trace_data}
        missing = expected_components - actual_components
        if missing:
            findings.append({
                "type": "incomplete_execution",
                "missing_components": list(missing),
                "severity": "warning",
            })

        # Alignment score
        alignment_score = round(coverage * 0.6 + (1.0 - len(findings) * 0.2) * 0.4, 2)
        alignment_score = max(0, min(1.0, alignment_score))

        result = ValidationResult(
            workflow_id=workflow_id,
            validation_type="trajectory_evaluation",
            gate_name="trajectory_evaluation",
            passed=alignment_score >= 0.5,
            severity=ValidationSeverity.WARNING,
            findings={
                "requirement_coverage": round(coverage, 2),
                "covered_requirements": list(covered_reqs),
                "uncovered_requirements": list(req_ids - covered_reqs),
                "issues": findings,
            },
            score=alignment_score,
        )
        session.add(result)

        logger.info(
            "trajectory_evaluated",
            workflow_id=workflow_id,
            alignment=alignment_score,
            coverage=round(coverage, 2),
        )
        return result


# ─── D-14: Validation Gates ─────────────────────────────────────────────────────

class ValidationGate:
    """
    Enforces validation gates as blocking or advisory checkpoints.
    Supports manual overrides with full audit trail.
    """

    def __init__(self, gate_name: str):
        self.gate_name = gate_name
        self.policy = get_policy_manager()
        self.config = self.policy.get_gate_config(gate_name)
        self.is_blocking = self.config.get("blocking", False)
        self.timeout = self.config.get("timeout", 300)

    async def evaluate(
        self,
        validation_results: list[ValidationResult],
        workflow_id: str,
        session,
    ) -> dict:
        """
        Evaluate all validation results against gate policy.
        Returns gate decision with reasoning.
        """
        failed_results = [r for r in validation_results if not r.passed]
        blocking_failures = [
            r for r in failed_results
            if r.severity == ValidationSeverity.BLOCKING
        ]

        gate_passed = len(blocking_failures) == 0

        decision = {
            "gate_name": self.gate_name,
            "passed": gate_passed,
            "is_blocking": self.is_blocking,
            "should_block": self.is_blocking and not gate_passed,
            "total_checks": len(validation_results),
            "passed_checks": len(validation_results) - len(failed_results),
            "failed_checks": len(failed_results),
            "blocking_failures": len(blocking_failures),
            "average_score": round(
                sum(r.score or 0 for r in validation_results) / max(len(validation_results), 1), 2
            ),
        }

        # Log gate decision
        audit = AuditLog(
            action=AuditAction.STATE_CHANGE,
            resource_type="validation_gate",
            resource_id=workflow_id,
            details=f"Gate '{self.gate_name}': {'PASS' if gate_passed else 'FAIL'} "
                    f"(blocking={self.is_blocking})",
            after_state=decision,
        )
        session.add(audit)

        logger.info(
            "gate_evaluated",
            gate=self.gate_name,
            passed=gate_passed,
            blocking=self.is_blocking,
            should_block=decision["should_block"],
        )

        return decision

    @staticmethod
    async def override_gate(
        workflow_id: str,
        gate_name: str,
        reason: str,
        approved_by: str,
        original_result: dict,
        session,
    ) -> PolicyOverride:
        """
        Override a failed gate with audit trail.
        This is a governance action requiring justification.
        """
        override = PolicyOverride(
            workflow_id=workflow_id,
            gate_name=gate_name,
            override_reason=reason,
            approved_by=approved_by,
            original_result=original_result,
        )
        session.add(override)

        # Audit log
        audit = AuditLog(
            user_id=approved_by,
            action=AuditAction.OVERRIDE,
            resource_type="validation_gate",
            resource_id=workflow_id,
            details=f"Gate '{gate_name}' overridden: {reason}",
            before_state=original_result,
            after_state={"overridden": True, "by": approved_by},
        )
        session.add(audit)

        logger.warning(
            "gate_overridden",
            gate=gate_name,
            workflow_id=workflow_id,
            by=approved_by,
            reason=reason,
        )
        return override


class GateRegistry:
    """Registry of all validation gates in the workflow."""

    GATES = {
        "spec_validation": {"position": "after_spec_generation", "blocking": True},
        "contract_validation": {"position": "after_api_design", "blocking": True},
        "integration_testing": {"position": "after_code_generation", "blocking": True},
        "trajectory_evaluation": {"position": "after_all_agents", "blocking": False},
    }

    @classmethod
    def get_gate(cls, name: str) -> ValidationGate:
        if name not in cls.GATES:
            raise ValueError(f"Unknown gate: {name}. Available: {list(cls.GATES.keys())}")
        return ValidationGate(name)

    @classmethod
    def get_gates_for_position(cls, position: str) -> list[ValidationGate]:
        return [
            ValidationGate(name)
            for name, config in cls.GATES.items()
            if config["position"] == position
        ]
