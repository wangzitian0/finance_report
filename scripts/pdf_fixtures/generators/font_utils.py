"""Font utilities for handling non-English fonts in reportlab."""
from pathlib import Path
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from typing import Optional


def register_chinese_fonts() -> Optional[str]:
    """
    Register Chinese fonts from system if available.
    
    Returns:
        Font name if registered successfully, None otherwise
    """
    # Common Chinese font paths on different systems
    font_paths = [
        # macOS - Found fonts
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Supplemental/PingFang.ttc",
        # Linux
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/arphic/uming.ttc",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        # Windows (if running on Windows)
        "C:/Windows/Fonts/simsun.ttc",
        "C:/Windows/Fonts/simhei.ttf",
    ]
    
    for font_path in font_paths:
        if Path(font_path).exists():
            try:
                # For TTC files, try different subfont indices (0, 1, etc.)
                # TTC files contain multiple fonts in one file
                if font_path.endswith('.ttc'):
                    # Try subfontIndex 0 first (most common)
                    try:
                        pdfmetrics.registerFont(TTFont("ChineseFont", font_path, subfontIndex=0))
                        return "ChineseFont"
                    except Exception:
                        # Try subfontIndex 1 if 0 fails
                        try:
                            pdfmetrics.registerFont(TTFont("ChineseFont", font_path, subfontIndex=1))
                            return "ChineseFont"
                        except Exception:
                            continue
                else:
                    # Regular TTF file
                    pdfmetrics.registerFont(TTFont("ChineseFont", font_path))
                    return "ChineseFont"
            except Exception as e:
                # Log error for debugging but continue trying other fonts
                continue
    
    return None


def get_safe_font(font_family: str, chinese_font: Optional[str] = None) -> str:
    """
    Get a safe font that can handle the text.
    
    Args:
        font_family: Desired font family from template
        chinese_font: Registered Chinese font name (if available)
    
    Returns:
        Safe font name that reportlab can use
    """
    # Standard reportlab fonts
    safe_fonts = [
        "Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique",
        "Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic",
        "Courier", "Courier-Bold", "Courier-Oblique", "Courier-BoldOblique",
    ]
    
    # If font is already safe, use it
    if font_family in safe_fonts:
        return font_family
    
    # If we have Chinese font and the requested font is Chinese, use it
    if chinese_font and ("Sim" in font_family or "Hei" in font_family or "Sun" in font_family):
        return chinese_font
    
    # Fallback based on style
    if "Bold" in font_family or "Hei" in font_family:
        return "Helvetica-Bold"
    else:
        return "Helvetica"


def can_display_chinese(font_name: str) -> bool:
    """
    Check if a font can display Chinese characters.
    
    Args:
        font_name: Font name to check
    
    Returns:
        True if font can display Chinese, False otherwise
    """
    # Standard reportlab fonts cannot display Chinese
    standard_fonts = [
        "Helvetica", "Times-Roman", "Courier",
        "Helvetica-Bold", "Times-Bold", "Courier-Bold",
    ]
    
    if font_name in standard_fonts:
        return False
    
    # If it's a registered custom font (like ChineseFont), assume it can
    if font_name == "ChineseFont":
        return True
    
    return False
