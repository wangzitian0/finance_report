"""
Synthetic statement generators for benchmark scenarios.

Generates deterministic CSV banking statements for financial scenario assertions.
"""

from __future__ import annotations

from decimal import Decimal


def generate_standard_operations_csv(
    opening_balance: Decimal = Decimal("10000.00"),
) -> bytes:
    """Generate standard operations CSV statement rows representing balanced revenue and expenses."""
    closing_balance = opening_balance + Decimal("2800.00")
    lines = [
        "Statement Currency,Statement Period Start,Statement Period End,Statement Opening Balance,Statement Closing Balance,Date,Description,Amount",
        f"SGD,2025-04-01,2025-04-30,{opening_balance:.2f},{closing_balance:.2f},2025-04-05,CONSULTING SERVICES REVENUE,5000.00",
        f"SGD,2025-04-01,2025-04-30,{opening_balance:.2f},{closing_balance:.2f},2025-04-10,COMMERCIAL OFFICE LEASE RENT,-1500.00",
        f"SGD,2025-04-01,2025-04-30,{opening_balance:.2f},{closing_balance:.2f},2025-04-15,AWS CLOUD HOSTING AND SAAS,-500.00",
        f"SGD,2025-04-01,2025-04-30,{opening_balance:.2f},{closing_balance:.2f},2025-04-20,BUSINESS CLIENT DINING DINNER,-200.00",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def generate_household_wife_operations_csv(
    opening_balance: Decimal = Decimal("5000.00"),
) -> bytes:
    """Generate wife's operating CSV statement rows representing household salary and daily living expenses."""
    closing_balance = opening_balance + Decimal("3100.00")
    lines = [
        "Statement Currency,Statement Period Start,Statement Period End,Statement Opening Balance,Statement Closing Balance,Date,Description,Amount",
        f"SGD,2025-04-01,2025-04-30,{opening_balance:.2f},{closing_balance:.2f},2025-04-08,TECH ENTERPRISE PAYROLL SALARY,3500.00",
        f"SGD,2025-04-01,2025-04-30,{opening_balance:.2f},{closing_balance:.2f},2025-04-16,NTUC FAIRPRICE GROCERIES,-250.00",
        f"SGD,2025-04-01,2025-04-30,{opening_balance:.2f},{closing_balance:.2f},2025-04-24,SP SERVICES RESIDENTIAL UTILITIES,-150.00",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def generate_credit_card_repayment_bank_csv(
    opening_balance: Decimal = Decimal("10000.00"),
) -> bytes:
    """Generate bank statement CSV rows representing a 1,200 SGD credit card debt repayment."""
    repayment_amount = Decimal("1200.00")
    closing_balance = opening_balance - repayment_amount
    lines = [
        "Statement Currency,Statement Period Start,Statement Period End,Statement Opening Balance,Statement Closing Balance,Date,Description,Amount",
        f"SGD,2025-04-01,2025-04-30,{opening_balance:.2f},{closing_balance:.2f},2025-04-20,PAYMENT TO CITI CREDIT CARD 4321,-1200.00",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def generate_multicurrency_usd_csv(
    opening_balance: Decimal = Decimal("5000.00"),
) -> bytes:
    """Generate US Dollar operating CSV statement rows."""
    closing_balance = opening_balance + Decimal("1800.00")
    lines = [
        "Statement Currency,Statement Period Start,Statement Period End,Statement Opening Balance,Statement Closing Balance,Date,Description,Amount",
        f"USD,2025-04-01,2025-04-30,{opening_balance:.2f},{closing_balance:.2f},2025-04-05,US CLIENT CONSULTING RETAINER,2000.00",
        f"USD,2025-04-01,2025-04-30,{opening_balance:.2f},{closing_balance:.2f},2025-04-20,GLOBAL INFRASTRUCTURE SUBSCRIPTION,-200.00",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def generate_multicurrency_hkd_csv(
    opening_balance: Decimal = Decimal("20000.00"),
) -> bytes:
    """Generate Hong Kong Dollar operating CSV statement rows."""
    closing_balance = opening_balance + Decimal("4000.00")
    lines = [
        "Statement Currency,Statement Period Start,Statement Period End,Statement Opening Balance,Statement Closing Balance,Date,Description,Amount",
        f"HKD,2025-04-01,2025-04-30,{opening_balance:.2f},{closing_balance:.2f},2025-04-10,GREATER CHINA TECH DIVIDEND,5000.00",
        f"HKD,2025-04-01,2025-04-30,{opening_balance:.2f},{closing_balance:.2f},2025-04-25,HK CUSTODIAN AND ACCOUNT FEE,-1000.00",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def generate_consecutive_month1_csv(
    opening_balance: Decimal = Decimal("15450.75"),
) -> bytes:
    """Generate Month 1 (Jan 2025) statement rows."""
    closing_balance = opening_balance - Decimal("179.52")
    lines = [
        "Statement Currency,Statement Period Start,Statement Period End,Statement Opening Balance,Statement Closing Balance,Date,Description,Amount",
        f"SGD,2025-01-01,2025-01-31,{opening_balance:.2f},{closing_balance:.2f},2025-01-15,TECH CORP SALARY JAN,5000.00",
        f"SGD,2025-01-01,2025-01-31,{opening_balance:.2f},{closing_balance:.2f},2025-01-20,LIVING EXPENSES AND UTILITIES,-5179.52",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def generate_consecutive_month2_csv(
    opening_balance: Decimal = Decimal("15271.23"),
) -> bytes:
    """Generate Month 2 (Feb 2025) statement rows."""
    closing_balance = opening_balance + Decimal("2978.77")
    lines = [
        "Statement Currency,Statement Period Start,Statement Period End,Statement Opening Balance,Statement Closing Balance,Date,Description,Amount",
        f"SGD,2025-02-01,2025-02-28,{opening_balance:.2f},{closing_balance:.2f},2025-02-15,TECH CORP SALARY FEB,5000.00",
        f"SGD,2025-02-01,2025-02-28,{opening_balance:.2f},{closing_balance:.2f},2025-02-20,ANNUAL BONUS PAYMENT,1000.00",
        f"SGD,2025-02-01,2025-02-28,{opening_balance:.2f},{closing_balance:.2f},2025-02-25,LIVING EXPENSES AND DINING,-3021.23",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def generate_consecutive_month3_csv(
    opening_balance: Decimal = Decimal("18250.00"),
) -> bytes:
    """Generate Month 3 (Mar 2025) statement rows."""
    closing_balance = opening_balance + Decimal("3050.00")
    lines = [
        "Statement Currency,Statement Period Start,Statement Period End,Statement Opening Balance,Statement Closing Balance,Date,Description,Amount",
        f"SGD,2025-03-01,2025-03-31,{opening_balance:.2f},{closing_balance:.2f},2025-03-15,TECH CORP SALARY MAR,5000.00",
        f"SGD,2025-03-01,2025-03-31,{opening_balance:.2f},{closing_balance:.2f},2025-03-25,LIVING EXPENSES AND RENT,-1950.00",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def generate_consecutive_month4_csv(
    opening_balance: Decimal = Decimal("21300.00"),
) -> bytes:
    """Generate Month 4 (Apr 2025) statement rows."""
    closing_balance = opening_balance + Decimal("2900.00")
    lines = [
        "Statement Currency,Statement Period Start,Statement Period End,Statement Opening Balance,Statement Closing Balance,Date,Description,Amount",
        f"SGD,2025-04-01,2025-04-30,{opening_balance:.2f},{closing_balance:.2f},2025-04-15,TECH CORP SALARY APR,5000.00",
        f"SGD,2025-04-01,2025-04-30,{opening_balance:.2f},{closing_balance:.2f},2025-04-25,LIVING EXPENSES AND BILLS,-2100.00",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")
