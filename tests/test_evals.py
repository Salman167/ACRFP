"""Golden-set evals — CI-safe with mock LLM and in-process guardrail."""

import os

os.environ["LLM_PROVIDER"] = "mock"
os.environ["POLICY_PACK"] = "local"
os.environ["GUARDRAIL_URL"] = "http://127.0.0.1:9"
os.environ["EXECUTOR_URL"] = "http://127.0.0.1:9"

from shared.config import get_settings

get_settings.cache_clear()

from evals.harness import load_golden_cases, run_eval_suite


def test_golden_suite_is_defined():
    cases = load_golden_cases()
    ids = {c["id"] for c in cases}
    assert {
        "reliability_restart_allow",
        "cost_idle_requires_approval",
        "protected_namespace_dual_approval",
        "sovereign_region_deny",
        "cpu_scale_out_allow",
    } <= ids


def test_golden_suite_passes_on_mock():
    report = run_eval_suite()
    failed = [c["id"] for c in report["cases"] if not c["passed"]]
    assert report["passed"], f"failed cases: {failed} score={report['score']}"
    assert report["score"] == 1.0
    assert report["cases_total"] >= 5
