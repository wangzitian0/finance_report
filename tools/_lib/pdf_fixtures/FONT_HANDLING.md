# PDF Fixture Font Handling

Font fallback policy is owned by
[`docs/ssot/pdf-fixtures.md`](../../../docs/ssot/pdf-fixtures.md#font-fallback).

The implementation lives in `generators/font_utils.py`:

- `register_chinese_fonts()`
- `get_safe_font()`
- `can_display_chinese()`

Quick check:

```bash
python -c "from tools._lib.pdf_fixtures.generators.font_utils import register_chinese_fonts; print(register_chinese_fonts())"
```
