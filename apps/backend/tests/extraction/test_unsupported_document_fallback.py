'AC-extraction.source-conservation.1'; from uuid import uuid4; import pytest; from src.extraction import DocumentType; from src.extraction.extension.source_lifecycle import SourceIdentityCommand
def test_document_type_rejects_unsupported_document_types():
    unsupported_types = ['tax_return', 'payslip', 'utility_bill', 'crypto_wallet', 'invoice']
    for doc_type in unsupported_types:
        with pytest.raises(ValueError, match=f"'{doc_type}' is not a valid DocumentType"): DocumentType(doc_type)
    _m1_user_id = uuid4()
    with pytest.raises(TypeError, match='document_type must be a DocumentType'): SourceIdentityCommand(user_id=_m1_user_id, file_path='/tmp/tax_2024.pdf', file_hash='hash_12345', original_filename='tax_2024.pdf', document_type='tax_return')
