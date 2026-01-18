"""PDF format validation tools."""
import pdfplumber
from pathlib import Path
from typing import Dict, Any, List, Optional


class PDFValidator:
    """Validate generated PDF format against template."""
    
    def validate_structure(
        self, pdf_path: Path, template: Dict[str, Any]
    ) -> Dict[str, Any]:
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
    
    def _validate_table(
        self, table: List[List], table_config: Dict[str, Any]
    ) -> Dict[str, Any]:
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
    
    def compare_structure(
        self, real_pdf_path: Path, generated_pdf_path: Path
    ) -> Dict[str, Any]:
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
