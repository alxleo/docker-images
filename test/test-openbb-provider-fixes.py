"""Fixture checks for native provider behavior patched into the image."""

import asyncio
import unittest
from datetime import date
from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock, patch

import pandas as pd
from openbb_core.provider.utils.errors import EmptyDataError
from openbb_sec.models.sec_as_filed_statements import (
    SecAsFiledStatementsFetcher,
    SecAsFiledStatementsQueryParams,
)
from openbb_sec.models.sec_financials import FinancialStatements
from openbb_sec.models.sec_risk_factors import (
    SecRiskFactorsFetcher,
    SecRiskFactorsQueryParams,
)
from openbb_yfinance.models.balance_sheet import (
    YFinanceBalanceSheetFetcher,
    YFinanceBalanceSheetQueryParams,
)
from openbb_yfinance.models.cash_flow import (
    YFinanceCashFlowStatementFetcher,
    YFinanceCashFlowStatementQueryParams,
)
from openbb_yfinance.models.income_statement import (
    YFinanceIncomeStatementFetcher,
    YFinanceIncomeStatementQueryParams,
)
from pydantic import ValidationError

YFINANCE_STATEMENTS = (
    (
        YFinanceIncomeStatementFetcher,
        YFinanceIncomeStatementQueryParams,
        "get_income_stmt",
    ),
    (
        YFinanceBalanceSheetFetcher,
        YFinanceBalanceSheetQueryParams,
        "get_balance_sheet",
    ),
    (
        YFinanceCashFlowStatementFetcher,
        YFinanceCashFlowStatementQueryParams,
        "get_cash_flow",
    ),
)


class FakeTicker:
    def __init__(self, data: pd.DataFrame, info: dict[str, str]):
        self.data = data
        self.info = info

    def get_income_stmt(self, **_kwargs):
        return self.data

    def get_balance_sheet(self, **_kwargs):
        return self.data

    def get_cash_flow(self, **_kwargs):
        return self.data


class YFinanceStatementTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame(
            [[100.0], [10.0]],
            index=["Total Revenue", "Net Income"],
            columns=[pd.Timestamp("2025-12-31")],
        )

    def test_all_statement_models_include_yahoo_reporting_currency(self):
        for fetcher, query_type, _getter in YFINANCE_STATEMENTS:
            with self.subTest(fetcher=fetcher.__name__):
                ticker = FakeTicker(self.frame.copy(), {"financialCurrency": "GBP"})
                query = query_type(symbol="ULVR.L")
                with patch("yfinance.Ticker", return_value=ticker) as ticker_factory:
                    rows = fetcher.extract_data(query, None)
                self.assertEqual(ticker_factory.call_args.args, ("ULVR.L",))
                self.assertEqual(rows[0]["reported_currency"], "GBP")
                data = fetcher.transform_data(query, rows)
                self.assertEqual(data[0].reported_currency, "GBP")

    def test_missing_yahoo_currency_stays_unavailable(self):
        for fetcher, query_type, _getter in YFINANCE_STATEMENTS:
            with self.subTest(fetcher=fetcher.__name__):
                ticker = FakeTicker(self.frame.copy(), {})
                with patch("yfinance.Ticker", return_value=ticker):
                    rows = fetcher.extract_data(query_type(symbol="MSFT"), None)
                self.assertIsNone(rows[0]["reported_currency"])

    def test_statement_query_models_reject_multiple_symbols(self):
        for fetcher, query_type, _getter in YFINANCE_STATEMENTS:
            with self.subTest(fetcher=fetcher.__name__):
                with (
                    patch("yfinance.Ticker") as ticker_factory,
                    self.assertRaisesRegex(ValidationError, "one symbol"),
                ):
                    query_type(symbol="MSFT,ULVR.L")
                ticker_factory.assert_not_called()

    def test_empty_statement_frames_raise_empty_data_error(self):
        for fetcher, query_type, _getter in YFINANCE_STATEMENTS:
            with self.subTest(fetcher=fetcher.__name__):
                ticker = FakeTicker(pd.DataFrame(), {"financialCurrency": "USD"})
                with (
                    patch("yfinance.Ticker", return_value=ticker),
                    self.assertRaises(EmptyDataError),
                ):
                    fetcher.extract_data(query_type(symbol="MSFT"), None)


