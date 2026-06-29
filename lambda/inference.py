"""
Lambda de Inferência — AlignFit

Fluxo:
  1. Recebe evento SQS disparado pelo EventBridge (objeto criado no bucket Trusted)
  2. Faz download do CSV de keypoints
  3. Extrai as mesmas features usadas no treinamento (média, std, min, max)
  4. Carrega o modelo de classificação de exercício + encoder
  5. Identifica o exercício
  6. Carrega o modelo de execução específico do exercício
  7. Classifica a execução como correta ou errada
  8. Salva o resultado em JSON no bucket Results (individual + incremental)
"""

# =========================================================
# IMPORTS
# =========================================================

import os
import json
import tempfile
from datetime import datetime, timezone

import boto3
import joblib
import numpy as np
import pandas as pd

# =========================================================
# AWS — via variáveis de ambiente (definidas no CFN)
# =========================================================

s3 = boto3.client("s3")

TRUSTED_BUCKET = os.environ.get("TRUSTED_BUCKET")
MODELS_BUCKET  = os.environ.get("MODELS_BUCKET")
RESULTS_BUCKET = os.environ.get("RESULTS_BUCKET")

# =========================================================
# MAPEAMENTO: nome do exercício → arquivo do modelo
# =========================================================

EXERCISE_MODEL_KEYS = {
    "agachamento":      "modelo-de-classificacao-de-execucao-agachamento.pkl",
    "biceps":           "modelo-de-classificacao-de-execucao-biceps.pkl",
    "elevacao_lateral": "modelo-de-classificacao-de-execucao-elevacao-lateral.pkl",
    "desenvolvimento":  "modelo-de-classificacao-de-execucao-desenvolvimento.pkl",
}

# =========================================================
# UTILITÁRIOS
# =========================================================

def download_model(key: str):
    """Faz download de um modelo do bucket Models com cache em /tmp."""
    cache_path = f"/tmp/{key}"

    if os.path.exists(cache_path):
        print(f"INFO | Modelo em cache | /tmp/{key}")
        return joblib.load(cache_path)

    s3.download_file(MODELS_BUCKET, key, cache_path)
    print(f"INFO | Modelo baixado | s3://{MODELS_BUCKET}/{key}")
    return joblib.load(cache_path)


def extract_features(df: pd.DataFrame) -> np.ndarray:
    """
    Extrai as mesmas features usadas no treinamento:
    média, desvio padrão, mínimo e máximo dos keypoints por vídeo.
    """
    feature_cols = [
        col for col in df.columns
        if col.endswith("_x") or col.endswith("_y")
    ]

    # Agrupa por vídeo (cada CSV tem um único vídeo, mas mantemos a lógica robusta)
    grouped = df.groupby("video")[feature_cols]

    row = (
        grouped.mean().iloc[0].tolist()
        + grouped.std().fillna(0).iloc[0].tolist()
        + grouped.min().iloc[0].tolist()
        + grouped.max().iloc[0].tolist()
    )

    return np.array([row])


def save_result(file_id: str, result: dict):
    """Salva o resultado individual + append no histórico incremental."""

    # ─── Resultado individual (usado pelo polling do frontend) ───
    result_key = f"results/{file_id}.json"

    s3.put_object(
        Bucket=RESULTS_BUCKET,
        Key=result_key,
        Body=json.dumps(result, ensure_ascii=False),
        ContentType="application/json",
    )

    print(f"INFO | Resultado salvo | s3://{RESULTS_BUCKET}/{result_key}")

    # ─── Histórico incremental (usado pelo Grafana) ─────────────
    HISTORY_KEY = "results/historico.json"

    try:
        obj = s3.get_object(Bucket=RESULTS_BUCKET, Key=HISTORY_KEY)
        history = json.loads(obj["Body"].read().decode("utf-8"))
    except Exception:
        history = []

    history.append(result)

    s3.put_object(
        Bucket=RESULTS_BUCKET,
        Key=HISTORY_KEY,
        Body=json.dumps(history, ensure_ascii=False, indent=2),
        ContentType="application/json",
    )

    print(f"INFO | Histórico atualizado | {len(history)} registros")

