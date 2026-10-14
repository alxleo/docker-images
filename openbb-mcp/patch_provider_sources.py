"""Patch SEC/yfinance 2.0.0 at build time until upstream releases include these fixes."""

from importlib.metadata import distribution, version
from pathlib import Path

EXPECTED_VERSIONS = {"openbb-sec": "2.0.0", "openbb-yfinance": "2.0.0"}


def lines(*source_lines: str) -> str:
    """Join exact source lines for version-pinned replacements."""
    return "\n".join(source_lines) + "\n"


def rewrite(package: str, relative_path: str, replacements: tuple[tuple[str, str], ...]) -> None:
    """Rewrite one installed source file, failing when its pinned source changes."""
    package_version = version(package)
    if package_version != EXPECTED_VERSIONS[package]:
        raise RuntimeError(f"Expected {package} {EXPECTED_VERSIONS[package]}, found {package_version}")

    path = Path(str(distribution(package).locate_file(""))) / relative_path
    source = path.read_text()
    for before, after in replacements:
        if source.count(before) != 1:
            raise RuntimeError(f"Expected one source anchor in {path}: {before!r}")
        source = source.replace(before, after, 1)
    path.write_text(source)


rewrite(
    "openbb-sec",
    "openbb_sec/models/sec_financials.py",
    (
        (
            'item = self._item_by_name("risk factor") or self.get_item("3D", "3")',
            'item = self._item_by_name("risk factor") or self.get_item("3D")',
        ),
        (
            '            "cash": "cash flows",',
            '            "cash": "cash flow",',
        ),
        (
            "            if len(df.columns) == 5:",
            lines(
                "            if len(df.columns) > 5:",
                "                data_columns = [",
                "                    index",
                "                    for index, column in enumerate(df.columns[1:], start=1)",
                '                    if not re.search(r"\\.\\d+$", str(column[1]))',
                "                ]",
                "                df1 = df.iloc[:, [0, *data_columns]].copy()",
                "                self._period_end1 = df1.columns[1][0]",
                "                df1.columns = df1.columns.droplevel(0)",
                "            elif len(df.columns) == 5:",
            ),
        ),
        (
            'blocks = [b for b in blocks if b.get("risk_factor")]',
            lines(
                "blocks = [",
                "    b",
                "    for b in blocks",
                '    if b.get("risk_factor") and (b.get("text") or "").strip()',
                "]",
            )
            .replace("\n", "\n            ")
            .rstrip(),
        ),
        (
            "    def risk_factors(self) -> list:",
            lines(
                "    def _foreign_risk_factors(self) -> list:",
                '        """Resolve a foreign-filing risk page range to its report anchors."""',
                "        from bs4 import BeautifulSoup",
                "        from openbb_sec.utils.filing_sections import split_bold_sections",
                "",
                '        html = self.get_main_document_content() or ""',
                "        if not html:",
                "            return []",
                '        soup = BeautifulSoup(html, "html.parser")',
                "        page_range = None",
                '        for row in soup.find_all("tr"):',
                '            row_text = re.sub(r"\\s+", " ", row.get_text(" ", strip=True))',
                '            if not re.search(r"\\bD\\.?\\s+Risk Factors\\b", row_text, re.IGNORECASE):',
                "                continue",
                '            match = re.search(r"\\b(\\d+)\\s*[-–]\\s*(\\d+)\\b", row_text)',
                "            if match:",
                "                page_range = (int(match.group(1)), int(match.group(2)))",
                "                break",
                "        def anchor_position(document: str, anchor_id: str) -> int | None:",
                "            position = document.find(f'id=\"{anchor_id}\"')",
                "            if position < 0:",
                "                position = document.find(f\"id='{anchor_id}'\")",
                '            return document.rfind("<", 0, position) if position >= 0 else None',
                "",
                '        section_html = ""',
                "        if page_range:",
                "            page_anchors = {}",
                '            for anchor in soup.find_all("a", href=True):',
                '                page = anchor.get_text(" ", strip=True)',
                '                href = anchor.get("href", "")',
                '                if page.isdigit() and href.startswith("#"):',
                "                    page_anchors.setdefault(int(page), href[1:])",
                "            start_id = page_anchors.get(page_range[0])",
                "            end_id = page_anchors.get(page_range[1] + 1)",
                "            if start_id and end_id:",
                "                start = anchor_position(html, start_id)",
                "                end = anchor_position(html, end_id)",
                "                if start is not None and end is not None and end > start:",
                "                    section_html = html[start:end]",
                "",
                "        if not section_html:",
                "            from openbb_sec.utils.filing_sections import extract_section_html",
                "",
                '            item_3 = extract_section_html(html, "3")',
                '            item_soup = BeautifulSoup(item_3, "html.parser")',
                '            for element in item_soup.find_all(["p", "div", "td"]):',
                '                heading = re.sub(r"\\s+", " ", element.get_text(" ", strip=True)).replace("\\xa0", " ")',
                '                if len(heading) > 100 or not re.fullmatch(r"(?:3\\s*\\.\\s*D|3D|D)[.\\s:]*RISK FACTORS", heading, re.IGNORECASE):',
                "                    continue",
                '                anchor_id = element.get("id")',
                "                if anchor_id:",
                "                    start = anchor_position(item_3, anchor_id)",
                "                    if start is not None:",
                "                        section_html = item_3[start:]",
                "                        break",
                "        if not section_html:",
                "            return []",
                '        section_soup = BeautifulSoup(section_html, "html.parser")',
                '        heading_pattern = re.compile(r"(?:(?:ITEM\\s+)?3\\s*\\.?\\s*D|D)[.)\\s:]*RISK FACTORS|RISK FACTORS|OUR PRINCIPAL RISKS", re.IGNORECASE)',
                '        for element in section_soup.find_all(["p", "div", "td", "h1", "h2", "h3", "h4"]):',
                '            heading = re.sub(r"\\s+", " ", element.get_text(" ", strip=True)).replace("\\xa0", " ")',
                "            if element.parent is not None and heading_pattern.fullmatch(heading):",
                "                element.decompose()",
                "        section_html = str(section_soup)",
                '        if not section_soup.get_text(" ", strip=True):',
                "            return []",
                '        blocks = split_bold_sections(section_html, "risk_factor")',
                '        blocks = [b for b in blocks if b.get("risk_factor") and (b.get("text") or "").strip()]',
                "        if blocks:",
                "            return blocks",
                '        text = BeautifulSoup(section_html, "html.parser").get_text(" ", strip=True)',
                '        return [{"risk_factor": "Risk Factors", "text": text}] if text else []',
                "",
                "    def risk_factors(self) -> list:",
            ),
        ),
        (
            lines(
                '    def get_statement(self, statement: str = "income"):',
                '        """As-filed statement (income/balance/cash/equity) as (data, meta) DataFrames."""',
            ),
            lines(
                "    def filing_metadata(self) -> dict:",
                '        """Return provenance from this selected filing."""',
                "        return {",
                '            "source_url": self.main_document_url or self.base_url,',
                '            "accession": self._accession_dash(),',
                '            "filing_date": self.filing_date,',
                '            "filing_period_ending": self.period_ending,',
                '            "filing_form": self.document_type,',
                "        }",
                "",
                "    @staticmethod",
                "    def _period_start_from_duration(period_ending: str) -> str | None:",
                '        """Find a duration start using its full month count."""',
                "        from pandas import DateOffset, offsets, to_datetime",
                "",
                '        if " -- " not in period_ending:',
                "            return None",
                '        period_end, duration = period_ending.split(" -- ", 1)',
                '        match = re.search(r"(\\d+)\\s+months?\\s+ended\\b", duration, re.IGNORECASE)',
                "        if not match:",
                "            return None",
                "        period_end = to_datetime(period_end)",
                "        return (",
                "            period_end",
                "            - DateOffset(months=int(match.group(1)))",
                "            + offsets.MonthEnd(0)",
                "            + offsets.MonthBegin(1)",
                '        ).strftime("%Y-%m-%d")',
                "",
                '    def get_statement(self, statement: str = "income"):',
                '        """As-filed statement (income/balance/cash/equity) as (data, meta) DataFrames."""',
            ),
        ),
        (
            lines(
                '            if row.value and row.value != "--" and " -- " in row.period_ending:',
                "                period_end = row.period_ending",
                '                period_months = period_end.split(" -- ")[-1][0]',
                '                period_end = to_datetime(period_end.split(" -- ")[0])',
                "                period_start = (",
                "                    period_end",
                "                    - DateOffset(months=int(period_months))",
                "                    + offsets.MonthEnd(0)",
                "                    + offsets.MonthBegin(1)",
                '                ).strftime("%Y-%m-%d")',
                "",
                "                return period_start",
            ),
            lines(
                '            if " -- " in str(row.period_ending or ""):',
                "                period_start = self._period_start_from_duration(",
                '                    str(row.period_ending or "")',
                "                )",
                "                if period_start:",
                "                    return period_start",
            ),
        ),
        (
            "    def _download_statement_from_url(self, url, is_equity: bool = False):",
            lines(
                "    @staticmethod",
                "    def _statement_unit(tags, instance, label: str) -> str | None:",
                '        """Find the XBRL unit matching a displayed statement label."""',
                '        normalized = re.sub(r"\\s+", " ", str(label)).strip().lower()',
                '        label_keys = ("label", "totalLabel", "terseLabel", "verboseLabel", "negatedLabel", "periodStartLabel", "periodEndLabel")',
                "        for tag, info in (tags or {}).items():",
                "            if not isinstance(info, dict):",
                "                continue",
                "            if not any(",
                '                isinstance(info.get(key), str) and re.sub(r"\\s+", " ", info[key]).strip().lower() == normalized',
                "                for key in label_keys",
                "            ):",
                "                continue",
                '            contexts = (instance.get(tag) or {}).get("context", [])',
                "            if contexts:",
                '                return contexts[0].get("unit")',
                "        return None",
                "",
                "    @staticmethod",
                "    def _scale_statement_value(value, label, unit, multiplier, shares_multiplier):",
                '        """Apply filing scales using XBRL units for non-monetary values."""',
                "        from pandas import isnull",
                "",
                "        if isnull(value):",
                '            return "--"',
                "        label = str(label).lower()",
                '        unit = str(unit or "").lower()',
                '        is_share_count = "(in shares)" in label or unit.strip() in ("share", "shares")',
                '        is_per_share = "per share" in label or "/" in unit',
                "        if is_share_count:",
                "            return int(value * shares_multiplier)",
                "        if is_per_share:",
                "            return float(value)",
                '        if unit in ("pure", "percent", "percentage") or "percent" in label or "%" in label:',
                "            return float(value)",
                "        return int(value * multiplier)",
                "",
                "    @staticmethod",
                "    def _statement_multiplier(heading: str) -> int:",
                '        """Read the amount scale stated in a filing table heading."""',
                "        match = re.search(",
                '            r"\\b(?:in\\s+)?(tens of thousands|hundreds of thousands|millions?|thousands?|hundreds?|tens)\\b",',
                "            heading,",
                "            re.IGNORECASE,",
                "        )",
                "        if not match:",
                "            return 1",
                "        unit = match.group(1).lower()",
                '        unit = {"million": "millions", "thousand": "thousands", "hundred": "hundreds"}.get(unit, unit)',
                "        return Filing._multiplier_map(unit)",
                "",
                "    def _download_statement_from_url(self, url, is_equity: bool = False):",
            ),
        ),
        (
            lines(
                "            multiplier_str = (",
                '                statement.columns[0].split("$ in ")[-1]',
                '                if "$ in " in statement.columns[0]',
                '                else ""',
                "            )",
            ),
            lines(
                "            multiplier = self._statement_multiplier(",
                "                str(statement.columns[0])",
                "            )",
            ),
        ),
        (
            lines(
                "            multiplier = self._multiplier_map(multiplier_str) if multiplier_str else 1",
            ),
            "",
        ),
        (
            lines(
                "            pattern = re.compile(",
                '                r"\\(in [a-zA-Z] per share\\)|per\\s+(?:common\\s+)?share\\b|weighted average number of",',
                "                re.IGNORECASE,",
                "            )",
                "            pattern_shares = re.compile(",
                '                r"(shares authorized|shares issued|shares outstanding)$",',
                "                re.IGNORECASE,",
                "            )",
            ),
            "",
        ),
        (
            lines(
                "                def _scale_row_value(row):",
                "                    if isnull(row[col]):",
                '                        return "--"',
                "",
                "                    label = str(row[statement.columns[0]]).lower()",
                "                    is_per_share = bool(pattern.search(label)) or (",
                '                        "(in dollars per share)" in label',
                "                    )",
                '                    is_share_count = "(in shares)" in label or bool(',
                "                        pattern_shares.search(label)",
                "                    )",
                "",
                "                    if is_per_share:",
                "                        return float(row[col])",
                "",
                "                    if is_share_count:",
                "                        return int(row[col] * shares_multiplier)",
                "",
                "                    value = row[col] * multiplier",
                "                    return int(value)",
                "",
                "                statement[col] = statement.apply(",
                "                    _scale_row_value,",
                "                    axis=1,",
                "                )",
            ),
            lines(
                "                statement[col] = statement.apply(",
                "                    lambda row: self._scale_statement_value(",
                "                        row[col],",
                "                        row[statement.columns[0]],",
                "                        FinancialStatements._statement_unit(",
                "                            self._tags,",
                "                            self._instance,",
                "                            row[statement.columns[0]],",
                "                        ),",
                "                        multiplier,",
                "                        shares_multiplier,",
                "                    ),",
                "                    axis=1,",
                "                )",
            ),
        ),
        (
            "        return self._legacy_risk_factors()",
            lines(
                '        if doc_type.startswith(("20-F", "40-F")):',
                "            return self._foreign_risk_factors()",
                "        return self._legacy_risk_factors()",
            ).rstrip("\n"),
        ),
    ),
)

