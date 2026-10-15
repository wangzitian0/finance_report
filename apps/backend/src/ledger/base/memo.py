"""The memo of a journal entry: the size of its column and the cut for outside text."""

from __future__ import annotations

#: The size of the column ``journal_entries.memo``. The column definition reads it.
JOURNAL_MEMO_MAX_LENGTH = 500


def fit_journal_memo(text: str) -> str:
    """Cut ``text`` to the size of the memo column and keep its first characters.

    A statement description has no length limit, but the memo column holds
    ``JOURNAL_MEMO_MAX_LENGTH`` characters. A caller that builds a memo from outside
    text cuts it once. It passes that one value to the decision anchor and to the
    command, so that the digest of a retry is the same.
    """
    return text[:JOURNAL_MEMO_MAX_LENGTH]
