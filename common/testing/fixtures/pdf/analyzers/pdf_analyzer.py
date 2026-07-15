"""PDF format analyzer - extracts format information from real PDFs."""
import pdfplumber
from pathlib import Path
from typing import Dict, List, Any, Optional


class PDFAnalyzer:
    """Analyze PDF structure and extract format information (not transaction data)."""
    
    def analyze(self, pdf_path: Path) -> Dict[str, Any]:
        """
        Analyze PDF and extract format information.
        
        Returns format template dict with:
        - page: size, margins
        - fonts: font families and sizes
        - table: column structure, widths, alignment
        - text_positions: key text element positions
        
        Does NOT extract transaction data or sensitive information.
        """
        template = {
            "page": {},
            "fonts": {},
            "tables": [],
            "text_positions": {},
        }
        
        try:
            with pdfplumber.open(pdf_path) as pdf:
                # Analyze first page (usually contains statement header)
                if len(pdf.pages) > 0:
                    first_page = pdf.pages[0]
                    
                    # Extract page dimensions
                    template["page"] = {
                        "width": float(first_page.width),
                        "height": float(first_page.height),
                        "size": self._detect_page_size(first_page.width, first_page.height),
                    }
                    
                    # Extract tables
                    tables = first_page.extract_tables()
                    if tables:
                        for table in tables:
                            table_info = self._analyze_table(table, first_page)
                            if table_info:
                                template["tables"].append(table_info)
                    
                    # Extract text positions (for key elements like "Transaction Details")
                    text = first_page.extract_text()
                    if text:
                        template["text_positions"] = self._analyze_text_positions(
                            first_page, text
                        )
        
        except Exception as e:
            raise ValueError(f"Failed to analyze PDF: {e}")
        
        return template
    
    def _detect_page_size(self, width: float, height: float) -> str:
        """Detect page size from dimensions."""
        # A4: 595.27 x 841.89 points (at 72 DPI)
        if abs(width - 595.27) < 10 and abs(height - 841.89) < 10:
            return "A4"
        elif abs(width - 612) < 10 and abs(height - 792) < 10:
            return "Letter"
        return "Custom"
    
    def _analyze_table(self, table: List[List], page) -> Optional[Dict[str, Any]]:
        """Analyze table structure."""
        if not table or len(table) < 2:
            return None
        
        # Get header row
        header = table[0] if table else []
        
        # Try to find table bounding box
        # This is approximate - pdfplumber doesn't always give exact positions
        columns = []
        for i, col_name in enumerate(header):
            if col_name:
                columns.append({
                    "name": str(col_name).strip(),
                    "index": i,
                    "width": None,  # Will be estimated
                })
        
        return {
            "header": [str(h).strip() for h in header if h],
            "columns": columns,
            "row_count": len(table) - 1,  # Exclude header
        }
    
    def _analyze_text_positions(self, page, text: str) -> Dict[str, Any]:
        """Analyze positions of key text elements."""
        positions = {}
        
        # Look for key phrases
        key_phrases = [
            "Transaction Details",
            "Account",
            "Statement Period",
            "Balance",
        ]
        
        for phrase in key_phrases:
            if phrase.lower() in text.lower():
                positions[phrase] = {
                    "found": True,
                    # Exact position would require more complex analysis
                }
        
        return positions


class TemplateExtractor:
    """Convert analysis results to YAML template format."""
    
    def extract(self, analysis: Dict[str, Any], source: str) -> Dict[str, Any]:
        """
        Convert analysis to template format.
        
        Args:
            analysis: Result from PDFAnalyzer.analyze()
            source: Source identifier (dbs, cmb, mari)
        
        Returns:
            Template dict in YAML-serializable format
        """
        template = {
            "source": source,
            "page": analysis.get("page", {}),
            "fonts": self._extract_fonts(source),
            "tables": self._extract_table_structure(analysis, source),
        }
        
        return template
    
    def _extract_fonts(self, source: str) -> Dict[str, Any]:
        """Extract font configuration based on source."""
        # Default fonts - can be refined based on analysis
        fonts = {
            "header": {
                "family": "Helvetica-Bold",
                "size": 14,
            },
            "body": {
                "family": "Helvetica",
                "size": 10,
            },
            "table_header": {
                "family": "Helvetica-Bold",
                "size": 9,
            },
        }
        
        if source == "cmb" or source == "pingan":
            # CMB and Pingan use Chinese fonts
            fonts["body"]["family"] = "SimSun"  # 宋体
            fonts["table_header"]["family"] = "SimHei"  # 黑体
        
        return fonts
    
    def _extract_table_structure(self, analysis: Dict[str, Any], source: str) -> Dict[str, Any]:
        """Extract table structure based on source and analysis."""
        # Base structure on known formats from adapters
        if source == "dbs":
            return {
                "transaction_details": {
                    "columns": [
                        {"name": "Date", "width": 70, "align": "left"},
                        {"name": "Description", "width": 200, "align": "left"},
                        {"name": "Withdrawal", "width": 60, "align": "right"},
                        {"name": "Deposit", "width": 60, "align": "right"},
                        {"name": "Balance", "width": 70, "align": "right"},
                    ],
                    "header_style": {
                        "background": "#CCCCCC",
                        "text_color": "#000000",
                    },
                }
            }
        elif source == "cmb":
            return {
                "transaction_details": {
                    "columns": [
                        {"name": "记账日期", "width": 80, "align": "left"},
                        {"name": "货币", "width": 50, "align": "left"},
                        {"name": "交易金额", "width": 80, "align": "right"},
                        {"name": "联机余额", "width": 90, "align": "right"},
                        {"name": "交易摘要", "width": 150, "align": "left"},
                        {"name": "对手信息", "width": 100, "align": "left"},
                    ],
                    "header_style": {
                        "background": "#CCCCCC",
                        "text_color": "#000000",
                    },
                }
            }
        elif source == "mari":
            return {
                "transaction_details": {
                    "columns": [
                        {"name": "DATE", "width": 60, "align": "left"},
                        {"name": "TRANSACTION", "width": 200, "align": "left"},
                        {"name": "OUTGOING (SGD)", "width": 80, "align": "right"},
                        {"name": "INCOMING (SGD)", "width": 80, "align": "right"},
                    ],
                    "header_style": {
                        "background": "#CCCCCC",
                        "text_color": "#000000",
                    },
                }
            }
        elif source == "moomoo":
            return {
                "transaction_details": {
                    "columns": [
                        {"name": "Date", "width": 80, "align": "left"},
                        {"name": "Type", "width": 100, "align": "left"},
                        {"name": "Description", "width": 200, "align": "left"},
                        {"name": "Amount", "width": 100, "align": "right"},
                        {"name": "Currency", "width": 60, "align": "left"},
                    ],
                    "header_style": {
                        "background": "#CCCCCC",
                        "text_color": "#000000",
                    },
                }
            }
        elif source == "pingan":
            return {
                "transaction_details": {
                    "columns": [
                        {"name": "交易日期", "width": 80, "align": "left"},
                        {"name": "交易类型", "width": 100, "align": "left"},
                        {"name": "交易金额", "width": 90, "align": "right"},
                        {"name": "余额", "width": 90, "align": "right"},
                        {"name": "交易摘要", "width": 150, "align": "left"},
                    ],
                    "header_style": {
                        "background": "#CCCCCC",
                        "text_color": "#000000",
                    },
                }
            }
        
        return {}