rewrite(
    "openbb-sec",
    "openbb_sec/models/sec_risk_factors.py",
    (
        (
            "from typing import Any\n",
            lines("from datetime import date", "from typing import Any"),
        ),
        (
            lines(
                "    risk_factor: str | None = Field(",
                '        default=None, description="The individual risk factor heading."',
                "    )",
                '    text: str = Field(description="The text of the risk factor.")',
            ),
            lines(
                "    risk_factor: str | None = Field(",
                '        default=None, description="The individual risk factor heading."',
                "    )",
                '    text: str = Field(description="The text of the risk factor.")',
                '    source_url: str | None = Field(default=None, description="SEC source document URL.")',
                '    accession: str | None = Field(default=None, description="SEC filing accession number.")',
                '    filing_date: date | None = Field(default=None, description="SEC filing date.")',
                '    filing_period_ending: date | None = Field(default=None, description="Reported financial period end date.")',
                '    filing_form: str | None = Field(default=None, description="SEC filing form.")',
            ),
        ),
        (
            lines("        factors = statements.risk_factors()", "", "        if not factors:"),
            lines(
                "        factors = [",
                "            factor",
                "            for factor in statements.risk_factors()",
                '            if (factor.get("text") or "").strip()',
                "        ]",
                "",
                "        if not factors:",
            ),
        ),
        (
            "        return factors\n",
            lines(
                "        metadata = statements.filing_metadata()",
                "        return [{**factor, **metadata} for factor in factors]",
            ),
        ),
    ),
)

