from dataclasses import dataclass, field; from datetime import UTC, date, datetime, timedelta; from decimal import Decimal; from typing import TypeVar; from uuid import UUID, uuid4; import factory; from sqlalchemy.ext.asyncio import AsyncSession; from src.extraction import BankStatementStatus, DocumentType, Stage1Status, TransactionDirection, UploadedDocument; from src.extraction.orm.layer2 import AtomicTransaction; from src.extraction.orm.statement_summary import StatementSummary; from src.identity import User; from src.ledger import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine; from src.reconciliation import ReconciliationMatch, ReconciliationStatus; T = TypeVar('T')  # EPIC-008
class AsyncFactoryMixin:
    @classmethod
    def _build_kwargs(cls, *args, **kwargs) -> dict: return kwargs
    @classmethod
    async def create_async(cls, db: AsyncSession, *args, **kwargs) -> T: build_kwargs = cls._build_kwargs(*args, **kwargs); instance = cls.build(**build_kwargs); db.add(instance); await db.flush(); await db.refresh(instance); return instance
class UserFactory(factory.Factory, AsyncFactoryMixin):
    class Meta: model = User
    id = factory.LazyFunction(uuid4); email = factory.Sequence(lambda n: f'user{n}@example.com'); name = factory.Sequence(lambda n: f'User {n}'); hashed_password = 'hashed_test_password'; created_at = factory.LazyFunction(lambda: datetime.now(UTC)); updated_at = factory.LazyFunction(lambda: datetime.now(UTC))
class AccountFactory(factory.Factory, AsyncFactoryMixin):
    class Meta: model = Account
    id = factory.LazyFunction(uuid4); name = factory.Sequence(lambda n: f'Account {n}')
    type = AccountType.ASSET; currency = 'SGD'; is_active = True; description = None; created_at = factory.LazyFunction(lambda: datetime.now(UTC)); updated_at = factory.LazyFunction(lambda: datetime.now(UTC))
    @classmethod
    def _build_kwargs(cls, user_id: UUID, **kwargs) -> dict: return {'user_id': user_id, **kwargs}
class JournalEntryFactory(factory.Factory, AsyncFactoryMixin):
    class Meta: model = JournalEntry
    id = factory.LazyFunction(uuid4); entry_date = factory.LazyFunction(lambda: date.today()); memo = factory.Sequence(lambda n: f'Transaction {n}'); status = JournalEntryStatus.POSTED; created_at = factory.LazyFunction(lambda: datetime.now(UTC)); updated_at = factory.LazyFunction(lambda: datetime.now(UTC))
    @classmethod
    def _build_kwargs(cls, user_id: UUID, **kwargs) -> dict: return {'user_id': user_id, **kwargs}
    @classmethod
    async def create_balanced_async(cls, db: AsyncSession, user_id: UUID, amount: Decimal=Decimal('100.00'), **kwargs) -> tuple[JournalEntry, Account, Account]: debit_account = await AccountFactory.create_async(db, user_id=user_id, type=AccountType.ASSET, name='Cash'); credit_account = await AccountFactory.create_async(db, user_id=user_id, type=AccountType.INCOME, name='Revenue'); entry = await cls.create_async(db, user_id=user_id, **kwargs); debit_line = JournalLine(id=uuid4(), journal_entry_id=entry.id, account_id=debit_account.id, direction=Direction.DEBIT, amount=amount, created_at=datetime.now(UTC), updated_at=datetime.now(UTC)); credit_line = JournalLine(id=uuid4(), journal_entry_id=entry.id, account_id=credit_account.id, direction=Direction.CREDIT, amount=amount, created_at=datetime.now(UTC), updated_at=datetime.now(UTC)); db.add(debit_line); db.add(credit_line); await db.flush(); await db.refresh(entry); return (entry, debit_account, credit_account)
class JournalLineFactory(factory.Factory, AsyncFactoryMixin):
    class Meta: model = JournalLine
    id = factory.LazyFunction(uuid4); direction = Direction.DEBIT; amount = Decimal('100.00'); created_at = factory.LazyFunction(lambda: datetime.now(UTC)); updated_at = factory.LazyFunction(lambda: datetime.now(UTC))
    @classmethod
    def _build_kwargs(cls, entry_id: UUID, account_id: UUID, **kwargs) -> dict: return {'entry_id': entry_id, 'account_id': account_id, **kwargs}
