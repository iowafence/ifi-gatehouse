# tests

Python tests. The backend suite is run with `python3 harness/run_safe_suite.py .` (standard library only; the three PyMuPDF tests skip when it is not installed). `python -m unittest discover -s tests` also works. Browser suites live in `e2e/` and need Playwright.

- Engine and workflow: `test_engine.py`, `test_input_guards.py`, `test_labor_gate.py`
- API and demo sessions: `test_api.py`, `test_demo_routes.py`
- Portfolio, crews and pricing: `test_portfolio.py`, `test_crew_plans.py`, `test_pricing_*.py`, `test_footing_*.py`
- Intake: `test_intake.py`
- Repository guardrails: `test_repo_policy.py` runs the secret scanner, commit-message policy and link checker against throwaway repositories with planted violations.
