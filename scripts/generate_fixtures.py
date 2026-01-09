#!/usr/bin/env python
"""
Test script to parse documents from tmp/input/ and generate fixtures.

Features:
- Caches raw model outputs in tmp/output/ to avoid re-running API calls
- Use --no-cache to force fresh API calls
- Sanitization is a separate step (run sanitize_fixtures.py after)
"""

import asyncio
import json
import sys
from pathlib import Path


# Add backend src to path
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root / "apps/backend"))

# Load env from repo root
from dotenv import load_dotenv  # noqa: E402
load_dotenv(repo_root / ".env")



def get_cache_path(file_path: Path, output_dir: Path) -> Path:
    """Get cache file path for a given input file."""
    return output_dir / f"{file_path.stem}_raw.json"


async def parse_with_cache(
    file_path: Path, 
    institution: str, 
    output_dir: Path,
    use_cache: bool = True,
) -> dict:
    """Parse file, using cache if available."""
    cache_path = get_cache_path(file_path, output_dir)
    
    # Try to load from cache
    if use_cache and cache_path.exists():
        print(f"   📦 Loading from cache: {cache_path.name}")
        with open(cache_path, "r") as f:
            return json.load(f)
    
    # Call API via ExtractionService
    print("   🌐 Calling Gemini API...")
    
    # Initialize service
    from src.services.extraction import ExtractionService
    service = ExtractionService()
    
    # Read file content
    file_content = file_path.read_bytes()
    ext = file_path.suffix.lower().lstrip(".")
    
    # Get raw response using service (DRY compliant)
    # This reuses the service's base64 encoding, prompt generation, and error handling
    raw_response = await service.extract_financial_data(
        file_content=file_content,
        institution=institution,
        file_type=ext,
        return_raw=True
    )
    
    # Extract content for local processing/validation
    content_str = raw_response["choices"][0]["message"]["content"]
    
    # Parse JSON (keep local logic for now as it handles specific markdown stripping)
    try:
        extracted = json.loads(content_str)
    except json.JSONDecodeError:
        # Try to extract from markdown code blocks
        import re
        json_match = re.search(r"```json\s*(.*?)\s*```", content_str, re.DOTALL)
        if json_match:
            extracted = json.loads(json_match.group(1))
        else:
            extracted = {"error": "Failed to parse JSON", "raw": content_str}
    
    # Save to cache
    cache_data = {
        "file": file_path.name,
        "institution": institution,
        "raw_response": raw_response,
        "extracted": extracted,
    }
    
    with open(cache_path, "w") as f:
        json.dump(cache_data, f, indent=2, ensure_ascii=False)
    print(f"   💾 Saved to cache: {cache_path.name}")
    
    return cache_data


def process_extracted_data(cache_data: dict) -> dict:
    """Process extracted data into fixture format."""
    extracted = cache_data.get("extracted", {})
    
    # Handle case where Gemini returns an array instead of object
    if isinstance(extracted, list):
        if len(extracted) > 0:
            extracted = extracted[0]
        else:
            return {
                "file": cache_data["file"],
                "institution": cache_data["institution"],
                "success": False,
                "error": "Empty array response",
            }
    
    if "error" in extracted:
        return {
            "file": cache_data["file"],
            "institution": cache_data["institution"],
            "success": False,
            "error": extracted.get("error"),
        }
    
    try:
        return {
            "file": cache_data["file"],
            "institution": cache_data["institution"],
            "success": True,
            "statement": {
                "period_start": extracted.get("period_start"),
                "period_end": extracted.get("period_end"),
                "opening_balance": str(extracted.get("opening_balance", "0")),
                "closing_balance": str(extracted.get("closing_balance", "0")),
                "currency": extracted.get("currency", "SGD"),
                "confidence_score": 100,  # Will be recalculated
                "balance_validated": True,
                "validation_error": None,
            },
            "events": [
                {
                    "date": str(txn.get("date")),
                    "description": txn.get("description", ""),
                    "amount": str(txn.get("amount", "0")),
                    "direction": txn.get("direction", "OUT"),
                    "confidence": "high",
                }
                for txn in extracted.get("transactions", [])
                if txn.get("date") and txn.get("date") not in ("None", "UNKNOWN", "")
            ],
        }
    except Exception as e:
        return {
            "file": cache_data["file"],
            "institution": cache_data["institution"],
            "success": False,
            "error": f"Processing error: {e}",
        }


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-cache", action="store_true", help="Force fresh API calls")
    args = parser.parse_args()
    
    input_dir = repo_root / "tmp/input"
    output_dir = repo_root / "tmp/output"
    fixtures_dir = repo_root / "apps/backend/tests/fixtures"
    
    output_dir.mkdir(parents=True, exist_ok=True)
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    
    # Map files to institutions
    file_mappings = {
        "2504.pdf": "DBS",
        "Apr2025_MariBank_e-Statement.pdf": "MariBank",
        "moomoo-2504.pdf": "Moomoo",
        "futu-2506.pdf": "Futu",
        "gxs-2506.pdf": "GXS",
        "2024-2025.pdf": "CMB",
        "2025.pdf": "CMB",
    }
    
    results = []
    for filename, institution in file_mappings.items():
        file_path = input_dir / filename
        if not file_path.exists():
            print(f"⚠️  Skipping {filename} (not found)")
            continue
        
        print(f"📄 Processing {filename} ({institution})...")
        
        try:
            cache_data = await parse_with_cache(
                file_path, institution, output_dir, 
                use_cache=not args.no_cache
            )
            result = process_extracted_data(cache_data)
        except Exception as e:
            result = {
                "file": filename,
                "institution": institution,
                "success": False,
                "error": f"{type(e).__name__}: {e}",
            }
        
        results.append(result)
        
        if result["success"]:
            print(f"   ✅ {len(result.get('events', []))} events")
            
            # Save individual fixture
            fixture_name = filename.replace(".pdf", "_parsed.json").replace(" ", "_")
            with open(fixtures_dir / fixture_name, "w") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
        else:
            print(f"   ❌ {result.get('error', 'Unknown error')}")
    
    # Save summary
    with open(fixtures_dir / "summary.json", "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    print(f"\n✨ Raw outputs cached in: {output_dir}/")
    print(f"✨ Fixtures saved to: {fixtures_dir}/")
    print("\n💡 Run 'python scripts/sanitize_fixtures.py' to mask PII")


if __name__ == "__main__":
    asyncio.run(main())
