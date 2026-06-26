"""
Lambda de Consulta de Resultado — AlignFit

Endpoint: GET /result/{file_id}

O frontend faz polling neste endpoint após o upload.
Retorna o JSON de resultado salvo pela Lambda de inferência,
ou 202 (Accepted) enquanto o processamento ainda está em andamento.
"""

# =========================================================
# IMPORTS
# =========================================================

import json
import os

import boto3
from botocore.exceptions import ClientError

# =========================================================
# AWS
# =========================================================

s3 = boto3.client("s3")

RESULTS_BUCKET = os.environ.get("RESULTS_BUCKET")

# =========================================================
# CORS HEADERS
# =========================================================

CORS_HEADERS = {
    "Access-Control-Allow-Origin":  "*",
    "Access-Control-Allow-Methods": "GET,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}

# =========================================================
# HANDLER
# =========================================================

def lambda_handler(event, context):

    # -----------------------------------------------------
    # PRE-FLIGHT OPTIONS (CORS)
    # -----------------------------------------------------

    if event.get("httpMethod") == "OPTIONS":
        return {"statusCode": 200, "headers": CORS_HEADERS, "body": ""}

    # -----------------------------------------------------
    # EXTRAIR FILE ID
    # -----------------------------------------------------

    path_params = event.get("pathParameters") or {}
    file_id     = path_params.get("file_id")

    if not file_id:
        return {
            "statusCode": 400,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": "file_id não informado"}),
        }

    # -----------------------------------------------------
    # BUSCAR RESULTADO NO S3
    # -----------------------------------------------------

    result_key = f"results/{file_id}.json"

    try:
        response = s3.get_object(Bucket=RESULTS_BUCKET, Key=result_key)
        result   = json.loads(response["Body"].read().decode("utf-8"))

        return {
            "statusCode": 200,
            "headers": CORS_HEADERS,
            "body": json.dumps(result, ensure_ascii=False),
        }

    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            # Resultado ainda não disponível — processamento em andamento
            return {
                "statusCode": 202,
                "headers": CORS_HEADERS,
                "body": json.dumps({
                    "status":   "processing",
                    "mensagem": "Análise em andamento. Tente novamente em alguns segundos.",
                }),
            }

        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": str(e)}),
        }