class UploadedDocumentFactory(factory.Factory, AsyncFactoryMixin):
    class Meta: model = UploadedDocument
    id = factory.LazyFunction(uuid4); file_path = factory.Sequence(lambda n: f'statements/doc_{n}.pdf'); file_hash = factory.LazyFunction(lambda: uuid4().hex); original_filename = factory.Sequence(lambda n: f'statement_{n}.pdf'); document_type = DocumentType.BANK_STATEMENT; created_at = factory.LazyFunction(lambda: datetime.now(UTC)); updated_at = factory.LazyFunction(lambda: datetime.now(UTC))
    @classmethod
    def _build_kwargs(cls, user_id: UUID, **kwargs) -> dict: return {'user_id': user_id, **kwargs}
class StatementSummaryFactory(factory.Factory, AsyncFactoryMixin):
    class Meta: model = StatementSummary
    id = factory.LazyFunction(uuid4); file_hash = factory.LazyFunction(lambda: uuid4().hex); institution = factory.Sequence(lambda n: f'Bank {n}'); account_last4 = factory.Sequence(lambda n: f'{n:04d}'); currency = 'SGD'; status = BankStatementStatus.UPLOADED; created_at = factory.LazyFunction(lambda: datetime.now(UTC)); updated_at = factory.LazyFunction(lambda: datetime.now(UTC))
    @classmethod
    def _build_kwargs(cls, user_id: UUID, **kwargs) -> dict: return {'user_id': user_id, **kwargs}
class AtomicTransactionFactory(factory.Factory, AsyncFactoryMixin):
    class Meta: model = AtomicTransaction
    id = factory.LazyFunction(uuid4); txn_date = factory.LazyFunction(date.today); description = factory.Sequence(lambda n: f'Transaction {n}'); amount = Decimal('50.00'); direction = TransactionDirection.OUT; reference = None; currency = 'SGD'; dedup_hash = factory.LazyFunction(lambda: uuid4().hex + uuid4().hex); created_at = factory.LazyFunction(lambda: datetime.now(UTC)); updated_at = factory.LazyFunction(lambda: datetime.now(UTC))
    @classmethod
    def _build_kwargs(cls, user_id: UUID, *, source_doc_id: UUID | None=None, **kwargs) -> dict: source_documents = kwargs.pop('source_documents', [{'doc_id': str(source_doc_id or uuid4()), 'doc_type': DocumentType.BANK_STATEMENT.value}]); return {'user_id': user_id, 'source_documents': source_documents, **kwargs}
class ReconciliationMatchFactory(factory.Factory, AsyncFactoryMixin):
    class Meta: model = ReconciliationMatch
    id = factory.LazyFunction(uuid4); match_score = 95; score_breakdown = {'amount': 1.0, 'date': 0.9, 'description': 0.85}; status = ReconciliationStatus.PENDING_REVIEW; created_at = factory.LazyFunction(lambda: datetime.now(UTC)); updated_at = factory.LazyFunction(lambda: datetime.now(UTC))
    @classmethod
    def _build_kwargs(cls, atomic_txn_id: UUID, journal_entry_ids: list[str], **kwargs) -> dict: return {'atomic_txn_id': atomic_txn_id, 'journal_entry_ids': journal_entry_ids, **kwargs}
@dataclass
class SeededParsedStatement:
    user_id: UUID; document: UploadedDocument; statement: StatementSummary; transactions: list[AtomicTransaction] = field(default_factory=list)
    @property
    def id(self) -> UUID: return self.statement.id
    @property
    def original_filename(self) -> str: return self.document.original_filename
