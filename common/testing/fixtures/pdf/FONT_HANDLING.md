# PDF Fixture Font Handling

Font fallback policy is owned by
[`common/testing/readme.md#pdf-fixtures`](../../readme.md#pdf-fixtures).

The implementation lives in `generators/font_utils.py`:

- `register_chinese_fonts()`
- `get_safe_font()`
- `can_display_chinese()`

Quick check:

```bash
python -c "from common.testing.fixtures.pdf.generators.font_utils import register_chinese_fonts; print(register_chinese_fonts())"
```
