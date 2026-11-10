import pytest; from fastapi import HTTPException, status; from src.platform import raise_bad_request, raise_conflict, raise_gateway_timeout, raise_internal_error, raise_not_found, raise_service_unavailable, raise_too_large, raise_too_many_requests, raise_unauthorized
def test_raise_not_found():
    with pytest.raises(HTTPException) as exc_info: raise_not_found('User')
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND; assert exc_info.value.detail == 'User not found'; _m1_cause = ValueError('Original error')
    with pytest.raises(HTTPException) as _m1_exc_info: raise_not_found('Account', cause=_m1_cause)
    assert _m1_exc_info.value.status_code == status.HTTP_404_NOT_FOUND; assert _m1_exc_info.value.__cause__ is _m1_cause
    with pytest.raises(HTTPException) as _m2_exc_info: raise_bad_request('Invalid input')
    assert _m2_exc_info.value.status_code == status.HTTP_400_BAD_REQUEST; assert _m2_exc_info.value.detail == 'Invalid input'; _m3_cause = ValueError('Validation failed')
    with pytest.raises(HTTPException) as _m3_exc_info: raise_bad_request('Bad data', cause=_m3_cause)
    assert _m3_exc_info.value.__cause__ is _m3_cause
    with pytest.raises(HTTPException) as _m4_exc_info: raise_unauthorized('Invalid token')
    assert _m4_exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED; assert _m4_exc_info.value.detail == 'Invalid token'; _m5_cause = RuntimeError('Token expired')
    with pytest.raises(HTTPException) as _m5_exc_info: raise_unauthorized('Unauthorized', cause=_m5_cause)
    assert _m5_exc_info.value.__cause__ is _m5_cause
    with pytest.raises(HTTPException) as _m6_exc_info: raise_conflict('Resource already exists')
    assert _m6_exc_info.value.status_code == status.HTTP_409_CONFLICT; assert _m6_exc_info.value.detail == 'Resource already exists'; _m7_cause = RuntimeError('Duplicate key')
    with pytest.raises(HTTPException) as _m7_exc_info: raise_conflict('Conflict', cause=_m7_cause)
    assert _m7_exc_info.value.__cause__ is _m7_cause
    with pytest.raises(HTTPException) as _m8_exc_info: raise_too_large('File too large')
    assert _m8_exc_info.value.status_code == status.HTTP_413_CONTENT_TOO_LARGE; assert _m8_exc_info.value.detail == 'File too large'; _m9_cause = ValueError('Size exceeded')
    with pytest.raises(HTTPException) as _m9_exc_info: raise_too_large('Too large', cause=_m9_cause)
    assert _m9_exc_info.value.__cause__ is _m9_cause
    with pytest.raises(HTTPException) as _m10_exc_info: raise_too_many_requests('Rate limit exceeded')
    assert _m10_exc_info.value.status_code == status.HTTP_429_TOO_MANY_REQUESTS; assert _m10_exc_info.value.detail == 'Rate limit exceeded'
    with pytest.raises(HTTPException) as _m11_exc_info: raise_too_many_requests('Rate limit exceeded', retry_after=60)
    assert _m11_exc_info.value.status_code == status.HTTP_429_TOO_MANY_REQUESTS; assert _m11_exc_info.value.headers == {'Retry-After': '60'}; _m12_cause = RuntimeError('Rate limited')
    with pytest.raises(HTTPException) as _m12_exc_info: raise_too_many_requests('Too many requests', cause=_m12_cause)
    assert _m12_exc_info.value.__cause__ is _m12_cause
    with pytest.raises(HTTPException) as _m13_exc_info: raise_internal_error('Internal server error')
    assert _m13_exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR; assert _m13_exc_info.value.detail == 'Internal server error'; _m14_cause = Exception('Database error')
    with pytest.raises(HTTPException) as _m14_exc_info: raise_internal_error('Server error', cause=_m14_cause)
    assert _m14_exc_info.value.__cause__ is _m14_cause
    with pytest.raises(HTTPException) as _m15_exc_info: raise_service_unavailable('Service unavailable')
    assert _m15_exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE; assert _m15_exc_info.value.detail == 'Service unavailable'; _m16_cause = ConnectionError('Service down')
    with pytest.raises(HTTPException) as _m16_exc_info: raise_service_unavailable('Unavailable', cause=_m16_cause)
    assert _m16_exc_info.value.__cause__ is _m16_cause
    with pytest.raises(HTTPException) as _m17_exc_info: raise_gateway_timeout('Gateway timeout')
    assert _m17_exc_info.value.status_code == status.HTTP_504_GATEWAY_TIMEOUT; assert _m17_exc_info.value.detail == 'Gateway timeout'; _m18_cause = TimeoutError('Request timeout')
    with pytest.raises(HTTPException) as _m18_exc_info: raise_gateway_timeout('Timeout', cause=_m18_cause)
    assert _m18_exc_info.value.__cause__ is _m18_cause
