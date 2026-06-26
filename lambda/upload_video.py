import json
import boto3
import uuid
import os

s3 = boto3.client("s3")

# =========================================================
# CONFIGURAÇÃO — via variável de ambiente (definida no CFN)
# =========================================================

RAW_BUCKET = os.environ.get("RAW_BUCKET")

# =========================================================
# CORS HEADERS
# =========================================================

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
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
        return {
            "statusCode": 200,
            "headers": CORS_HEADERS,
            "body": ""
        }

    # -----------------------------------------------------
    # VALIDAÇÃO DO BUCKET
    # -----------------------------------------------------

    if not RAW_BUCKET:
        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": "RAW_BUCKET não configurado"})
        }

    try:

        # -------------------------------------------------
        # GERAR FILE ID E PRESIGNED URL
        # -------------------------------------------------

        file_id = str(uuid.uuid4())

        object_key = f"videos/{file_id}.mp4"

        presigned_url = s3.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": RAW_BUCKET,
                "Key": object_key,
                "ContentType": "video/mp4",
            },
            ExpiresIn=300,  # 5 minutos
        )

        return {
            "statusCode": 200,
            "headers": CORS_HEADERS,
            "body": json.dumps({
                "upload_url": presigned_url,
                "file_id": file_id,
                "object_key": object_key,
            })
        }

    except Exception as e:

        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": str(e)})
        }
