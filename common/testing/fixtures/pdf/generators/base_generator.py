"""Base PDF generator class."""
import yaml
from pathlib import Path
from typing import Dict, Any
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, TableStyle


class BasePDFGenerator:
    """Base class for PDF generators."""
    
    def __init__(self, template_path: Path):
        """Initialize generator with format template."""
        self.template = self._load_template(template_path)
        self.source = self.template.get("source", "unknown")
    
    def _load_template(self, template_path: Path) -> Dict[str, Any]:
        """Load format template from YAML file."""
        if not template_path.exists():
            raise FileNotFoundError(f"Template not found: {template_path}")
        
        with open(template_path, "r") as f:
            return yaml.safe_load(f)
    
    def _get_page_size(self):
        """Get page size from template."""
        page_info = self.template.get("page", {})
        size = page_info.get("size", "A4")
        return A4 if size == "A4" else A4  # Default to A4
    
    def _get_margins(self):
        """Get margins from template."""
        margins = self.template.get("page", {}).get("margins", {})
        return (
            margins.get("left", 72),
            margins.get("bottom", 72),
            margins.get("right", 72),
            margins.get("top", 72),
        )
    
    def _get_font(self, font_type: str = "body") -> tuple[str, int]:
        """Get font family and size from template."""
        fonts = self.template.get("fonts", {})
        font_info = fonts.get(font_type, fonts.get("body", {}))
        font_family = font_info.get("family", "Helvetica")
        # Fallback to Helvetica if font not available in reportlab
        if font_family not in ["Helvetica", "Helvetica-Bold", "Times-Roman", "Courier", "Times-Bold"]:
            if "Bold" in font_family or "Hei" in font_family:
                font_family = "Helvetica-Bold"
            else:
                font_family = "Helvetica"
        return (
            font_family,
            font_info.get("size", 10),
        )
    
    def _create_table_style(self, table_config: Dict[str, Any], table_font: str = None) -> TableStyle:
        """Create table style from template."""
        header_style = table_config.get("header_style", {})
        row_style = table_config.get("row_style", {})
        
        # Use provided font or get from template
        if table_font is None:
            table_font = self._get_font("table_header")[0]
        table_font_size = self._get_font("table_header")[1]
        
        commands = [
            # Header styling
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(header_style.get("background", "#CCCCCC"))),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor(header_style.get("text_color", "#000000"))),
            ("FONTNAME", (0, 0), (-1, 0), table_font),
            ("FONTSIZE", (0, 0), (-1, 0), table_font_size),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
            ("TOPPADDING", (0, 0), (-1, 0), 12),
        ]
        
        # Row styling
        if row_style.get("background"):
            commands.append(
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor(row_style["background"]))
            )
        
        if row_style.get("border"):
            commands.append(
                ("GRID", (0, 0), (-1, -1), 1, colors.black)
            )
        
        # Column alignment
        columns = table_config.get("columns", [])
        for i, col in enumerate(columns):
            align = col.get("align", "left")
            if align == "right":
                commands.append(("ALIGN", (i, 1), (i, -1), "RIGHT"))
            elif align == "center":
                commands.append(("ALIGN", (i, 1), (i, -1), "CENTER"))
            else:
                commands.append(("ALIGN", (i, 1), (i, -1), "LEFT"))
        
        return TableStyle(commands)
    
    def _get_column_widths(self, table_config: Dict[str, Any]) -> list[float]:
        """Get column widths from template."""
        columns = table_config.get("columns", [])
        return [col.get("width", 100) for col in columns]
    
    def create_document(self, output_path: Path):
        """Create PDF document with configured page size and margins."""
        page_size = self._get_page_size()
        margins = self._get_margins()
        
        return SimpleDocTemplate(
            str(output_path),
            pagesize=page_size,
            leftMargin=margins[0],
            bottomMargin=margins[1],
            rightMargin=margins[2],
            topMargin=margins[3],
        )
