def _parse_brokerage_position(item, broker, snapshot_date):
    identifier = item.get('symbol') or item.get('ticker') or item.get('isin') or item.get('asset_identifier')
    # ... rest of the function remains the same ...

    return identifier


    identifier = item.get('asset_identifier') or item.get('symbol') or item.get('ticker') or item.get('isin')
    # ... rest of the function remains the same ...
    return identifier
