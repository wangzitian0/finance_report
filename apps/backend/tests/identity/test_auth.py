'AC-identity.2.1'; from uuid import uuid4; import pytest; import structlog; from fastapi import HTTPException; from httpx import ASGITransport, AsyncClient; from src.identity import get_current_user_id
async def test_auth_missing_header(db_engine):
    'AC8.2.4'; from src.main import app; transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url='http://test') as ac: response = await ac.get('/accounts')
    assert response.status_code == 401; assert response.json()['detail'] == 'Not authenticated'
async def test_auth_invalid_token(db_engine):
    'AC8.2.4'; from src.main import app; transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url='http://test', headers={'Authorization': 'Bearer invalid-token'}) as ac: response = await ac.get('/accounts')
    assert response.status_code == 401; assert response.json()['detail'] == 'Could not validate credentials'
async def test_auth_non_existent_user(db_engine):
    'AC8.2.4'; from src.identity import create_access_token; from src.main import app; transport = ASGITransport(app=app); random_uuid = str(uuid4()); token = create_access_token(data={'sub': random_uuid})
    async with AsyncClient(transport=transport, base_url='http://test', headers={'Authorization': f'Bearer {token}'}) as ac: response = await ac.get('/accounts')
    assert response.status_code == 401; assert response.json()['detail'] == 'User not found'
async def test_auth_valid_user(client, test_user): 'AC-identity.2.4 AC1.2.2 AC8.2.4'; response = await client.get('/accounts'); assert response.status_code == 200
async def test_get_current_user_id_direct(db, test_user): from src.identity import create_access_token; token = create_access_token(data={'sub': str(test_user.id)}); user_id = await get_current_user_id(token=token, db=db); assert user_id == test_user.id
async def test_AC10_11_1_get_current_user_id_binds_user_context(db, test_user): 'AC-observability.11.1'; from src.identity import create_access_token; structlog.contextvars.clear_contextvars(); token = create_access_token(data={'sub': str(test_user.id)}); user_id = await get_current_user_id(token=token, db=db); assert user_id == test_user.id; assert structlog.contextvars.get_contextvars()['user_id'] == str(test_user.id)
async def test_get_current_user_id_invalid_user_db(db):
    from src.identity import create_access_token; token = create_access_token(data={'sub': str(uuid4())})
    with pytest.raises(HTTPException, match='User not found'): await get_current_user_id(token=token, db=db)