# =========================================================
# HANDLER
# =========================================================

def lambda_handler(event, context):

    print("INFO | Evento de inferência recebido")

    for record in event["Records"]:

        body   = json.loads(record["body"])
        detail = body["detail"]

        bucket_name = detail["bucket"]["name"]
        object_key  = detail["object"]["key"]

        # O file_id é o UUID gerado no upload (nome do CSV sem extensão)
        csv_filename = os.path.basename(object_key)
        file_id      = csv_filename.replace(".mp4.csv", "").replace(".csv", "")

        print(f"INFO | Processando CSV | s3://{bucket_name}/{object_key}")
        print(f"INFO | File ID         | {file_id}")

        # -----------------------------------------------------
        # DOWNLOAD DO CSV
        # -----------------------------------------------------

        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            s3.download_file(bucket_name, object_key, tmp.name)
            df = pd.read_csv(tmp.name)

        if df.empty:
            print(f"ERRO | CSV vazio para file_id={file_id}")
            save_result(file_id, {
                "file_id":  file_id,
                "status":   "error",
                "mensagem": "Nenhum keypoint detectado no vídeo.",
            })
            continue

        # -----------------------------------------------------
        # EXTRAÇÃO DE FEATURES
        # -----------------------------------------------------

        X = extract_features(df)

        print(f"INFO | Features extraídas | shape={X.shape}")

        # -----------------------------------------------------
        # CLASSIFICAÇÃO DO EXERCÍCIO
        # -----------------------------------------------------

        exercise_model   = download_model("modelo-de-classificacao")
        label_encoder    = download_model("modelo-de-classificacao.pkl")

        exercise_encoded = exercise_model.predict(X)[0]
        exercise_name    = label_encoder.inverse_transform([exercise_encoded])[0]

        print(f"INFO | Exercício identificado | {exercise_name}")

        # -----------------------------------------------------
        # CLASSIFICAÇÃO DA EXECUÇÃO
        # -----------------------------------------------------

        if exercise_name not in EXERCISE_MODEL_KEYS:
            print(f"AVISO | Exercício '{exercise_name}' sem modelo de execução treinado")
            save_result(file_id, {
                "file_id":    file_id,
                "status":     "partial",
                "exercicio":  exercise_name,
                "execucao":   None,
                "mensagem":   f"Exercício identificado, mas modelo de execução para '{exercise_name}' ainda não está disponível.",
            })
            continue

        exec_model_key = EXERCISE_MODEL_KEYS[exercise_name]
        exec_model     = download_model(exec_model_key)

        execution_code = exec_model.predict(X)[0]
        execution      = "correta" if int(execution_code) == 0 else "errada"

        print(f"INFO | Execução classificada | {execution}")

        # -----------------------------------------------------
        # SALVAR RESULTADO
        # -----------------------------------------------------

        # Labels amigáveis para a mensagem ao usuário
        exercise_friendly = {
            "agachamento":      "Agachamento",
            "biceps":           "Rosca Direta",
            "elevacao_lateral": "Elevação Lateral",
            "desenvolvimento":  "Desenvolvimento de Ombro",
        }

        friendly_name = exercise_friendly.get(exercise_name, exercise_name)

        now = datetime.now(timezone.utc)

        result = {
            "file_id":   file_id,
            "status":    "success",
            "exercicio": exercise_name,
            "execucao":  execution,
            "mensagem":  (
                f"Exercício identificado: {friendly_name}. "
                f"Execução {'correta!' if execution == 'correta' else 'com erros. Revise a técnica do exercício.'}"
            ),
            "timestamp": now.isoformat(),
            "data":      now.strftime("%Y-%m-%d"),
            "hora":      now.strftime("%H:%M:%S"),
        }

        save_result(file_id, result)

    print("INFO | Inferência finalizada")
