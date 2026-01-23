#!/usr/bin/env python3
"""
Seed FX rates for testing FX gain/loss calculations

This script seeds the fx_rates table with test data to validate
FX gain/loss calculations for multi-currency accounts.

Usage:
    # Local development
    python scripts/seed_fx_rates.py --env local

    # Staging (requires DATABASE_URL env var)
    DATABASE_URL=... python scripts/seed_fx_rates.py --env staging

    # Production (requires DATABASE_URL env var)
    DATABASE_URL=... python scripts/seed_fx_rates.py --env production
"""

import argparse
import asyncio
import os
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "backend"))

from src.config import settings
from src.models.market_data import FxRate


def get_database_url(env: str) -> str:
    if env in ["staging", "production"]:
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            print(f"❌ DATABASE_URL environment variable required for {env}")
            print("Please set DATABASE_URL and try again")
            print("Example: DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db")
            sys.exit(1)
        return database_url
    else:
        return settings.database_url


async def seed_fx_rates(env: str):
    database_url = get_database_url(env)
    print(
        f"Connecting to {env} database: {database_url.split('@')[1] if '@' in database_url else 'local'}"
    )

    engine = create_async_engine(database_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    rates_to_seed = [
        {
            "base_currency": "USD",
            "quote_currency": "USD",
            "rate": Decimal("1.000000"),
            "rate_date": date(2026, 1, 23),
            "source": "seed",
        },
        {
            "base_currency": "SGD",
            "quote_currency": "SGD",
            "rate": Decimal("1.000000"),
            "rate_date": date(2026, 1, 23),
            "source": "seed",
        },
        {
            "base_currency": "EUR",
            "quote_currency": "EUR",
            "rate": Decimal("1.000000"),
            "rate_date": date(2026, 1, 23),
            "source": "seed",
        },
        {
            "base_currency": "USD",
            "quote_currency": "SGD",
            "rate": Decimal("1.280000"),
            "rate_date": date(2026, 1, 23),
            "source": "seed",
        },
        {
            "base_currency": "USD",
            "quote_currency": "EUR",
            "rate": Decimal("0.852000"),
            "rate_date": date(2026, 1, 23),
            "source": "seed",
        },
        {
            "base_currency": "SGD",
            "quote_currency": "USD",
            "rate": Decimal("0.781250"),
            "rate_date": date(2026, 1, 23),
            "source": "seed",
        },
        {
            "base_currency": "EUR",
            "quote_currency": "USD",
            "rate": Decimal("1.173709"),
            "rate_date": date(2026, 1, 23),
            "source": "seed",
        },
    ]

    async with session_maker() as session:
        existing_check = await session.execute(
            select(FxRate).where(FxRate.rate_date == date(2026, 1, 23))
        )
        existing_rates = existing_check.scalars().all()

        if existing_rates:
            print(f"Found {len(existing_rates)} existing rates for 2026-01-23")
            for rate in existing_rates:
                print(f"  {rate.base_currency}/{rate.quote_currency}: {rate.rate}")

            response = input("Delete existing rates and reseed? (y/N): ")
            if response.lower() != "y":
                print("Aborted")
                return

            delete_stmt = delete(FxRate).where(FxRate.rate_date == date(2026, 1, 23))
            await session.execute(delete_stmt)
            print("Deleted existing rates")

        for rate_data in rates_to_seed:
            fx_rate = FxRate(id=uuid4(), **rate_data, created_at=datetime.now(UTC))
            session.add(fx_rate)
            print(
                f"Added {rate_data['base_currency']}/{rate_data['quote_currency']}: {rate_data['rate']}"
            )

        await session.commit()
        print(f"\nSeeded {len(rates_to_seed)} FX rates for {env} environment")

        print("\n--- Expected FX Calculation ---")
        print("Historical cost: 10,000 USD @ 1.25 = 12,500 SGD")
        print("Current value: 10,000 USD @ 1.28 = 12,800 SGD")
        print("Unrealized FX gain: 300 SGD")
        print("-------------------------------")

    await engine.dispose()


def main():
    parser = argparse.ArgumentParser(
        description="Seed FX rates for FX gain/loss testing"
    )
    parser.add_argument(
        "--env",
        choices=["local", "staging", "production"],
        default="local",
        help="Target environment (default: local)",
    )

    args = parser.parse_args()

    print(f"Seeding FX rates for environment: {args.env}")

    try:
        asyncio.run(seed_fx_rates(args.env))
        print("✅ FX rates seeded successfully")
    except Exception as e:
        print(f"❌ Error seeding FX rates: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
