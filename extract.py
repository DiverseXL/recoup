import re
import os

bundle_dir = r"C:\Users\MY PC\Documents\recoup-production\bundle"
index_path = os.path.join(bundle_dir, "index.html")
style_path = os.path.join(bundle_dir, "style.css")
app_path = os.path.join(bundle_dir, "app.js")
manifest_path = r"C:\Users\MY PC\Documents\recoup-production\manifest.json"

with open(index_path, "r", encoding="utf-8") as f:
    content = f.read()

# Extract style
style_match = re.search(r'<style>(.*?)</style>', content, re.DOTALL)
if style_match:
    style_content = style_match.group(1).strip() + "\n"
    with open(style_path, "w", encoding="utf-8") as f:
        f.write(style_content)
    content = content[:style_match.start()] + '<link rel="stylesheet" href="style.css" />' + content[style_match.end():]

# Extract main script
# The script we want to extract is the one starting with <script>\n    // -- State
script_match = re.search(r'<script>\s*// -- State(.*?)</script>', content, re.DOTALL)
if script_match:
    script_content = "// -- State" + script_match.group(1)
    with open(app_path, "w", encoding="utf-8") as f:
        f.write(script_content.strip() + "\n")
    content = content[:script_match.start()] + '<script src="app.js"></script>' + content[script_match.end():]

with open(index_path, "w", encoding="utf-8") as f:
    f.write(content)

with open(manifest_path, "r", encoding="utf-8") as f:
    manifest_content = f.read()

manifest_content = manifest_content.replace('"' + "'unsafe-inline'" + '"', '')
manifest_content = manifest_content.replace('\"style-src\": [\"\'self\'\", \"\'unsafe-inline\'\"]', '\"style-src\": [\"\'self\'\"]')
manifest_content = manifest_content.replace('\"script-src\": [\"\'self\'\", \"\'unsafe-inline\'\"]', '\"script-src\": [\"\'self\'\"]')

with open(manifest_path, "w", encoding="utf-8") as f:
    f.write(manifest_content)

print("Extraction and replacement complete.")
