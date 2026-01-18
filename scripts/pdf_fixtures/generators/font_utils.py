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
    # Try TTF files first (simpler), then TTC files with different subfont indices
    font_paths = [
        # macOS - Try TTF first if available, then TTC
        "/System/Library/Fonts/Supplemental/PingFangSC-Regular.otf",  # Try OTF
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
                    for subfont_idx in [0, 1]:
                        try:
                            pdfmetrics.registerFont(TTFont("ChineseFont", font_path, subfontIndex=subfont_idx))
                            # Test if the font actually works by checking if it's registered
                            if "ChineseFont" in pdfmetrics.getRegisteredFontNames():
                                return "ChineseFont"
                        except Exception:
                            continue
                elif font_path.endswith('.otf'):
                    # Try OTF file (OpenType)
                    try:
                        pdfmetrics.registerFont(TTFont("ChineseFont", font_path))
                        if "ChineseFont" in pdfmetrics.getRegisteredFontNames():
                            return "ChineseFont"
                    except Exception:
                        continue
                else:
                    # Regular TTF file
                    pdfmetrics.registerFont(TTFont("ChineseFont", font_path))
                    if "ChineseFont" in pdfmetrics.getRegisteredFontNames():
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
    # If we have a registered Chinese font, prioritize it for Chinese text
    # This ensures Chinese characters are displayed correctly
    if chinese_font:
        # If the template requests a Chinese font (SimHei, SimSun, etc.), use ChineseFont
        if any(x in font_family for x in ["Sim", "Hei", "Sun", "Song", "Ping", "ST"]):
            return chinese_font
        # For other fonts, still use ChineseFont if available to ensure Chinese text works
        # But allow standard fonts for pure English content
        standard_fonts = [
            "Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique",
            "Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic",
            "Courier", "Courier-Bold", "Courier-Oblique", "Courier-BoldOblique",
        ]
        if font_family in standard_fonts:
            return font_family
        # For unknown fonts, use ChineseFont to be safe
        return chinese_font
    
    # No Chinese font available - use standard fonts
    standard_fonts = [
        "Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique",
        "Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic",
        "Courier", "Courier-Bold", "Courier-Oblique", "Courier-BoldOblique",
    ]
    
    if font_family in standard_fonts:
        return font_family
    
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