rewrite(
    "openbb-sec",
    "openbb_sec/models/sec_as_filed_statements.py",
    (
        (
            "from typing import Any, Literal\n",
            lines("from datetime import date", "from typing import Any, Literal"),
        ),
        (
            lines(
                "class SecAsFiledStatementsData(Data):",
                '    """SEC As-Filed Financial Statements Data."""',
                "",
                "    order: int | None = Field(",
            ),
            lines(
                "class SecAsFiledStatementsData(Data):",
                '    """SEC As-Filed Financial Statements Data."""',
                "",
                '    source_url: str | None = Field(default=None, description="SEC source document URL.")',
                '    accession: str | None = Field(default=None, description="SEC filing accession number.")',
                '    filing_date: date | None = Field(default=None, description="SEC filing date.")',
                '    filing_period_ending: date | None = Field(default=None, description="SEC report period end date.")',
                '    filing_form: str | None = Field(default=None, description="SEC filing form.")',
                "    order: int | None = Field(",
            ),
        ),
        (
            '        return data.to_dict("records")',
            lines(
                "        metadata = statements.filing_metadata()",
                '        return [{**row, **metadata} for row in data.to_dict("records")]',
            ).rstrip("\n"),
        ),
    ),
)


STATEMENT_PATCHES = (
    (
        "openbb_yfinance/models/income_statement.py",
        "YFinanceIncomeStatementData",
        "IncomeStatementData",
        "Income Statement",
        "get_income_stmt",
    ),
    (
        "openbb_yfinance/models/balance_sheet.py",
        "YFinanceBalanceSheetData",
        "BalanceSheetData",
        "Balance Sheet",
        "get_balance_sheet",
    ),
    (
        "openbb_yfinance/models/cash_flow.py",
        "YFinanceCashFlowStatementData",
        "CashFlowStatementData",
        "Cash Flow Statement",
        "get_cash_flow",
    ),
)

