.PHONY: docs-svg-samples

## docs-svg-samples — regenerate pure-vector SVG previews for all seed templates
## Output: docs/site/operations/templates/svg-samples/{template-id}.svg
docs-svg-samples:
	cd backend && uv run python scripts/generate_template_svgs.py
