import os
import sys

# Ensure we can import from the root directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from common.meta.base.layering import PACKAGE_LAYER, LAYER_RANK
import importlib

def main():
    # Identify packages with contract.py
    packages = []
    for d in os.listdir("common"):
        if os.path.isdir(os.path.join("common", d)) and os.path.exists(os.path.join("common", d, "contract.py")):
            packages.append(d)
            
    # Group by layer
    by_layer = {}
    for layer in LAYER_RANK:
        by_layer[layer] = []
        
    for pkg in packages:
        # Load contract
        try:
            mod = importlib.import_module(f"common.{pkg}.contract")
            contract = getattr(mod, "contract", getattr(mod, "CONTRACT", None))
            if not contract:
                continue
                
            # Get description from module docstring
            desc = (mod.__doc__ or "").strip().split("\\n")[0]
            if not desc:
                desc = pkg
                
            # layer is defined by PACKAGE_LAYER or contract.klass
            layer = PACKAGE_LAYER.get(pkg) or contract.klass
            if layer:
                by_layer[layer].append((pkg, desc))
        except Exception as e:
            print(f"Failed to load contract for {pkg}: {e}")
            
    # Generate markdown
    lines = [
        "# `common/` — the package review surface",
        "",
        "`common/` is where the repo's **packages** live as specs and high-level review",
        "surfaces. A package is a DDD bounded context; each one is a directory",
        "`common/<pkg>/` holding its `readme.md` (ubiquitous language), `contract.py` (a",
        "machine-checkable `PackageContract`), and `todo.md` (its worklist).",
        "",
        "## Map",
        "",
        "Contract-carrying packages, by layer:",
        ""
    ]
    
    # Sort layers by rank
    sorted_layers = sorted(LAYER_RANK.keys(), key=lambda layer_name: LAYER_RANK[layer_name])
    
    for i, layer in enumerate(sorted_layers):
        pkgs_in_layer = sorted(by_layer[layer], key=lambda x: x[0])
        if not pkgs_in_layer:
            continue
            
        layer_desc = f"**L{i} {layer}**"
        
        pkg_items = []
        for pkg, desc in pkgs_in_layer:
            # handle multi-line desc
            desc_inline = desc.replace('\\n', ' ').strip()
            pkg_items.append(f"[`{pkg}/`](../{pkg}/readme.md): {desc_inline}")
            
        lines.append(f"- {layer_desc} — " + ", ".join(pkg_items))
        
    out_path = os.path.join("common", "meta", "data", "package-map.md")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        f.write("\n".join(lines) + "\n")
        
    print(f"Generated {out_path}")
    
    # Delete old readme if exists
    old_readme = os.path.join("common", "readme.md")
    if os.path.exists(old_readme):
        os.remove(old_readme)
        print(f"Deleted {old_readme}")

if __name__ == "__main__":
    main()
