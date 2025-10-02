#!/bin/bash

# Cleaning script for WhirlTube project
echo "Cleaning WhirlTube project directory..."

# Remove cache directories
echo "Removing cache directories..."
rm -rf .mypy_cache/
rm -rf .pytest_cache/
rm -rf .ruff_cache/
find . -type d -name "__pycache__" -exec rm -rf {} +
find . -type f -name "*.pyc" -delete

# Remove build artifacts
echo "Removing build artifacts..."
rm -rf build/
rm -rf dist/
rm -rf whirltube/*.egg-info/ 2>/dev/null || true
rm -rf whirltube-git/*.egg-info/ 2>/dev/null || true

# Remove virtual environment (optional - you can recreate it with python -m venv .venv)
echo "Do you want to remove the virtual environment? (y/n)"
read -r response
if [[ "$response" =~ ^[Yy]$ ]]; then
    rm -rf .venv/
fi

echo "Project directory cleaned!"