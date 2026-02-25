import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from httpx import AsyncClient
from uuid import uuid4, UUID
from datetime import date
from decimal import Decimal

from src.models import JournalEntry, JournalEntryStatus, JournalLine, User, Account, AccountType
from src.schemas import JournalEntryCreate, VoidJournalEntryRequest, JournalLineCreate

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def test_accounts(db: AsyncSession, test_user: User):
    """Create test accounts for journal entries."""
    accounts = []

    # Create a cash account (ASSET)
    cash_account = Account(
        id=uuid4(),
        user_id=test_user.id,
        name="Cash",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(cash_account)
    accounts.append(cash_account)

    # Create an income account
    income_account = Account(
        id=uuid4(),
        user_id=test_user.id,
        name="Service Income",
        type=AccountType.INCOME,
        currency="SGD",
    )
    db.add(income_account)
    accounts.append(income_account)

    await db.commit()
    for acc in accounts:
        await db.refresh(acc)

    return accounts


@pytest.fixture
async def test_entries(db: AsyncSession, test_user: User, test_accounts: list[Account]):
    """Create test journal entries for testing."""
    entries = []

    # Create a draft entry with lines
    draft_entry = JournalEntry(
        id=uuid4(),
        user_id=test_user.id,
        entry_date=date(2023, 1, 15),
        memo="Test draft entry",
        status=JournalEntryStatus.DRAFT,
    )
    db.add(draft_entry)
    await db.flush()

    # Add balanced lines
    draft_line_debit = JournalLine(
        id=uuid4(),
        journal_entry_id=draft_entry.id,
        account_id=test_accounts[0].id,
        direction="DEBIT",
        amount=Decimal("100.00"),
        currency="SGD",
    )
    draft_line_credit = JournalLine(
        id=uuid4(),
        journal_entry_id=draft_entry.id,
        account_id=test_accounts[1].id,
        direction="CREDIT",
        amount=Decimal("100.00"),
        currency="SGD",
    )
    db.add(draft_line_debit)
    db.add(draft_line_credit)
    entries.append(draft_entry)

    # Create a posted entry with lines
    posted_entry = JournalEntry(
        id=uuid4(),
        user_id=test_user.id,
        entry_date=date(2023, 1, 16),
        memo="Test posted entry",
        status=JournalEntryStatus.POSTED,
    )
    db.add(posted_entry)
    await db.flush()

    # Add balanced lines
    posted_line_debit = JournalLine(
        id=uuid4(),
        journal_entry_id=posted_entry.id,
        account_id=test_accounts[0].id,
        direction="DEBIT",
        amount=Decimal("200.00"),
        currency="SGD",
    )
    posted_line_credit = JournalLine(
        id=uuid4(),
        journal_entry_id=posted_entry.id,
        account_id=test_accounts[1].id,
        direction="CREDIT",
        amount=Decimal("200.00"),
        currency="SGD",
    )
    db.add(posted_line_debit)
    db.add(posted_line_credit)
    entries.append(posted_entry)

    await db.commit()
    for entry in entries:
        await db.refresh(entry, ["lines"])

    return entries


@pytest.mark.asyncio
async def test_create_journal_entry(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
    test_accounts: list[Account],
):
    """Test creating a journal entry."""
    # GIVEN: Valid balanced journal entry data
    entry_data = {
        "entry_date": "2023-01-15",
        "memo": "Test entry",
        "lines": [
            {
                "account_id": str(test_accounts[0].id),
                "direction": "DEBIT",
                "amount": "100.00",
                "currency": "SGD",
            },
            {
                "account_id": str(test_accounts[1].id),
                "direction": "CREDIT",
                "amount": "100.00",
                "currency": "SGD",
            },
        ],
        "source_type": "manual",
    }

    # WHEN: Create journal entry
    response = await client.post("/journal-entries", json=entry_data)

    # THEN: Entry created successfully
    assert response.status_code == 201
    data = response.json()
    assert data["id"] is not None
    assert data["entry_date"] == "2023-01-15"
    assert data["memo"] == "Test entry"
    assert data["status"] == "draft"
    assert len(data["lines"]) == 2

    # Verify in database
    result = await db.execute(select(JournalEntry).where(JournalEntry.id == UUID(data["id"])))
    entry = result.scalar_one()
    assert entry is not None
    assert entry.user_id == test_user.id
    assert entry.entry_date == date(2023, 1, 15)
    assert entry.memo == "Test entry"


@pytest.mark.asyncio
async def test_create_unbalanced_entry(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
    test_accounts: list[Account],
):
    """Test creating an unbalanced entry fails."""
    # GIVEN: Unbalanced entry data (missing credit side)
    invalid_data = {
        "entry_date": "2023-01-15",
        "memo": "Invalid entry",
        "lines": [
            {
                "account_id": str(test_accounts[0].id),
                "direction": "DEBIT",
                "amount": "100.00",
                "currency": "SGD",
            }
        ],
        "source_type": "manual",
    }

    # WHEN: Try to create unbalanced entry
    response = await client.post("/journal-entries", json=invalid_data)

    # THEN: Request rejected
    assert response.status_code == 400
    assert "must balance" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_list_journal_entries(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
    test_entries: list[JournalEntry],
):
    """Test listing journal entries with filters."""
    # GIVEN: Test entries exist

    # WHEN: List all entries
    response = await client.get("/journal-entries")

    # THEN: Entries returned
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= len(test_entries)
    assert len(data["items"]) > 0

    # Test filtering by status
    response = await client.get("/journal-entries?status_filter=DRAFT")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    assert all(item["status"] == "draft" for item in data["items"])

    # Test date range filtering
    start_date = date(2023, 1, 1)
    end_date = date(2023, 12, 31)
    response = await client.get(f"/journal-entries?start_date={start_date}&end_date={end_date}")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1

    # Test pagination
    response = await client.get("/journal-entries?limit=1&offset=0")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) <= 1


