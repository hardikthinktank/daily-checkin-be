#!/bin/bash
set -e

echo "Installing dependencies..."
pip install -r requirements.txt

echo "Running database migrations..."
alembic upgrade head

echo "Seeding clinical rules..."
python -m scripts.seed_rules

echo "Seeding demo data..."
python -m scripts.seed_demo_data

echo "Seeding test-case fixtures..."
python -m scripts.seed_test_case_fixtures

echo "Build completed successfully!"