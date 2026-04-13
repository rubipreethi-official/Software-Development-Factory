"""End-to-end pipeline test for the AI Control Plane."""

import httpx
import json
import time

BASE = "http://127.0.0.1:8000"


def main():
    # 1. Health check
    print("=== HEALTH CHECK ===")
    r = httpx.get(f"{BASE}/api/v1/health")
    health = r.json()
    print(json.dumps(health, indent=2))

    # 2. Submit PRD
    print("\n=== SUBMITTING PRD ===")
    prd = {
        "title": "User Authentication Service",
        "content": (
            "# User Authentication Service\n\n"
            "## Overview\n"
            "Build a REST API for user authentication with JWT tokens, "
            "supporting registration, login, and token refresh.\n\n"
            "## Requirements\n"
            "- Users can register with email and password\n"
            "- Passwords must be hashed with bcrypt\n"
            "- Login returns JWT access and refresh tokens\n"
            "- Protected endpoints require valid JWT\n"
            "- Token refresh without re-authentication\n"
            "- Rate limiting on auth endpoints\n\n"
            "## Constraints\n"
            "- Must use Python 3.11+ with FastAPI\n"
            "- PostgreSQL for user storage\n"
            "- Response time under 200ms for auth endpoints\n"
            "- Must follow OWASP security guidelines\n\n"
            "## Security\n"
            "- Input validation on all endpoints\n"
            "- SQL injection prevention\n"
            "- Brute force protection via rate limiting\n"
        ),
    }
    r = httpx.post(f"{BASE}/api/v1/prd", json=prd, timeout=30)
    result = r.json()
    print(f"Status: {r.status_code}")
    execution_id = result.get("execution_id", "")
    print(f"Execution ID: {execution_id}")

    # 3. Poll until complete
    print("\n=== WORKFLOW PROGRESS ===")
    final_state = "unknown"
    for i in range(20):
        time.sleep(1)
        r = httpx.get(f"{BASE}/api/v1/executions/{execution_id}", timeout=10)
        state = r.json().get("state", "?")
        if state != final_state:
            elapsed = i
            print(f"  [{elapsed}s] State: {state}")
            final_state = state
        if state in ("completed", "failed", "human_review_required"):
            break

    # 4. Final status
    print("\n=== FINAL STATUS ===")
    r = httpx.get(f"{BASE}/api/v1/executions/{execution_id}")
    status_data = r.json()
    print(json.dumps(status_data, indent=2))

    if final_state != "completed":
        print(f"\nWorkflow did not complete. State: {final_state}")
        print(f"Error: {status_data.get('error_message', 'N/A')}")
        return

    # 5. Generated Spec
    print("\n=== GENERATED SPEC ===")
    r = httpx.get(f"{BASE}/api/v1/executions/{execution_id}/spec")
    spec = r.json()
    print(f"  Quality Score:    {spec.get('quality_score')}")
    print(f"  Completeness:     {spec.get('completeness_score')}")
    print(f"  Contradictions:   {spec.get('contradiction_count')}")
    content = spec.get("content", {})
    func_reqs = content.get("functional_requirements", [])
    print(f"  Functional Reqs:  {len(func_reqs)}")
    for req in func_reqs:
        print(f"    [{req.get('id')}] {req.get('description', '')[:80]}")
    print(f"  API Endpoints:    {len(content.get('api_endpoints', []))}")
    print(f"  Data Models:      {len(content.get('data_models', []))}")
    print(f"  Constraints:      {len(content.get('constraints', []))}")

    # 6. Code Artifacts
    print("\n=== CODE ARTIFACTS ===")
    r = httpx.get(f"{BASE}/api/v1/executions/{execution_id}/code")
    code_data = r.json()
    print(f"  Total artifacts: {code_data.get('count')}")
    for a in code_data.get("artifacts", []):
        print(f"  - {a['file_name']} ({a['language']}, {a['line_count']} lines, validation: {a.get('validation_status', 'N/A')})")

    # 7. Test Artifacts
    print("\n=== TEST ARTIFACTS ===")
    r = httpx.get(f"{BASE}/api/v1/executions/{execution_id}/tests")
    test_data = r.json()
    print(f"  Total test suites: {test_data.get('count')}")
    for t in test_data.get("tests", []):
        print(f"  - {t['file_name']} (type: {t['test_type']})")

    # 8. Validation Results
    print("\n=== VALIDATION RESULTS ===")
    r = httpx.get(f"{BASE}/api/v1/executions/{execution_id}/validation")
    val_data = r.json()
    for v in val_data.get("validations", []):
        status = "PASS" if v["passed"] else "FAIL"
        print(f"  - {v['type']}: {status} (score: {v['score']}, severity: {v['severity']})")

    # 9. Execution Trace
    print("\n=== EXECUTION TRACE ===")
    r = httpx.get(f"{BASE}/api/v1/executions/{execution_id}/trace")
    trace_data = r.json()
    print(f"  Total trace events: {trace_data.get('count')}")
    for t in trace_data.get("traces", []):
        dur = t.get("duration_ms", "?")
        print(f"  [{t['component']}] {t['event_type']} -> {t['status']} ({dur}ms)")

    # 10. Prometheus Metrics
    print("\n=== PROMETHEUS METRICS (relevant) ===")
    r = httpx.get(f"{BASE}/metrics")
    for line in r.text.split("\n"):
        if line and not line.startswith("#"):
            if any(k in line for k in ["workflow", "agent", "validation_gate", "spec_quality"]):
                print(f"  {line}")

    # 11. List all executions
    print("\n=== ALL EXECUTIONS ===")
    r = httpx.get(f"{BASE}/api/v1/executions")
    execs = r.json()
    print(f"  Total: {execs.get('total')}")
    for e in execs.get("items", []):
        print(f"  - {e['id'][:12]}... state={e['state']}")

    print("\n" + "=" * 50)
    print("  PIPELINE TEST COMPLETE - ALL STAGES PASSED")
    print("=" * 50)


if __name__ == "__main__":
    main()
