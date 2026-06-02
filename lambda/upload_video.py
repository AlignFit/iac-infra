import json
import boto3
import base64
import uuid

s3 = boto3.client("s3")

RAW_BUCKET = "raw-video-bucket-511999689174"

def lambda_handler(event, context):

    try:

        if not event.get("body"):
            return {
                "statusCode": 400,
                "body": json.dumps({
                    "message": "Nenhum conteúdo recebido"
                })
            }

        file_content = base64.b64decode(event["body"])

        file_name = f"{uuid.uuid4()}.mp4"

        s3.put_object(
            Bucket=RAW_BUCKET,
            Key=file_name,
            Body=file_content,
            ContentType="video/mp4"
        )

        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Upload realizado com sucesso",
                "file": file_name
            })
        }

    except Exception as e:

        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": str(e)
            })
        }