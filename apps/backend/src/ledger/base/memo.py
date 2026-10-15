"""The memo of a journal entry: the size of its column and the cut for outside text."""

from __future__ import annotations

#: The size of the column ``journal_entries.memo``. The column definition reads it.
JOURNAL_MEMO_MAX_LENGTH = 500


def fit_journal_memo(text: str) -> str:
    """Cut ``text`` to the size of the memo column and keep its first characters.

    A statement description has no length limit, but the memo column holds
    ``JOURNAL_MEMO_MAX_LENGTH`` characters. The decision anchor and the command must
    hold the memo that the entry stores. A mismatch fails the first posting. A caller
    that builds a memo from text without a limit cuts it once and gives that one value
    to both. The cut is a pure function, so a retry computes the same value.
    """
    return text[:JOURNAL_MEMO_MAX_LENGTH]
