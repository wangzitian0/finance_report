"""Locust performance test suite for Finance Report API.

Run with:
    locust -f apps/backend/tests/locustfile.py --host=http://localhost:8000

For headless mode:
    locust -f apps/backend/tests/locustfile.py --host=http://localhost:8000 --users 10 --spawn-rate 2 --run-time 1m --headless

For staging:
    locust -f apps/backend/tests/locustfile.py --host=https://report-staging.zitian.party --users 50 --spawn-rate 5 --run-time 5m
"""

import os
import random
from io import BytesIO

from locust import HttpUser, between, events, task
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from src.logger import get_logger

logger = get_logger(__name__)


def generate_test_pdf() -> BytesIO:
    """Generate a minimal PDF for statement upload testing."""
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    p.drawString(100, 750, "Bank Statement")
    p.drawString(100, 730, "Account: 1234567890")
    p.drawString(100, 710, "Date: 2024-01-15")
    p.drawString(100, 690, "Transaction: Purchase at Store - $50.00")
    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer


class FinanceReportUser(HttpUser):
    """Simulated user performing typical Finance Report operations."""

    wait_time = between(1, 3)

    def on_start(self) -> None:
        """Set up test user authentication."""
        # Note: Performance tests now require a valid JWT token.
        # Use TEST_USER_TOKEN env var to provide it.
        token = os.getenv("TEST_USER_TOKEN", "mock-token-not-for-prod")
        self.client.headers = {"Authorization": f"Bearer {token}"}

    @task(5)
    def view_dashboard(self) -> None:
        """GET /api/health - Most frequent operation."""
        self.client.get("/api/health")

    @task(3)
    def list_accounts(self) -> None:
        """GET /api/accounts - List user accounts."""
        with self.client.get("/api/accounts", catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code in (401, 403):
                logger.warning(f"Auth failed in load test: {response.status_code}")
                response.failure(f"Auth failed: {response.status_code}")
            else:
                logger.error(
                    "Unexpected status in load test",
                    extra={"endpoint": "/api/accounts", "status": response.status_code},
                )
                response.failure(f"Unexpected: {response.status_code}")

    @task(2)
    def list_journal_entries(self) -> None:
        """GET /api/journal - List journal entries."""
        params = {"skip": random.randint(0, 100), "limit": 20}
        with self.client.get("/api/journal", params=params, catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code in (401, 403):
                logger.warning(f"Auth failed in load test: {response.status_code}")
                response.failure(f"Auth failed: {response.status_code}")
            else:
                logger.error("Unexpected status", extra={"endpoint": "/api/journal", "status": response.status_code})
                response.failure(f"Unexpected: {response.status_code}")

    @task(1)
    def upload_statement(self) -> None:
        """POST /api/statements/upload - Upload bank statement (expensive operation)."""
        pdf_buffer = generate_test_pdf()

        files = {"file": ("test_statement.pdf", pdf_buffer, "application/pdf")}
        data = {
            "institution": "Test Bank",
            "account_number": f"ACC{random.randint(1000, 9999)}",
            "account_name": "Test Account",
        }

        with self.client.post(
            "/api/statements/upload", files=files, data=data, catch_response=True, timeout=60
        ) as response:
            if response.status_code == 201:
                response.success()
            elif response.status_code == 400:
                logger.warning(f"Validation failed: {response.text[:200]}")
                response.failure(f"Validation failed: {response.text[:200]}")
            elif response.status_code in (401, 403):
                logger.warning(f"Auth failed: {response.status_code}")
                response.failure(f"Auth failed: {response.status_code}")
            elif response.status_code == 429:
                logger.warning("Rate limited")
                response.failure("Rate limited")
            elif response.status_code >= 500:
                logger.error("Server error", extra={"status": response.status_code})
                response.failure(f"Server error: {response.status_code}")
            else:
                logger.error("Unexpected status", extra={"status": response.status_code})
                response.failure(f"Unexpected: {response.status_code}")

    @task(2)
    def run_reconciliation(self) -> None:
        """POST /api/reconciliation/run - Run reconciliation matching."""
        with self.client.post("/api/reconciliation/run", catch_response=True, timeout=30) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code in (401, 403):
                logger.warning(f"Auth failed: {response.status_code}")
                response.failure(f"Auth failed: {response.status_code}")
            elif response.status_code == 429:
                logger.warning("Rate limited")
                response.failure("Rate limited")
            else:
                logger.error(
                    "Unexpected status", extra={"endpoint": "/api/reconciliation/run", "status": response.status_code}
                )
                response.failure(f"Unexpected: {response.status_code}")

    @task(3)
    def view_reconciliation_stats(self) -> None:
        """GET /api/reconciliation/stats - View reconciliation statistics."""
        with self.client.get("/api/reconciliation/stats", catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code in (401, 403):
                logger.warning(f"Auth failed: {response.status_code}")
                response.failure(f"Auth failed: {response.status_code}")
            else:
                logger.error(
                    "Unexpected status",
                    extra={"endpoint": "/api/reconciliation/stats", "status": response.status_code},
                )
                response.failure(f"Unexpected: {response.status_code}")

    @task(2)
    def view_reports(self) -> None:
        """GET /api/reports/* - Generate financial reports."""
        report_type = random.choice(["balance-sheet", "income-statement", "trial-balance"])
        endpoint = f"/api/reports/{report_type}"

        params = {"as_of_date": "2024-01-31"}

        with self.client.get(endpoint, params=params, catch_response=True, timeout=30) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code in (401, 403):
                logger.warning(f"Auth failed: {response.status_code}")
                response.failure(f"Auth failed: {response.status_code}")
            else:
                logger.error("Unexpected status", extra={"endpoint": endpoint, "status": response.status_code})
                response.failure(f"Unexpected: {response.status_code}")


@events.quitting.add_listener
def _(environment, **kwargs) -> None:
    """Print performance summary on quit."""
    if environment.stats.total.fail_ratio > 0.05:
        logger.error(
            "Performance test FAILED",
            extra={
                "error_rate": environment.stats.total.fail_ratio,
                "avg_response_time": environment.stats.total.avg_response_time,
                "threshold": "5%",
            },
        )
        print(f"\n❌ FAIL: Error rate {environment.stats.total.fail_ratio:.2%} exceeds 5%")
        environment.process_exit_code = 1
    elif environment.stats.total.avg_response_time > 2000:
        logger.warning(
            "Performance test WARNING",
            extra={
                "error_rate": environment.stats.total.fail_ratio,
                "avg_response_time": environment.stats.total.avg_response_time,
                "threshold": "2000ms",
            },
        )
        print(f"\n⚠️  WARNING: Avg response time {environment.stats.total.avg_response_time:.0f}ms exceeds 2s")
    else:
        logger.info(
            "Performance test PASSED",
            extra={
                "error_rate": environment.stats.total.fail_ratio,
                "avg_response_time": environment.stats.total.avg_response_time,
            },
        )
        print(
            f"\n✅ PASS: Error rate {environment.stats.total.fail_ratio:.2%}, Avg {environment.stats.total.avg_response_time:.0f}ms"
        )