class FakeFilingMetadata:
    base_url = "https://www.sec.gov/Archives/edgar/data/1/0000000001"
    main_document_url = f"{base_url}/annual-report.htm"
    filing_date = date(2026, 2, 20)
    period_ending = date(2025, 12, 31)
    document_type = "20-F"

    @staticmethod
    def _accession_dash():
        return "0000000001-26-000001"

    def filing_metadata(self):
        return FinancialStatements.filing_metadata(self)


class FakeForeignFiling:
    document_type = "20-F"

    def __init__(self):
        self.requested_items = []

    def _item_by_name(self, _needle):
        return None

    def get_item(self, *item_numbers):
        self.requested_items.append(item_numbers)
        if item_numbers == ("3D",):
            return {"item_num": "3D", "name": "Risk Factors", "text": "specific 3D risk"}
        if item_numbers == ("3",):
            return {"item_num": "3", "name": "Key Information", "text": "all of Item 3"}
        return None

    def get_main_document_content(self):
        return None

    def _legacy_risk_factors(self):
        return []


class SecRiskFactorTests(unittest.TestCase):
    def test_foreign_filing_selects_only_item_3d(self):
        filing = FakeForeignFiling()
        self.assertEqual(
            FinancialStatements.risk_factors(filing),
            [{"risk_factor": "Risk Factors", "text": "specific 3D risk"}],
        )
        self.assertEqual(filing.requested_items, [("3D",)])

    def test_foreign_risk_toc_slices_only_the_referenced_page_range(self):
        html = """
        <html><body>
          <table>
            <tr><td>D.</td><td>Risk Factors</td><td>31-37</td></tr>
            <tr><td><a href="#start">31</a></td><td>Our Principal Risks</td></tr>
            <tr><td><a href="#end">38</a></td><td>Viability Statement</td></tr>
          </table>
          <div id="start"><p>Our Principal Risks</p>
            <p><b>Funding Risk</b> We may not obtain funding.</p>
          </div>
          <div id="end"><p>Following report content that is outside Item 3D.</p></div>
        </body></html>
        """

        class Filing:
            @staticmethod
            def get_main_document_content():
                return html

        factors = FinancialStatements._foreign_risk_factors(Filing())
        self.assertTrue(factors)
        self.assertTrue(all((factor.get("text") or "").strip() for factor in factors))
        combined = " ".join(factor["text"] for factor in factors)
        self.assertIn("We may not obtain funding.", combined)
        self.assertNotIn("Following report content", combined)

    def test_foreign_item_3d_heading_stops_before_item_4(self):
        html = """
        <html><body>
          <p>ITEM 3. KEY INFORMATION</p>
          <p id="risk-factors">3.D RISK FACTORS</p>
          <p><b>Industry Risk</b> The market is competitive.</p>
          <p>ITEM 4. INFORMATION ON THE COMPANY</p>
          <p>Later annual report content.</p>
        </body></html>
        """

        class Filing:
            @staticmethod
            def get_main_document_content():
                return html

        factors = FinancialStatements._foreign_risk_factors(Filing())
        self.assertTrue(factors)
        combined = " ".join(factor["text"] for factor in factors)
        self.assertIn("The market is competitive.", combined)
        self.assertNotIn("Later annual report content", combined)

    def test_foreign_item_3d_heading_without_body_is_empty(self):
        html = """
        <html><body>
          <p>ITEM 3. KEY INFORMATION</p>
          <p id="risk-factors">3.D RISK FACTORS</p>
          <p>ITEM 4. INFORMATION ON THE COMPANY</p>
          <p>Later annual report content.</p>
        </body></html>
        """

        class Filing:
            @staticmethod
            def get_main_document_content():
                return html

        self.assertEqual(FinancialStatements._foreign_risk_factors(Filing()), [])

    def test_foreign_page_range_heading_without_body_is_empty(self):
        for heading in ("3.D RISK FACTORS", "Our Principal Risks"):
            with self.subTest(heading=heading):
                html = f"""
                <html><body>
                  <table>
                    <tr><td>D.</td><td>Risk Factors</td><td>31-37</td></tr>
                    <tr><td><a href="#start">31</a></td></tr>
                    <tr><td><a href="#end">38</a></td></tr>
                  </table>
                  <div id="start"><p>{heading}</p></div>
                  <div id="end"><p>Later report content.</p></div>
                </body></html>
                """

                class Filing:
                    @staticmethod
                    def get_main_document_content(_html=html):
                        return _html

                self.assertEqual(FinancialStatements._foreign_risk_factors(Filing()), [])

    def test_missing_foreign_risks_do_not_use_domestic_legacy_parser(self):
        class Filing:
            document_type = "20-F"

            @staticmethod
            def _item_by_name(_needle):
                return None

            @staticmethod
            def get_item(*_item_numbers):
                return None

            @staticmethod
            def get_main_document_content():
                return None

            @staticmethod
            def _foreign_risk_factors():
                return []

            @staticmethod
            def _legacy_risk_factors():
                raise AssertionError("foreign forms must not use the legacy parser")

        self.assertEqual(FinancialStatements.risk_factors(Filing()), [])

    def test_empty_heading_blocks_are_filtered_and_filing_metadata_is_retained(self):
        class Statements(FakeFilingMetadata):
            @staticmethod
            def risk_factors():
                return [
                    {"risk_factor": "No body", "text": "  \n"},
                    {"risk_factor": "Liquidity", "text": "Funding risk details."},
                ]

        query = SecRiskFactorsQueryParams(symbol="UL")
        with (
            patch(
                "openbb_sec.models.sec_financials.resolve_section_url",
                new=AsyncMock(return_value="https://www.sec.gov/selected-filing"),
            ),
            patch.object(FinancialStatements, "from_url", return_value=Statements()),
        ):
            rows = asyncio.run(SecRiskFactorsFetcher.aextract_data(query, None))

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["source_url"], Statements.main_document_url)
        self.assertEqual(row["accession"], "0000000001-26-000001")
        self.assertEqual(row["filing_date"], date(2026, 2, 20))
        self.assertEqual(row["filing_period_ending"], date(2025, 12, 31))
        self.assertEqual(row["filing_form"], "20-F")
        data = SecRiskFactorsFetcher.transform_data(query, rows)
        self.assertEqual(data[0].filing_period_ending, date(2025, 12, 31))

    def test_as_filed_rows_retain_filing_provenance(self):
        class Statements(FakeFilingMetadata):
            @staticmethod
            def get_statement(_statement_type):
                return pd.DataFrame(
                    [{"period_ending": "2026-03-31 -- 12 Months Ended", "value": 5_472_920}],
                ), None

        query = SecAsFiledStatementsQueryParams(symbol="TM", statement_type="cash")
        with (
            patch(
                "openbb_sec.models.sec_financials.resolve_section_url",
                new=AsyncMock(return_value="https://www.sec.gov/selected-filing"),
            ),
            patch.object(FinancialStatements, "from_url", return_value=Statements()),
        ):
            rows = asyncio.run(SecAsFiledStatementsFetcher.aextract_data(query, None))

        self.assertEqual(rows[0]["value"], 5_472_920)
        self.assertEqual(rows[0]["accession"], "0000000001-26-000001")
        self.assertEqual(rows[0]["filing_period_ending"], date(2025, 12, 31))
        self.assertEqual(rows[0]["filing_form"], "20-F")
        data = SecAsFiledStatementsFetcher.transform_data(query, rows)
        self.assertEqual(data[0].filing_date, date(2026, 2, 20))

    def test_duration_and_scale_use_full_filing_labels(self):
        self.assertEqual(
            FinancialStatements._period_start_from_duration("2026-03-31 -- 12 Months Ended"),
            "2025-04-01",
        )
        self.assertEqual(
            FinancialStatements._period_start_from_duration("2026-03-31 -- 3 Months Ended"),
            "2026-01-01",
        )
        self.assertEqual(
            FinancialStatements._statement_multiplier("JPY (in millions of yen)"),
            1_000_000,
        )
        self.assertEqual(
            FinancialStatements._statement_multiplier("JPY (in million of yen)"),
            1_000_000,
        )
        self.assertEqual(FinancialStatements._statement_multiplier("$ in thousands"), 1_000)
        self.assertEqual(FinancialStatements._statement_multiplier("per share"), 1)

    def test_empty_risk_bodies_raise_empty_data_error(self):
        class Statements(FakeFilingMetadata):
            @staticmethod
            def risk_factors():
                return [{"risk_factor": "No body", "text": " \n"}]

        query = SecRiskFactorsQueryParams(symbol="UL")
        with (
            patch(
                "openbb_sec.models.sec_financials.resolve_section_url",
                new=AsyncMock(return_value="https://www.sec.gov/selected-filing"),
            ),
            patch.object(FinancialStatements, "from_url", return_value=Statements()),
            self.assertRaises(EmptyDataError),
        ):
            asyncio.run(SecRiskFactorsFetcher.aextract_data(query, None))