@pytest.mark.asyncio
async def test_get_journal_entry(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
    test_entries: list[JournalEntry],
):
    """Test getting a specific journal entry."""
    # GIVEN: Test entry exists
    entry = test_entries[0]

    # WHEN: Get entry by ID
    response = await client.get(f"/journal-entries/{entry.id}")

    # THEN: Entry returned
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(entry.id)
    assert data["memo"] == entry.memo

    # Test getting non-existent entry
    non_existent_id = uuid4()
    response = await client.get(f"/journal-entries/{non_existent_id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_post_journal_entry(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
    test_entries: list[JournalEntry],
):
    """Test posting a journal entry (changing status from DRAFT to POSTED)."""
    # GIVEN: Draft entry exists
    draft_entry = next((e for e in test_entries if e.status == JournalEntryStatus.DRAFT), None)
    assert draft_entry is not None, "No draft entry found"

    # WHEN: Post the entry
    response = await client.post(f"/journal-entries/{draft_entry.id}/post")

    # THEN: Entry posted successfully
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "posted"

    # Verify in database
    await db.refresh(draft_entry)
    assert draft_entry.status == JournalEntryStatus.POSTED

    # Test posting already posted entry
    response = await client.post(f"/journal-entries/{draft_entry.id}/post")
    assert response.status_code == 400
    assert "already posted" in response.json()["detail"].lower()

    # Test posting non-existent entry
    non_existent_id = uuid4()
    response = await client.post(f"/journal-entries/{non_existent_id}/post")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_void_journal_entry(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
    test_entries: list[JournalEntry],
):
    """Test voiding a journal entry."""
    # GIVEN: Posted entry exists
    posted_entry = next((e for e in test_entries if e.status == JournalEntryStatus.POSTED), None)
    assert posted_entry is not None, "No posted entry found"

    # WHEN: Void the entry
    void_request = {"reason": "Test void reason"}
    response = await client.post(
        f"/journal-entries/{posted_entry.id}/void",
        json=void_request,
    )

    # THEN: Entry voided successfully
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "void"
    assert data["void_reason"] == "Test void reason"

    # Verify in database
    await db.refresh(posted_entry)
    assert posted_entry.status == JournalEntryStatus.VOID
    assert posted_entry.void_reason == "Test void reason"

    # Test voiding already voided entry
    response = await client.post(
        f"/journal-entries/{posted_entry.id}/void",
        json=void_request,
    )
    assert response.status_code == 400
    assert "already voided" in response.json()["detail"].lower()

    # Test voiding non-existent entry
    non_existent_id = uuid4()
    response = await client.post(
        f"/journal-entries/{non_existent_id}/void",
        json=void_request,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_journal_entry(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
    test_accounts: list[Account],
):
    """Test deleting a journal entry (only drafts can be deleted)."""
    # GIVEN: Create a draft entry to delete
    draft_entry = JournalEntry(
        id=uuid4(),
        user_id=test_user.id,
        entry_date=date(2023, 1, 20),
        memo="Entry to delete",
        status=JournalEntryStatus.DRAFT,
    )
    db.add(draft_entry)
    await db.flush()

    # Add balanced lines
    line_debit = JournalLine(
        id=uuid4(),
        journal_entry_id=draft_entry.id,
        account_id=test_accounts[0].id,
        direction="DEBIT",
        amount=Decimal("50.00"),
        currency="SGD",
    )
    line_credit = JournalLine(
        id=uuid4(),
        journal_entry_id=draft_entry.id,
        account_id=test_accounts[1].id,
        direction="CREDIT",
        amount=Decimal("50.00"),
        currency="SGD",
    )
    db.add(line_debit)
    db.add(line_credit)
    await db.commit()
    draft_id = draft_entry.id

    # WHEN: Delete the draft entry
    response = await client.delete(f"/journal-entries/{draft_id}")

    # THEN: Entry deleted successfully
    assert response.status_code == 204

    # Verify in database
    result = await db.execute(select(JournalEntry).where(JournalEntry.id == draft_id))
    entry = result.scalar_one_or_none()
    assert entry is None

    # Test deleting already deleted entry
    response = await client.delete(f"/journal-entries/{draft_id}")
    assert response.status_code == 404

    # Test deleting non-existent entry
    non_existent_id = uuid4()
    response = await client.delete(f"/journal-entries/{non_existent_id}")
    assert response.status_code == 404
