#!/usr/bin/env bash
# Generate all charts from benchmark data by executing Jupyter notebooks.
# Run from project root: ./scripts/generate_all_charts.sh
set -euo pipefail

NOTEBOOKS=(
    "notebooks/analysis_article_01.ipynb"
    "notebooks/analysis_article_02.ipynb"
    "notebooks/analysis_article_03.ipynb"
    "notebooks/analysis_article_04.ipynb"
    "notebooks/analysis_article_05.ipynb"
    "notebooks/analysis_article_06.ipynb"
    "notebooks/analysis_article_07.ipynb"
    "notebooks/analysis_article_08.ipynb"
    "notebooks/analysis_article_09.ipynb"
    "notebooks/cost_dashboard.ipynb"
)

echo "Generating all charts..."

for nb in "${NOTEBOOKS[@]}"; do
    if [[ -f "$nb" ]]; then
        echo "  Executing: $nb"
        uv run jupyter nbconvert --to notebook --execute "$nb" \
            --output "${nb%.ipynb}_executed.ipynb" \
            --ExecutePreprocessor.timeout=300 \
            --ExecutePreprocessor.kernel_name=python3 2>/dev/null || \
        echo "  Warning: $nb failed (may need live data — continuing)"
    else
        echo "  Skipping: $nb (not found)"
    fi
done

echo ""
echo "Charts directory:"
find results/charts -name "*.png" | sort | while read -r f; do
    echo "  $f"
done

echo ""
echo "Done. Open results/charts/ to view all charts."
