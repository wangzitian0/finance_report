from __future__ import annotations; from collections import defaultdict; from uuid import UUID; from src.counter import CounterKey
class InMemoryCounterRepository:
    def __init__(self) -> None: self._tally: dict[tuple[UUID, str], int] = defaultdict(int)
    async def bump(self, user_id: UUID, key: CounterKey) -> int: self._tally[user_id, key.value] += 1; return self._tally[user_id, key.value]
    async def total(self, key: CounterKey) -> int: return sum((v for (_, k), v in self._tally.items() if k == key.value))
    async def for_user(self, user_id: UUID, key: CounterKey) -> int: return self._tally.get((user_id, key.value), 0)