async def seed_parsed_statement(db: AsyncSession, user_id: UUID, *, institution: str='DBS', original_filename: str='dbs_statement_2026_01.pdf', opening_balance: Decimal=Decimal('1000.00'), transactions: list[dict] | None=None) -> SeededParsedStatement:
    rows = transactions if transactions is not None else [{'description': 'Salary', 'amount': Decimal('5000.00'), 'direction': TransactionDirection.IN}, {'description': 'Coffee Shop', 'amount': Decimal('5.00'), 'direction': TransactionDirection.OUT}]; file_hash = uuid4().hex + uuid4().hex[:32]; document = await UploadedDocumentFactory.create_async(db, user_id=user_id, file_hash=file_hash, original_filename=original_filename, document_type=DocumentType.BANK_STATEMENT); closing_balance = opening_balance
    for row in rows:
        if row['direction'] == TransactionDirection.IN: closing_balance += row['amount']
        else: closing_balance -= row['amount']
    statement = await StatementSummaryFactory.create_async(db, user_id=user_id, file_hash=file_hash, uploaded_document_id=document.id, institution=institution, currency='SGD', period_start=date(2026, 1, 1), period_end=date(2026, 1, 31), opening_balance=opening_balance, closing_balance=closing_balance, status=BankStatementStatus.PARSED, stage1_status=Stage1Status.PENDING_REVIEW, confidence_score=95); doc_marker = {'doc_id': str(document.id), 'doc_type': DocumentType.BANK_STATEMENT.value}; base_date = date(2026, 1, 10); seeded_txns: list[AtomicTransaction] = []; running_balance = opening_balance
    for (index, row) in enumerate(rows):
        if row['direction'] == TransactionDirection.IN: running_balance += row['amount']
        else: running_balance -= row['amount']
        build_kwargs = AtomicTransactionFactory._build_kwargs(user_id=user_id, source_documents=[doc_marker], txn_date=row.get('date') or base_date + timedelta(days=index), description=row['description'], amount=row['amount'], direction=row['direction'], currency='SGD', balance_after=running_balance); seeded_txns.append(AtomicTransactionFactory.build(**build_kwargs))
    db.add_all(seeded_txns); await db.flush(); await db.commit(); return SeededParsedStatement(user_id=user_id, document=document, statement=statement, transactions=seeded_txns)
@dataclass(frozen=True)
class SeededYearOfEntries: bank: Account; card: Account; salary: Account
async def seed_year_of_journal_entries(db: AsyncSession, user_id: UUID, *, first_day: date, entry_count: int=1000, amount: Decimal=Decimal('100.00')) -> SeededYearOfEntries:
    from sqlalchemy import insert; from src.audit import JournalEntrySourceType; from src.ledger import JournalEntryAuthorityState; bank = Account(user_id=user_id, name='Bank', code='1001', type=AccountType.ASSET, currency='SGD'); card = Account(user_id=user_id, name='Card', code='2001', type=AccountType.LIABILITY, currency='SGD'); salary = Account(user_id=user_id, name='Salary', code='4001', type=AccountType.INCOME, currency='SGD'); db.add_all([bank, card, salary]); await db.flush(); now = datetime.now(UTC); entry_rows = []; line_rows = []
    for index in range(entry_count): entry_id = uuid4(); entry_rows.append({'id': entry_id, 'user_id': user_id, 'entry_date': first_day + timedelta(days=index % 365), 'memo': f'txn {index}', 'source_type': JournalEntrySourceType.MANUAL, 'source_id': None, 'decision_anchor_id': None, 'decision_authority_state': JournalEntryAuthorityState.LEGACY_UNPROVEN, 'status': JournalEntryStatus.POSTED, 'void_reason': None, 'void_reversal_entry_id': None, 'created_at': now, 'updated_at': now}); debit, credit = (bank, card) if index % 5 == 0 else (bank, salary); [line_rows.append({'id': uuid4(), 'journal_entry_id': entry_id, 'account_id': account.id, 'direction': direction, 'amount': amount, 'currency': 'SGD', 'fx_rate': None, 'event_type': None, 'tags': None, 'created_at': now, 'updated_at': now}) for account, direction in ((debit, Direction.DEBIT), (credit, Direction.CREDIT))]
    await db.execute(insert(JournalEntry), entry_rows); await db.execute(insert(JournalLine), line_rows); await db.commit(); return SeededYearOfEntries(bank=bank, card=card, salary=salary)