def native_statement_rows():
    labels = [
        "Operating cash flow",
        "Basic earnings per share",
        "Effective tax rate (in percent)",
        "Weighted average number of shares outstanding (in shares)",
        "Zero",
    ]
    values = [5_472_920, 1.23, 17.5, 314.5, 0]
    units = [
        "iso4217:JPY",
        "iso4217:JPY / shares",
        "pure",
        "shares",
        "iso4217:JPY",
    ]
    tags = {f"tag{i}": {"label": label} for i, label in enumerate(labels)}
    instance = {
        f"tag{i}": {"context": [{"value": str(value), "unit": unit}]}
        for i, (value, unit) in enumerate(zip(values, units, strict=True))
    }
    filing = SimpleNamespace(
        _instance=instance,
        _tags=tags,
        tags=tags,
        _period_context={},
        document_type="20-F",
        is_xbrl=True,
    )
    filing._ensure_xbrl = lambda: None
    filing._get_statements_info = lambda: {"Consolidated cash flows": {"url": "https://www.sec.gov/fixture"}}
    raw = pd.DataFrame(
        {
            "JPY (in millions of yen), shares in thousands": labels,
            "Mar. 31, 2026": values,
        }
    )
    metadata = [
        pd.DataFrame(
            {
                0: ["Name", "Namespace Prefix", "Data Type", "Balance Type", "Period Type"],
                1: [tag, "fixture", "decimal", "credit", "duration"],
            }
        )
        for tag in tags
    ]
    filing._get_document = lambda *args, **kwargs: [raw, *metadata]
    for name in (
        "_period_start_from_duration",
        "_statement_multiplier",
        "_scale_statement_value",
        "_multiplier_map",
    ):
        setattr(filing, name, getattr(FinancialStatements, name))
    filing._download_statement_from_url = MethodType(FinancialStatements._download_statement_from_url, filing)
    filing._download_statement = MethodType(FinancialStatements._download_statement, filing)
    data, _metadata = FinancialStatements.get_statement(filing, "cash")
    return {row["label"]: row for row in data[["label", "value", "unit", "period_beginning"]].to_dict("records")}


class NativeStatementScaleTests(unittest.TestCase):
    def test_mixed_xbrl_units_apply_only_the_matching_display_scales(self):
        rows = native_statement_rows()
        self.assertEqual(rows["Operating cash flow"]["value"], 5_472_920_000_000)
        self.assertEqual(rows["Basic earnings per share"]["value"], 1.23)
        self.assertEqual(rows["Effective tax rate (in percent)"]["value"], 17.5)
        self.assertEqual(
            rows["Weighted average number of shares outstanding (in shares)"]["value"],
            314_500,
        )

    def test_zero_value_retains_duration_start(self):
        rows = native_statement_rows()
        self.assertEqual(rows["Zero"]["value"], 0)
        self.assertEqual(rows["Zero"]["period_beginning"], "2025-04-01")


if __name__ == "__main__":
    unittest.main(verbosity=2)
