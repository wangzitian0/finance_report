"""Generate fictional transaction data for test PDFs."""
import random
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Dict, Any


def generate_dbs_transactions(
    start_date: datetime,
    count: int = 15,
    opening_balance: Decimal = Decimal("5000.00"),
) -> tuple[List[Dict[str, Any]], Decimal]:
    """
    Generate fictional DBS transactions.
    
    Returns:
        (transactions, closing_balance)
    """
    descriptions = [
        ("GRAB RIDE", -15, -30),
        ("STARBUCKS COFFEE", -5, -10),
        ("NETFLIX SUBSCRIPTION", -15.90, -15.90),
        ("SALARY", 3000, 5000),
        ("NTUC FAIRPRICE", -50, -150),
        ("SPOTIFY", -9.90, -9.90),
        ("RESTAURANT PAYMENT", -40, -120),
        ("TRANSFER FROM FRIEND", 10, 50),
        ("ATM WITHDRAWAL", -100, -200),
        ("PAYNOW PAYMENT", -20, -50),
        ("GIRO PAYMENT", -100, -300),
        ("INTEREST EARNED", 0.50, 2.00),
    ]
    
    txns = []
    balance = opening_balance
    current_date = start_date
    
    for _ in range(count):
        # Advance date by 0-3 days
        current_date += timedelta(days=random.randint(0, 3))
        
        desc, min_amt, max_amt = random.choice(descriptions)
        
        # Generate random amount
        if min_amt == max_amt:
            amount = Decimal(str(min_amt))
        else:
            # Ensure min < max for randint
            min_val = min(min_amt, max_amt)
            max_val = max(min_amt, max_amt)
            min_cents = int(min_val * 100)
            max_cents = int(max_val * 100)
            cents = random.randint(min_cents, max_cents)
            amount = Decimal(cents) / Decimal(100)
        
        balance += amount
        
        txn = {
            "date": current_date.strftime("%d/%m/%Y"),
            "description": desc,
            "withdrawal": f"{abs(amount):.2f}" if amount < 0 else "",
            "deposit": f"{amount:.2f}" if amount > 0 else "",
            "balance": f"{balance:.2f}",
            "amount": amount,  # For internal calculation
        }
        txns.append(txn)
    
    return txns, balance


def generate_cmb_transactions(
    start_date: datetime,
    count: int = 20,
    opening_balance: Decimal = Decimal("10000.00"),
) -> tuple[List[Dict[str, Any]], Decimal]:
    """
    Generate fictional CMB transactions.
    
    Returns:
        (transactions, closing_balance)
    """
    descriptions = [
        ("工资代发", 5000, 20000),
        ("转账汇款", -100, -5000),
        ("快捷支付", -50, -500),
        ("信用卡预约还款", -500, -2000),
        ("账户结息", 1.00, 10.00),
        ("汇入汇款", 1000, 5000),
        ("银证转账", -1000, -5000),
        ("基金赎回", 2000, 10000),
        ("网联收款", 100, -100),  # Can be positive or negative
    ]
    
    txns = []
    balance = opening_balance
    current_date = start_date
    
    for _ in range(count):
        current_date += timedelta(days=random.randint(0, 2))
        
        desc, min_amt, max_amt = random.choice(descriptions)
        
        # Generate amount (can be positive or negative for some types)
        if "网联收款" in desc:
            # Can be either direction
            max_val = abs(max_amt)
            amount = Decimal(random.randint(-max_val, max_val))
        else:
            if min_amt == max_amt:
                amount = Decimal(str(min_amt))
            else:
                # Ensure min < max for randint
                min_val = min(min_amt, max_amt)
                max_val = max(min_amt, max_amt)
                min_cents = int(min_val)
                max_cents = int(max_val)
                cents = random.randint(min_cents, max_cents)
                amount = Decimal(cents)
        
        balance += amount
        
        txn = {
            "date": current_date.strftime("%Y-%m-%d"),
            "currency": "CNY",
            "amount": f"{amount:,.2f}",
            "balance": f"{balance:,.2f}",
            "description": desc,
            "counterparty": "测试用户" if amount > 0 else "测试商户",
            "amount_decimal": amount,  # For internal calculation
        }
        txns.append(txn)
    
    return txns, balance


