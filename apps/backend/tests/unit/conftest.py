import pytest
@pytest.fixture(autouse=True)
def patch_database_connection(): yield
