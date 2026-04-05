#!/bin/bash
set -e

echo "Bundling BLAIQ artifact..."

if [ ! -f "package.json" ]; then
  echo "No package.json found"
  exit 1
fi

# Install if needed
if [ ! -d "node_modules" ]; then
  echo "Installing dependencies..."
  pnpm install --frozen-lockfile 2>/dev/null || pnpm install
fi

# Install bundling tools if missing
pnpm add -D parcel @parcel/config-default html-inline 2>/dev/null || true

# Create parcel config
cat > .parcelrc << 'EOF'
{
  "extends": "@parcel/config-default"
}
EOF

# Clean and build
rm -rf dist bundle.html
pnpm exec parcel build index.html --dist-dir dist --no-source-maps 2>&1

# Inline into single file
pnpm exec html-inline dist/index.html > bundle.html

echo "bundle.html created ($(du -h bundle.html | cut -f1))"