def generate_mari_transactions(
    start_date: datetime,
    count: int = 12,
    opening_balance: Decimal = Decimal("3000.00"),
) -> tuple[List[Dict[str, Any]], Decimal]:
    """
    Generate fictional Mari Bank transactions.
    
    Returns:
        (transactions, closing_balance)
    """
    descriptions = [
        ("Outward Transfer to DBS", -100, -500),
        ("Inward Transfer from Salary", 2000, 4000),
        ("PayNow Payment", -20, -100),
        ("Interest Credit", 0.50, 2.00),
    ]
    
    txns = []
    balance = opening_balance
    current_date = start_date
    
    for _ in range(count):
        current_date += timedelta(days=random.randint(1, 3))
        
        desc, min_amt, max_amt = random.choice(descriptions)
        
        if min_amt == max_amt:
            amount = Decimal(str(min_amt))
        else:
            # Ensure min < max for randint
            min_val = min(min_amt, max_amt)
            max_val = max(min_amt, max_amt)
            min_cents = int(min_val * 100)
            max_cents = int(max_val * 100)
            cents = random.randint(min_cents, max_cents)
            amount = Decimal(cents) / Decimal(100)
        
        # Determine if outgoing or incoming
        is_outgoing = amount < 0 or "Outward" in desc or "Payment" in desc
        is_incoming = amount > 0 and ("Inward" in desc or "Interest" in desc)
        
        balance += amount
        
        txn = {
            "date": current_date.strftime("%d %b").upper(),  # "15 JAN"
            "description": desc,
            "outgoing": f"{abs(amount):.2f}" if is_outgoing else "",
            "incoming": f"{amount:.2f}" if is_incoming else "",
            "amount": amount,  # For internal calculation
        }
        txns.append(txn)
    
    return txns, balance


def generate_moomoo_transactions(
    start_date: datetime,
    count: int = 10,
    opening_balance: Decimal = Decimal("10000.00"),
) -> tuple[List[Dict[str, Any]], Decimal]:
    """
    Generate fictional Moomoo brokerage transactions.
    
    Returns:
        (transactions, closing_balance)
    """
    transaction_types = [
        ("DEPOSIT", 1000, 5000),
        ("WITHDRAWAL", -500, -2000),
        ("DIVIDEND", 10, 100),
        ("INTEREST", 1.00, 5.00),
        ("FEE", -1.00, -10.00),
    ]
    
    txns = []
    balance = opening_balance
    current_date = start_date
    
    for _ in range(count):
        current_date += timedelta(days=random.randint(1, 5))
        
        txn_type, min_amt, max_amt = random.choice(transaction_types)
        
        if min_amt == max_amt:
            amount = Decimal(str(min_amt))
        else:
            # Ensure min < max for randint
            min_val = min(min_amt, max_amt)
            max_val = max(min_amt, max_amt)
            min_cents = int(min_val * 100)
            max_cents = int(max_val * 100)
            cents = random.randint(min_cents, max_cents)
            amount = Decimal(cents) / Decimal(100)
        
        balance += amount
        
        txn = {
            "date": current_date.strftime("%Y-%m-%d"),
            "type": txn_type,
            "description": f"{txn_type} Transaction",
            "amount": f"{amount:,.2f}",
            "currency": "USD",
            "amount_decimal": amount,  # For internal calculation
        }
        txns.append(txn)
    
    return txns, balance


def generate_pingan_transactions(
    start_date: datetime,
    count: int = 15,
    opening_balance: Decimal = Decimal("8000.00"),
) -> tuple[List[Dict[str, Any]], Decimal]:
    """
    Generate fictional Pingan (平安银行) transactions.
    
    Returns:
        (transactions, closing_balance)
    """
    descriptions = [
        ("工资代发", 5000, 15000),
        ("转账汇款", -200, -2000),
        ("快捷支付", -50, -500),
        ("信用卡还款", -500, -3000),
        ("账户结息", 1.00, 10.00),
        ("基金申购", -1000, -5000),
        ("基金赎回", 1000, 5000),
    ]
    
    txns = []
    balance = opening_balance
    current_date = start_date
    
    for _ in range(count):
        current_date += timedelta(days=random.randint(0, 2))
        
        desc, min_amt, max_amt = random.choice(descriptions)
        
        if min_amt == max_amt:
            amount = Decimal(str(min_amt))
        else:
            # Ensure min < max for randint
            min_val = min(min_amt, max_amt)
            max_val = max(min_amt, max_amt)
            min_cents = int(min_val)
            max_cents = int(max_val)
            cents = random.randint(min_cents, max_cents)
            amount = Decimal(cents)
        
        balance += amount
        
        # Determine transaction type
        if "工资" in desc or "结息" in desc or "赎回" in desc:
            txn_type = "收入"
        elif "还款" in desc or "支付" in desc or "申购" in desc:
            txn_type = "支出"
        else:
            txn_type = "转账"
        
        txn = {
            "date": current_date.strftime("%Y-%m-%d"),
            "type": txn_type,
            "amount": f"{amount:,.2f}",
            "balance": f"{balance:,.2f}",
            "description": desc,
            "amount_decimal": amount,  # For internal calculation
        }
        txns.append(txn)
    
    return txns, balance
