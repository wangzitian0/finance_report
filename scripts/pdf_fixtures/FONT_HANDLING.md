# 非英语字体处理方案

## 问题

reportlab 默认不支持中文字体（SimSun、SimHei 等），导致中文字符显示为黑色方块（⬛️）。

## 通用解决方案

### 1. 字体注册工具 (`generators/font_utils.py`)

提供通用的字体处理函数：

- `register_chinese_fonts()`: 自动检测并注册系统中文字体
  - macOS: STHeiti, Songti, PingFang
  - Linux: wqy-microhei, uming
  - Windows: simsun, simhei

- `get_safe_font()`: 获取安全的字体（如果中文字体不可用，回退到 Helvetica）

- `can_display_chinese()`: 检查字体是否支持中文

### 2. 使用方式

```python
from generators.font_utils import register_chinese_fonts, get_safe_font, can_display_chinese

# 注册中文字体（如果可用）
chinese_font = register_chinese_fonts()

# 获取安全字体
safe_font = get_safe_font("SimHei", chinese_font)

# 检查是否可以使用中文
if can_display_chinese(safe_font):
    text = "招商银行"
else:
    text = "China Merchants Bank"
```

### 3. 当前实现

**CMB 和 Pingan 生成器：**
- 自动检测并注册系统中文字体
- 如果中文字体可用，使用中文文本
- 如果不可用，自动回退到英文文本

**数据生成：**
- 所有交易描述使用英文（避免字体问题）
- 表头根据字体支持情况选择中文或英文

### 4. 字体路径

系统会自动检测以下路径：

**macOS:**
- `/System/Library/Fonts/STHeiti Medium.ttc`
- `/System/Library/Fonts/STHeiti Light.ttc`
- `/System/Library/Fonts/Supplemental/Songti.ttc`

**Linux:**
- `/usr/share/fonts/truetype/wqy/wqy-microhei.ttc`
- `/usr/share/fonts/truetype/arphic/uming.ttc`

**Windows:**
- `C:/Windows/Fonts/simsun.ttc`
- `C:/Windows/Fonts/simhei.ttf`

### 5. 验证

运行以下命令验证字体注册：

```bash
cd scripts/pdf_fixtures
python -c "from generators.font_utils import register_chinese_fonts; print(register_chinese_fonts())"
# 应该输出: ChineseFont (如果成功) 或 None (如果失败)
```

## 注意事项

1. **字体注册是全局的**：一旦注册成功，所有 PDF 生成都可以使用
2. **自动回退**：如果中文字体不可用，自动使用英文，确保 PDF 可以正常生成
3. **跨平台兼容**：在不同操作系统上自动检测对应的字体路径
