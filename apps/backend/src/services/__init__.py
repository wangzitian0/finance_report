"""Services package."""

from src.services.account_service import (
    AccountNotFoundError,
    AccountServiceError,
    create_account,
    get_account,
    list_accounts,
    update_account,
)
from src.services.accounting import (
    AccountingError,
    ValidationError,
    calculate_account_balance,
    post_journal_entry,
    validate_fx_rates,
    validate_journal_balance,
    verify_accounting_equation,
    void_journal_entry,
)
from src.services.ai_advisor import AIAdvisorError, AIAdvisorService
from src.services.extraction import ExtractionError, ExtractionService
from src.services.fx import (
    FxRateError,
    convert_amount,
    convert_to_base,
    get_average_rate,
    get_exchange_rate,
)
from src.services.reconciliation import execute_matching, load_reconciliation_config
from src.services.reporting import (
    ReportError,
    generate_balance_sheet,
    generate_cash_flow,
    generate_income_statement,
    get_account_trend,
    get_category_breakdown,
)
from src.services.storage import StorageError, StorageService

__all__ = [
    "AccountNotFoundError",
    "AccountServiceError",
    "create_account",
    "get_account",
    "list_accounts",
    "update_account",
    "AccountingError",
    "AIAdvisorError",
    "AIAdvisorService",
    "ExtractionError",
    "ExtractionService",
    "ValidationError",
    "calculate_account_balance",
    "post_journal_entry",
    "validate_fx_rates",
    "validate_journal_balance",
    "verify_accounting_equation",
    "void_journal_entry",
    "execute_matching",
    "FxRateError",
    "convert_amount",
    "convert_to_base",
    "load_reconciliation_config",
    "get_average_rate",
    "get_exchange_rate",
    "ReportError",
    "generate_balance_sheet",
    "generate_cash_flow",
    "generate_income_statement",
    "get_account_trend",
    "get_category_breakdown",
    "StorageError",
    "StorageService",
]
