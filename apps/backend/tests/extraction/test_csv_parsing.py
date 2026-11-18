import pytest

from src.extraction.extension.service import ExtractionError, ExtractionService


@pytest.mark.parametrize(
    ("csv_content", "institution", "expected_txns", "meta"),
    [
        (
            b"Transaction Date,Reference,Debit Amount,Credit Amount,Transaction Ref1,Transaction Ref2,Transaction Ref3\n"
            b"15 Jan 2025,REF001,,500.00,SALARY,EMPLOYER PTE LTD,JAN 2025\n"
            b"16 Jan 2025,REF002,100.00,,NETS,FAIRPRICE,GROCERIES\n"
            b"17 Jan 2025,REF003,50.00,,ATM WITHDRAWAL,DBS ATM,",
            "DBS",
            [("2025-01-15", "500.00", "IN", "SALARY"), ("2025-01-16", "100.00", "OUT", None), ("2025-01-17", "50.00", "OUT", None)],
            {"observed_transaction_start": "2025-01-15", "observed_transaction_end": "2025-01-17", "_absent": ("currency", "period_start", "period_end")},
        ),
        (
            b"Statement Currency,Statement Period Start,Statement Period End,Statement Opening Balance,Statement Closing Balance,Date,Description,Amount\n"
            b"SGD,2025-01-01,2025-01-31,100.00,125.00,2025-01-15,Interest,25.00",
            "Example Bank",
            [("2025-01-15", "25.00", "IN", "Interest")],
            {"currency": "SGD", "period_start": "2025-01-01", "period_end": "2025-01-31", "opening_balance": "100.00", "closing_balance": "125.00", "balance_source": "declared_in_csv_export"},
        ),
        (
            b"Statement Currency,Statement Closing Balance,Date,Description,Amount\nSGD,125.00,2025-01-15,Interest,25.00",
            "Example Bank",
            [("2025-01-15", "25.00", "IN", None)],
            {"balance_source": "missing_from_csv_export"},
        ),
        (b"Date,Description,Amount\n2025-01-15,Interest,25.00", "Example Bank", [("2025-01-15", "25.00", "IN", None)], {"balance_source": "missing_from_csv_export"}),
        (b"Transaction Date,Debit Amount,Credit Amount,Transaction Ref1\n20 Jan 2025,,1000.00,TRANSFER\n21 Jan 2025,200.00,,BILL", "POSB", [("2025-01-20", "1000.00", "IN", None), ("2025-01-21", "200.00", "OUT", None)], {}),
        (
            b"ID,Created on,Direction,Source amount (after fees),Reference\n12345,2025-01-10T10:30:00Z,OUT,250.00,Payment\n12346,2025-01-12T14:00:00Z,IN,1500.00,Client",
            "Wise",
            [("2025-01-10", "250.00", "OUT", None), ("2025-01-12", "1500.00", "IN", None)],
            {"observed_transaction_start": "2025-01-10", "observed_transaction_end": "2025-01-12", "_absent": ("period_start", "period_end")},
        ),
        (b"Transaction Date,Description,Debit,Credit\n05/01/2025,SALARY,,5000.00\n06/01/2025,CARD,1500.00,", "OCBC", [("2025-01-05", "5000.00", "IN", None), ("2025-01-06", "1500.00", "OUT", None)], {}),
        (b"Date,Description,Amount\n2025-01-01,Income,500.00\n2025-01-02,Expense,-100.00", "Unknown Bank", [("2025-01-01", "500.00", "IN", None), ("2025-01-02", "100.00", "OUT", None)], {}),
        (b"\xef\xbb\xbfTransaction Date,Debit Amount,Credit Amount,Description\n15 Jan 2025,,100.00,Test", "DBS", [("2025-01-15", "100.00", "IN", None)], {}),
        ("\ufeffDate,Amount,Description\n2025-01-15,100.00,Test income", "Generic", [("2025-01-15", "100.00", "IN", None)], {}),
        (b"Date,Amount,Description\n2025-01-15,100.00,ISO\n15/01/2025,200.00,DMY\n01/15/2025,300.00,MDY", "Generic", [("2025-01-15", "100.00", "IN", None), ("2025-01-15", "200.00", "IN", None), ("2025-01-15", "300.00", "IN", None)], {}),
        (b'Date,Debit,Credit,Description\n2025-01-15,$50.00,,Purchase\n2025-01-16,,SGD 100.00,Deposit\n2025-01-17,,"1,500.00",Large', "Generic", [("2025-01-15", "50.00", "OUT", None), ("2025-01-16", "100.00", "IN", None), ("2025-01-17", "1500.00", "IN", None)], {}),
        (b"Transaction Date,Debit Amount,Credit Amount,Description\n15 Jan 2025,,100.00,Valid\nInvalid Date,,50.00,Skip\n16 Jan 2025,,200.00,Valid2", "DBS", [("2025-01-15", "100.00", "IN", None), ("2025-01-16", "200.00", "IN", None)], {}),
        (b"Transaction Date,Debit Amount,Credit Amount,Transaction Ref1\n15 Jan 2025,,,No amt\n16 Jan 2025,,500.00,Deposit", "DBS", [("2025-01-16", "500.00", "IN", None)], {}),
        (b"ID,Created on,Direction,Source amount (after fees),Reference\n123,INVALID,OUT,250.00,Bad\n124,2025-01-10T10:30:00Z,OUT,0.00,Zero\n125,2025-01-10T10:30:00Z,OUT,INVALID,Bad\n126,2025-01-12T14:00:00Z,IN,1500.00,Valid", "Wise", [("2025-01-12", "1500.00", "IN", None)], {}),
        (b"Transaction Date,Description,Debit,Credit\nBAD_DATE,INV,100.00,\n05/01/2025,NO_AMT,,\n06/01/2025,SALARY,,5000.00\n07/01/2025,CARD,1500.00,", "OCBC", [("2025-01-06", "5000.00", "IN", None), ("2025-01-07", "1500.00", "OUT", None)], {}),
        (b"Date,Amount,Description\nINVALID,100.00,Bad\n2025-01-15,INVALID_AMT,Bad\n2025-01-16,200.00,Valid", "Unknown Bank", [("2025-01-16", "200.00", "IN", None)], {}),
        (b"Date,Debit,Credit,Description\n2025-01-15,,,None\n2025-01-16,,500.00,Valid", "Unknown Bank", [("2025-01-16", "500.00", "IN", None)], {}),
        (b"Transaction Date,Debit,Credit,Description\n15 Jan 2025,,100.00,\n16 Jan 2025,,50.00,Valid", "OCBC", [("2025-01-15", "100.00", "IN", ""), ("2025-01-16", "50.00", "IN", "Valid")], {}),
        (b"Date,Amount,Description\n2025-01-15,100.00,Payment to S1234567A", "Unknown Bank", [("2025-01-15", "100.00", "IN", None)], {"_txn0_no_ref": True}),
        (b"Created on,Source amount (after fees),Direction,Reference\n1/5/2025T10:30:00,100.00,IN,TRF-1", "Wise", [("2025-05-01", "100.00", "IN", None)], {}),
        (
            "----------------------微信支付账单明细列表--------------------\n"
            "统计时间: 2025-01-01 至 2025-01-31\n-----------------------------------------------------------------\n"
            "交易时间,交易类型,交易对方,商品,收/支,金额(元),支付方式,当前状态,交易单号,商户单号,备注\n"
            "2025-01-15 12:30:00,商户消费,星巴克,拿铁咖啡,支出,¥38.00,零钱,支付成功,4200000001,M1001,/\n"
            "2025-01-18 19:00:00,转账,张三,朋友转账,收入,100.00,零钱,已存入零钱,4200000002,M1002,/\n".encode(),
            "WeChat Pay",
            [("2025-01-15", "38.00", "OUT", "星巴克"), ("2025-01-18", "100.00", "IN", "张三")],
            {"_refs": ["4200000001", "4200000002"]},
        ),
        (
            "支付宝交易记录明细查询\n账号: test@example.com\n-----------------------------------------------------------------\n"
            "交易时间\t,交易分类\t,交易对方\t,对方账号\t,商品说明\t,收/支\t,金额\t,收/付款方式\t,交易状态\t,交易订单号\t,商家订单号\t,备注\t\n"
            "2025-01-10 08:30:00\t,餐饮美食\t,肯德基\t,kfc@corp\t,早餐套餐\t,支出\t,25.50\t,花呗\t,交易成功\t,202501100001\t,KFC01\t,/\t\n"
            "2025-01-20 14:15:00\t,转账充值\t,李四\t,lisi@corp\t,还款转账\t,收入\t,500.00\t,余额宝\t,交易成功\t,202501200002\t,LS02\t,/\t\n"
            "2025-01-25 10:00:00\t,信用卡还款\t,招商银行\t,cmb@bank\t,还款\t,不计收支\t,2000.00\t,银行卡\t,还款成功\t,202501250003\t,CMB03\t,/\t\n".encode("gbk"),
            "Alipay",
            [("2025-01-10", "25.50", "OUT", "肯德基"), ("2025-01-20", "500.00", "IN", "李四")],
            {"_refs": ["202501100001", "202501200002"]},
        ),
    ],
)
async def test_csv_parsing_formats_and_skips(csv_content, institution, expected_txns, meta):
    result = await ExtractionService()._parse_csv_content(csv_content, institution)
    txns = result["transactions"]
    assert [(t["date"], t["amount"], t["direction"]) for t in txns] == [(d, a, dr) for d, a, dr, _ in expected_txns]
    for txn, (_, _, _, desc_sub) in zip(txns, expected_txns, strict=True):
        if desc_sub == "":
            assert txn["description"] == ""
        elif desc_sub is not None:
            assert desc_sub in txn["description"]
    for key, val in meta.items():
        if key == "_absent":
            assert all(k not in result for k in val)
        elif key == "_txn0_no_ref":
            assert "reference" not in txns[0]
        elif key == "_refs":
            assert [t["reference"] for t in txns] == val
        else:
            assert result[key] == val


@pytest.mark.parametrize(
    ("csv_content", "institution", "match"),
    [
        (b"Transaction Date,Amount\n", "DBS", "(No valid transactions|empty or has no data rows)"),
        (b"Transaction Date,Debit Amount,Credit Amount,Description\n15 Jan 2025,-,-,Dash", "DBS", "No valid transactions"),
        (b"Transaction Date,Debit Amount,Credit Amount,Description\n15 Jan 2025,abc,,Bad", "DBS", "No valid transactions"),
        (b"Date,Description,Reference\n2025-01-15,Some transaction,REF001", "Unknown Bank", "No valid transactions"),
        (b"Transaction Date,Debit Amount,Credit Amount,Description\nBAD DATE,,,R1\nALSO BAD,,,R2", "DBS", "No valid transactions found in CSV"),
    ],
)
async def test_csv_parsing_rejects_empty_or_invalid_rows(csv_content, institution, match):
    with pytest.raises(ExtractionError, match=match):
        await ExtractionService()._parse_csv_content(csv_content, institution)
