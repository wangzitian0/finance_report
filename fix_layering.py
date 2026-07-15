with open('common/meta/base/layering.py', 'r') as f:
    content = f.read()

if "'ui_core': PackageLayer.L1," not in content:
    content = content.replace(
        "'reconciliation': PackageLayer.L1,",
        "'reconciliation': PackageLayer.L1,\n    'ui_core': PackageLayer.L1,"
    )
    with open('common/meta/base/layering.py', 'w') as f:
        f.write(content)

