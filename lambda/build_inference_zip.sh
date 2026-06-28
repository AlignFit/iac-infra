#!/bin/bash
# =========================================================
# Script para empacotar:
#   1. inference-layer.zip  → Lambda Layer com dependências
#   2. inference.zip        → Apenas o handler (inference.py)
#
# A Layer fica abaixo de 250MB descompactada usando versões
# mínimas e excluindo arquivos desnecessários (testes, docs).
#
# Rodar na instância de build (Amazon Linux 2023 / x86_64)
# =========================================================

set -e

# Garantir pré-requisitos
echo "==> Verificando pré-requisitos ..."
dnf install -y python3-pip zip 2>/dev/null || yum install -y python3-pip zip 2>/dev/null || true

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LAYER_DIR=$(mktemp -d)
OUTPUT_DIR="$SCRIPT_DIR/zip"
mkdir -p "$OUTPUT_DIR"

# =========================================================
# 1. LAYER — dependências em python/
# =========================================================

echo "==> Instalando dependências da Layer ..."

# Lambda Layers esperam a estrutura python/
LAYER_PYTHON="$LAYER_DIR/python"
mkdir -p "$LAYER_PYTHON"

pip3 install --no-cache-dir \
    --platform manylinux2014_x86_64 \
    --implementation cp \
    --python-version 3.11 \
    --only-binary=:all: \
    --target "$LAYER_PYTHON" \
    "joblib>=1.3.0" \
    "numpy==1.26.4" \
    "pandas==2.2.3" \
    "scikit-learn==1.5.2" \
    "xgboost>=2.0.0"

# Remover arquivos desnecessários para reduzir tamanho
echo "==> Limpando arquivos desnecessários da Layer ..."
find "$LAYER_PYTHON" -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true
find "$LAYER_PYTHON" -type d -name "test" -exec rm -rf {} + 2>/dev/null || true
find "$LAYER_PYTHON" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$LAYER_PYTHON" -name "*.dist-info" -type d -exec rm -rf {} + 2>/dev/null || true
find "$LAYER_PYTHON" -name "*.pyc" -delete 2>/dev/null || true

# Mostrar tamanho
LAYER_SIZE=$(du -sm "$LAYER_PYTHON" | cut -f1)
echo "    Tamanho da Layer: ${LAYER_SIZE}MB (limite: 250MB)"

if [ "$LAYER_SIZE" -ge 250 ]; then
    echo "ERRO: Layer excede 250MB! Considere usar imagem Docker."
    exit 1
fi

echo "==> Gerando inference-layer.zip ..."
cd "$LAYER_DIR"
zip -r9 "$OUTPUT_DIR/inference-layer.zip" python/

# =========================================================
# 2. HANDLER ZIP — apenas inference.py
# =========================================================

echo "==> Gerando inference.zip (apenas handler) ..."
cd "$SCRIPT_DIR"
zip -j "$OUTPUT_DIR/inference.zip" inference.py

# =========================================================
# RESULTADO
# =========================================================

echo ""
echo "==> Concluído!"
echo "    Layer: $OUTPUT_DIR/inference-layer.zip ($(du -h "$OUTPUT_DIR/inference-layer.zip" | cut -f1))"
echo "    Handler: $OUTPUT_DIR/inference.zip ($(du -h "$OUTPUT_DIR/inference.zip" | cut -f1))"
echo ""
echo "==> Próximos passos:"
echo "    1. Upload da layer:"
echo "       aws s3 cp $OUTPUT_DIR/inference-layer.zip s3://<SETUP_BUCKET>/inference-layer.zip"
echo ""
echo "    2. Publicar a Layer:"
echo "       aws lambda publish-layer-version \\"
echo "         --layer-name inference-deps \\"
echo "         --content S3Bucket=<SETUP_BUCKET>,S3Key=inference-layer.zip \\"
echo "         --compatible-runtimes python3.11"
echo ""
echo "    3. Upload do handler:"
echo "       aws s3 cp $OUTPUT_DIR/inference.zip s3://<SETUP_BUCKET>/inference.zip"
echo ""
echo "    4. Atualizar a Lambda:"
echo "       aws lambda update-function-code --function-name inference --s3-bucket <SETUP_BUCKET> --s3-key inference.zip"
echo "       aws lambda update-function-configuration --function-name inference --layers <LAYER_ARN>"

# Limpeza
rm -rf "$LAYER_DIR"
