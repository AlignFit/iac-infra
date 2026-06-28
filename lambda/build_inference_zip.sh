#!/bin/bash
# =========================================================
# Script para empacotar inference.zip com dependências
# Rodar na instância de build (Amazon Linux / x86_64)
# =========================================================

set -e

WORK_DIR=$(mktemp -d)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTPUT="$SCRIPT_DIR/zip/inference.zip"

echo "==> Instalando dependências em $WORK_DIR ..."

pip install --no-cache-dir \
    --platform manylinux2014_x86_64 \
    --implementation cp \
    --python-version 3.11 \
    --only-binary=:all: \
    --target "$WORK_DIR" \
    joblib \
    numpy==1.26.4 \
    pandas==2.2.3 \
    scikit-learn==1.5.2

echo "==> Copiando handler ..."
cp "$SCRIPT_DIR/inference.py" "$WORK_DIR/"

echo "==> Gerando ZIP ..."
mkdir -p "$SCRIPT_DIR/zip"
cd "$WORK_DIR"
zip -r9 "$OUTPUT" .

echo "==> Pronto! ZIP gerado em: $OUTPUT"
echo "    Tamanho: $(du -h "$OUTPUT" | cut -f1)"

# Limpeza
rm -rf "$WORK_DIR"
