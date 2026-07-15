"""PDF format validation tools."""

import re
from pathlib import Path
from typing import Any

import pdfplumber

ValidationResult = dict[str, Any]


class PDFValidator:
    """Validate generated PDF format against template."""
    
    def validate_structure(
        self, pdf_path: Path, template: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Validate PDF structure against template.
        
        Returns:
            Validation result with success flag and details
        """
        result = {
            "success": True,
            "errors": [],
            "warnings": [],
        }
        
        try:
            with pdfplumber.open(pdf_path) as pdf:
                if len(pdf.pages) == 0:
                    result["success"] = False
                    result["errors"].append("PDF has no pages")
                    return result
                
                first_page = pdf.pages[0]
                
                # Validate page size
                page_info = template.get("page", {})
                expected_width = page_info.get("width", 595.27)
                expected_height = page_info.get("height", 841.89)
                
                if abs(first_page.width - expected_width) > 10:
                    result["warnings"].append(
                        f"Page width mismatch: expected ~{expected_width}, got {first_page.width}"
                    )
                
                if abs(first_page.height - expected_height) > 10:
                    result["warnings"].append(
                        f"Page height mismatch: expected ~{expected_height}, got {first_page.height}"
                    )
                
                # Validate table structure
                tables = first_page.extract_tables()
                if tables:
                    table_config = template.get("tables", {}).get("transaction_details")
                    if table_config:
                        table_validation = self._validate_table(
                            tables[0], table_config
                        )
                        if not table_validation["success"]:
                            result["success"] = False
                            result["errors"].extend(table_validation["errors"])
                        result["warnings"].extend(table_validation["warnings"])
                
                # Validate key phrases
                text = first_page.extract_text() or ""
                key_phrase = table_config.get("key_phrase") if table_config else None
                if key_phrase and key_phrase.lower() not in text.lower():
                    result["warnings"].append(
                        f"Key phrase '{key_phrase}' not found in PDF"
                    )
        
        except Exception as e:
            result["success"] = False
            result["errors"].append(f"Validation error: {e}")
        
        return result

    def validate_real_format_contract(self, template: dict[str, Any]) -> ValidationResult:
        """Validate sanitized real-format metadata embedded in a template."""
        result: ValidationResult = {"success": True, "errors": [], "warnings": []}
        contract = template.get("real_format_contract")
        if not isinstance(contract, dict):
            result["success"] = False
            result["errors"].append("real_format_contract is required")
            return result

        source = template.get("source")
        if contract.get("source") != source:
            result["success"] = False
            result["errors"].append(
                f"real_format_contract source mismatch: expected {source}, got {contract.get('source')}"
            )

        if contract.get("sensitive_data_policy") != "sanitized_format_metadata_only":
            result["success"] = False
            result["errors"].append("real_format_contract must use sanitized_format_metadata_only policy")

        tolerances = contract.get("tolerances", {})
        for key in ("page_size_points", "column_width_points"):
            value = tolerances.get(key)
            if not isinstance(value, (int, float)) or value <= 0:
                result["success"] = False
                result["errors"].append(f"real_format_contract tolerances.{key} must be positive")

        source_formats = contract.get("source_formats", {})
        date_regex = source_formats.get("date_regex")
        if not isinstance(date_regex, str) or not date_regex:
            result["success"] = False
            result["errors"].append("real_format_contract source_formats.date_regex is required")
        else:
            try:
                re.compile(date_regex)
            except re.error as exc:
                result["success"] = False
                result["errors"].append(f"real_format_contract date_regex is invalid: {exc}")

        expected_currency = template.get("text_elements", {}).get("currency")
        if source_formats.get("currency") != expected_currency:
            result["success"] = False
            result["errors"].append(
                "real_format_contract currency drift: "
                f"expected {expected_currency}, got {source_formats.get('currency')}"
            )

        template_table = template.get("tables", {}).get("transaction_details", {})
        template_columns = template_table.get("columns", [])
        table_contract = contract.get("tables", {}).get("transaction_details")
        if not isinstance(table_contract, dict):
            result["success"] = False
            result["errors"].append("real_format_contract tables.transaction_details is required")
            return result

        expected_column_names = [column.get("name") for column in template_columns]
        expected_widths = [column.get("width") for column in template_columns]
        if table_contract.get("columns") != expected_column_names:
            result["success"] = False
            result["errors"].append(
                "real_format_contract transaction_details column names drift from template columns"
            )
        if table_contract.get("column_widths") != expected_widths:
            result["success"] = False
            result["errors"].append(
                "real_format_contract transaction_details column widths drift from template columns"
            )
        min_rows = table_contract.get("min_rows")
        if not isinstance(min_rows, int) or min_rows <= 0:
            result["success"] = False
            result["errors"].append("real_format_contract transaction_details.min_rows must be positive")

        return result

    def validate_generated_pdf_against_real_format_contract(
        self,
        pdf_path: Path,
        template: dict[str, Any],
    ) -> ValidationResult:
        """Validate generated PDF structure against the sanitized real-format contract."""
        result = self.validate_real_format_contract(template)
        if not result["success"]:
            return result

        contract = template["real_format_contract"]
        table_contract = contract["tables"]["transaction_details"]
        source_formats = contract["source_formats"]
        tolerances = contract["tolerances"]
        expected_columns = table_contract["columns"]
        expected_column_count = len(expected_columns)
        date_pattern = re.compile(source_formats["date_regex"])

        try:
            with pdfplumber.open(pdf_path) as pdf:
                if not pdf.pages:
                    result["success"] = False
                    result["errors"].append("PDF has no pages")
                    return result

                first_page = pdf.pages[0]
                page_config = template.get("page", {})
                page_tolerance = tolerances["page_size_points"]
                if abs(first_page.width - page_config.get("width", first_page.width)) > page_tolerance:
                    result["success"] = False
                    result["errors"].append("Generated PDF page width is outside real-format tolerance")
                if abs(first_page.height - page_config.get("height", first_page.height)) > page_tolerance:
                    result["success"] = False
                    result["errors"].append("Generated PDF page height is outside real-format tolerance")

                text = "\n".join(page.extract_text() or "" for page in pdf.pages)
                currency = source_formats["currency"]
                if currency not in text:
                    result["success"] = False
                    result["errors"].append(f"Generated PDF does not expose currency marker {currency}")

                for phrase in contract.get("key_text", []):
                    if phrase not in text:
                        result["success"] = False
                        result["errors"].append(f"Generated PDF missing key text phrase: {phrase}")

                matching_rows: list[list[str]] = []
                for page in pdf.pages:
                    for table in page.extract_tables() or []:
                        if not table:
                            continue
                        header = [str(cell or "").strip() for cell in table[0]]
                        if len(header) != expected_column_count:
                            continue
                        if not self._header_matches(header, expected_columns):
                            continue
                        for row in table[1:]:
                            normalized = [str(cell or "").strip() for cell in row[:expected_column_count]]
                            if normalized and date_pattern.match(normalized[0]):
                                matching_rows.append(normalized)

                if len(matching_rows) < table_contract["min_rows"]:
                    result["success"] = False
                    result["errors"].append(
                        "Generated PDF transaction_details rows below real-format minimum: "
                        f"expected at least {table_contract['min_rows']}, got {len(matching_rows)}"
                    )

        except Exception as e:
            result["success"] = False
            result["errors"].append(f"Validation error: {e}")

        return result
    
    def _validate_table(
        self, table: list[list], table_config: dict[str, Any]
    ) -> dict[str, Any]:
        """Validate table structure."""
        result = {
            "success": True,
            "errors": [],
            "warnings": [],
        }
        
        if not table or len(table) < 2:
            result["success"] = False
            result["errors"].append("Table is empty or has no data rows")
            return result
        
        # Check column count
        expected_columns = table_config.get("columns", [])
        header = table[0] if table else []
        
        if len(header) != len(expected_columns):
            result["warnings"].append(
                f"Column count mismatch: expected {len(expected_columns)}, got {len(header)}"
            )
        
        # Check column names (approximate match)
        for i, expected_col in enumerate(expected_columns):
            if i < len(header):
                expected_name = expected_col.get("name", "").lower()
                actual_name = str(header[i]).lower() if header[i] else ""
                if expected_name and expected_name not in actual_name:
                    result["warnings"].append(
                        f"Column {i} name mismatch: expected '{expected_name}', got '{actual_name}'"
                    )
        
        return result

    def _header_matches(self, header: list[str], expected_columns: list[str]) -> bool:
        if len(header) != len(expected_columns):
            return False
        for actual, expected in zip(header, expected_columns, strict=True):
            expected_normalized = expected.lower().replace(" ", "")
            actual_normalized = actual.lower().replace(" ", "")
            if expected_normalized not in actual_normalized and actual_normalized not in expected_normalized:
                return False
        return True
    
    def compare_structure(
        self, real_pdf_path: Path, generated_pdf_path: Path
    ) -> dict[str, Any]:
        """
        Compare structure of real PDF and generated PDF.
        
        This is for local validation only (real PDF not committed).
        """
        result = {
            "success": True,
            "differences": [],
        }
        
        try:
            with pdfplumber.open(real_pdf_path) as real_pdf, \
                 pdfplumber.open(generated_pdf_path) as gen_pdf:
                
                # Compare page count
                if len(real_pdf.pages) != len(gen_pdf.pages):
                    result["differences"].append(
                        f"Page count: real={len(real_pdf.pages)}, generated={len(gen_pdf.pages)}"
                    )
                
                # Compare first page tables
                if len(real_pdf.pages) > 0 and len(gen_pdf.pages) > 0:
                    real_tables = real_pdf.pages[0].extract_tables()
                    gen_tables = gen_pdf.pages[0].extract_tables()
                    
                    if len(real_tables) != len(gen_tables):
                        result["differences"].append(
                            f"Table count: real={len(real_tables)}, generated={len(gen_tables)}"
                        )
        
        except Exception as e:
            result["success"] = False
            result["error"] = str(e)
        
        return result
