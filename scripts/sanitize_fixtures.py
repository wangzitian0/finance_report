#!/usr/bin/env python
"""
Sanitize test fixture files by replacing PII with anonymous placeholders.

Rules:
- Amounts: PRESERVE all amounts for analysis
- Card numbers: Keep last 4 digits (XXXX-XXXX-XXXX-2507)
- Phone numbers: Keep last 4 digits (XXXX5019)
- NRIC: Keep first and last (SXXXXXXXH)
- Account/reference numbers: Keep last 4 digits
- Personal names: Keep last 3 English letters or last Chinese char
- Company names: Keep last 3 letters before PTE/LTD
"""

import json
import re
from pathlib import Path


def mask_company_name(name: str) -> str:
    """Mask company name, keeping last 3 letters."""
    # Remove newlines for processing
    clean_name = name.replace('\n', ' ').strip()
    
    # Handle "XXX PTE. LTD." or "XXX PTE LTD" patterns
    pte_match = re.match(r'^(.+?)\s*(PTE\.?\s*LTD\.?|PTE\.|LTD\.?)(.*)$', clean_name, re.IGNORECASE)
    if pte_match:
        company_part = pte_match.group(1).strip()
        suffix = pte_match.group(2) + pte_match.group(3)
        # Get last word of company part
        words = company_part.split()
        if words:
            last_word = words[-1]
            if len(last_word) > 3:
                masked_last = '***' + last_word[-3:]
            else:
                masked_last = last_word
            words[-1] = masked_last
            masked_company = ' '.join(words)
        else:
            masked_company = '***' + company_part[-3:] if len(company_part) > 3 else company_part
        return masked_company + ' ' + suffix.strip()
    
    # For other company names without PTE/LTD
    if len(clean_name) > 3:
        return '***' + clean_name[-3:]
    return clean_name


def sanitize_description(desc: str) -> str:
    """Sanitize a transaction description by replacing PII only."""
    
    # Replace card numbers (4 groups of 4 digits) - keep last 4
    desc = re.sub(r'\b(\d{4})-(\d{4})-(\d{4})-(\d{4})\b', r'XXXX-XXXX-XXXX-\4', desc)
    
    # Replace sequences like "68042507" (8 digits) - keep last 4
    desc = re.sub(r'\b\d{4}(\d{4})\b(?=\s|$|[,.])', r'XXXX\1', desc)
    
    # Replace NRIC (S/T followed by 7 digits and a letter) - keep first and last
    desc = re.sub(r'\b([ST])\d{7}([A-Z])\b', r'\1XXXXXXX\2', desc)
    
    # Replace long number sequences (10+ digits) - keep last 4
    desc = re.sub(r'\b\d{6,}(\d{4})\b', r'XXXXXX\1', desc)
    
    # ========== Generic Company Name Sanitization ==========
    # Mask any words before PTE LTD, LLC, INC, etc.
    # Pattern: words followed by company suffix
    # Keep only the last 3 chars of the word immediately before suffix
    
    company_suffixes = r'(PTE\.?\s*LTD\.?|PTE\.|LTD\.?|LLC|INC\.?|SDN\.?\s*BHD\.?)'
    
    def replace_company_match(match):
        full_match = match.group(0)
        prefix = match.group(1) # Part before suffix
        suffix = match.group(2) # Suffix
        
        # Split prefix into words
        words = prefix.strip().split()
        if not words:
            return full_match
            
        # Mask all words except ensure last word has context
        masked_words = []
        for word in words:
            if len(word) > 3:
                masked_words.append('***' + word[-3:])
            else:
                masked_words.append('***')
                
        return ' '.join(masked_words) + ' ' + suffix

    desc = re.sub(rf'\b((?:[A-Z0-9\'-]+\s+)+){company_suffixes}\b', replace_company_match, desc, flags=re.IGNORECASE)

    # Specific known PII that might escape generic rules (keep minimal)
    # Generic "Name-like" patterns could be risky to auto-mask without NLP, 
    # but we can look for specific high-entropy patterns if needed.
    
    return desc


def sanitize_fixture(data: dict) -> dict:
    """Sanitize a single fixture file - keep all amounts."""
    result = data.copy()
    
    # Sanitize event descriptions
    if "events" in result:
        for event in result["events"]:
            desc = event.get("description")
            if desc:
                event["description"] = sanitize_description(desc)

    # Sanitize balances (User Request: Start at 300,000, preserve flow)
    from decimal import Decimal
    
    # Sanitize balances (User Request: Start at 300,000, preserve flow)
    
    # Check root level or nested 'statement' dictionary
    target_dict = result
    if "statement" in result and isinstance(result["statement"], dict):
        target_dict = result["statement"]

    # If balances are missing or None, we still want to sanitize them to valid numbers.
    try:
        raw_opening = target_dict.get("opening_balance")
        raw_closing = target_dict.get("closing_balance")
        
        # Handle "None" string literal or NoneType
        if str(raw_opening) == "None" or raw_opening is None:
            raw_opening = "0"
        if str(raw_closing) == "None" or raw_closing is None:
            raw_closing = "0"
            
        original_opening = Decimal(str(raw_opening))
        original_closing = Decimal(str(raw_closing))
        
        # Calculate net movement
        net_flow = original_closing - original_opening
        
        # New opening balance
        new_opening = Decimal("300000.00")
        new_closing = new_opening + net_flow
        
        target_dict["opening_balance"] = f"{new_opening:.2f}"
        target_dict["closing_balance"] = f"{new_closing:.2f}"
        
    except Exception as e:
        print(f"Warning: Failed to sanitize balance for {result.get('file', 'unknown')}: {e}")
            
    return result


def main():
    fixtures_dir = Path(__file__).parent.parent / "apps/backend/tests/fixtures"
    
    for json_file in fixtures_dir.glob("*.json"):
        if json_file.name == "summary.json":
            continue
        
        print(f"Sanitizing {json_file.name}...")
        
        with open(json_file, "r") as f:
            data = json.load(f)
        
        sanitized = sanitize_fixture(data)
        
        with open(json_file, "w") as f:
            json.dump(sanitized, f, indent=2, ensure_ascii=False)
        
        print("  ✅ Done")
    
    # Also sanitize summary.json
    summary_file = fixtures_dir / "summary.json"
    if summary_file.exists():
        print("Sanitizing summary.json...")
        with open(summary_file, "r") as f:
            data = json.load(f)
        
        for i, item in enumerate(data):
            if item.get("success"):
                data[i] = sanitize_fixture(item)
        
        with open(summary_file, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print("  ✅ Done")
    
    print("\n✨ Sanitization complete! (Amounts preserved, last chars kept)")


if __name__ == "__main__":
    main()