for relative_path, model_name, base_model, statement_name, getter in STATEMENT_PATCHES:
    replacements = [
        (
            f"class {model_name}({base_model}):",
            lines(
                '    @field_validator("symbol")',
                "    @classmethod",
                "    def require_single_symbol(cls, value: str) -> str:",
                '        if len(value.replace(",", " ").split()) != 1:',
                '            raise ValueError("Yahoo Finance statements require one symbol per request.")',
                "        return value.strip()",
                "",
                "",
                f"class {model_name}({base_model}):",
            ).rstrip("\n"),
        ),
        (
            lines(
                f"class {model_name}({base_model}):",
                f'    """Yahoo Finance {statement_name} Data."""',
                "",
                "    __alias_dict__ = {",
            ),
            lines(
                f"class {model_name}({base_model}):",
                f'    """Yahoo Finance {statement_name} Data."""',
                "",
                "    reported_currency: str | None = Field(",
                '        default=None, description="Currency for amounts reported in the statement."',
                "    )",
                "",
                "    __alias_dict__ = {",
            ),
        ),
    ]
    if getter != "get_cash_flow":
        replacements.append(
            (
                "from openbb_core.provider.utils.errors import EmptyDataError\n",
                lines(
                    "from openbb_core.provider.utils.errors import EmptyDataError",
                    "        from pandas import DataFrame",
                ),
            )
        )
    replacements.extend(
        [
            (
                lines(
                    '        period = "yearly" if query.period == "annual" else "quarterly"',
                    f"        data = Ticker(query.symbol).{getter}(",
                    "            as_dict=False, pretty=False, freq=period",
                    "        )",
                    "",
                    (
                        "        if not isinstance(data, DataFrame):"
                        if getter == "get_cash_flow"
                        else "        if data is None:"
                    ),
                    "            raise EmptyDataError()",
                ),
                lines(
                    '        period = "yearly" if query.period == "annual" else "quarterly"',
                    "        ticker = Ticker(query.symbol)",
                    f"        data = ticker.{getter}(",
                    "            as_dict=False, pretty=False, freq=period",
                    "        )",
                    "",
                    "        if not isinstance(data, DataFrame) or data.empty:",
                    "            raise EmptyDataError()",
                    '        reported_currency = (ticker.info or {}).get("financialCurrency")',
                ),
            ),
            (
                '        data = [{"period_ending": str(key), **value} for key, value in data.items()]',
                lines(
                    "        data = [",
                    '            {"period_ending": str(key), **value, "reported_currency": reported_currency}',
                    "            for key, value in data.items()",
                    "        ]",
                ).rstrip("\n"),
            ),
        ]
    )
    rewrite("openbb-yfinance", relative_path, tuple(replacements))
