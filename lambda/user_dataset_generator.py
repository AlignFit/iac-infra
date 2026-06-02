# =========================================================
# IMPORTS
# =========================================================

from ultralytics import YOLO

import os
import cv2
import json
import boto3
import pandas as pd

# =========================================================
# AWS
# =========================================================

s3 = boto3.client("s3")

RAW_BUCKET = "raw-video-bucket-511999689174"
TRUSTED_BUCKET = "trusted-video-bucket-511999689174"

# =========================================================
# CONFIGURAÇÕES
# =========================================================

# Modelo YOLO Pose
MODEL_PATH = "yolov8n-pose.pt"

# Processar 1 frame a cada N frames
FRAME_SKIP = 5

# =========================================================
# KEYPOINTS
# =========================================================

KEYPOINT_NAMES = {
    0: "nariz",
    1: "olho_esquerdo",
    2: "olho_direito",
    3: "orelha_esquerda",
    4: "orelha_direita",
    5: "ombro_esquerdo",
    6: "ombro_direito",
    7: "cotovelo_esquerdo",
    8: "cotovelo_direito",
    9: "pulso_esquerdo",
    10: "pulso_direito",
    11: "quadril_esquerdo",
    12: "quadril_direito",
    13: "joelho_esquerdo",
    14: "joelho_direito",
    15: "tornozelo_esquerdo",
    16: "tornozelo_direito"
}

# =========================================================
# CARREGAR MODELO
# =========================================================

print("INFO | Carregando YOLO Pose")

model = YOLO(MODEL_PATH)

print("INFO | Modelo carregado")

# =========================================================
# PROCESSAMENTO
# =========================================================

def process_video(video_path):

    video_name = os.path.basename(video_path)

    output_csv = f"/tmp/{video_name}.csv"

    if not os.path.exists(video_path):

        print(f"ERRO | Video nao encontrado | {video_path}")

        raise Exception("Video nao encontrado")

    cap = cv2.VideoCapture(video_path)

    all_data = []

    frame_id = 0

    print(f"INFO | Processando video | {video_name}")

    # =====================================================
    # PROCESSAR FRAMES
    # =====================================================

    while cap.isOpened():

        success, frame = cap.read()

        if not success:
            break

        # =================================================
        # PULAR FRAMES
        # =================================================

        if frame_id % FRAME_SKIP != 0:

            frame_id += 1
            continue

        height, width = frame.shape[:2]

        # =================================================
        # INFERÊNCIA YOLO
        # =================================================

        results = model(frame, verbose=False)

        result = results[0]

        # =================================================
        # VERIFICAR KEYPOINTS
        # =================================================

        if result.keypoints is not None and len(result.keypoints.xy) > 0:

            keypoints = result.keypoints.xy.cpu().numpy()

            # =============================================
            # PERCORRER PESSOAS
            # =============================================

            for person_id, person_keypoints in enumerate(keypoints):

                row = {

                    "video": video_name,
                    "frame": frame_id,
                    "person_id": person_id
                }

                # =========================================
                # KEYPOINTS NORMALIZADOS
                # =========================================

                for kp_id, (x, y) in enumerate(person_keypoints):

                    body_part = KEYPOINT_NAMES[kp_id]

                    x_norm = float(x / width)
                    y_norm = float(y / height)

                    row[f"{body_part}_x"] = x_norm
                    row[f"{body_part}_y"] = y_norm

                # =========================================
                # ADICIONAR AO DATASET
                # =========================================

                all_data.append(row)

        frame_id += 1

    # =====================================================
    # FINALIZAR VÍDEO
    # =====================================================

    cap.release()

    # =====================================================
    # CRIAR DATAFRAME
    # =====================================================

    df = pd.DataFrame(all_data)

    # =====================================================
    # SALVAR CSV
    # =====================================================

    df.to_csv(
        output_csv,
        index=False
    )

    # =====================================================
    # ENVIAR CSV PARA TRUSTED
    # =====================================================

    trusted_key = f"datasets/{video_name}.csv"

    s3.upload_file(
        output_csv,
        TRUSTED_BUCKET,
        trusted_key
    )

    # =====================================================
    # FINALIZAÇÃO
    # =====================================================

    print(f"INFO | Video processado | {video_name}")
    print(f"INFO | Registros gerados | {len(df)}")
    print(f"INFO | CSV enviado | s3://{TRUSTED_BUCKET}/{trusted_key}")

# =========================================================
# HANDLER
# =========================================================

def lambda_handler(event, context):

    print("INFO | Evento recebido")

    for record in event["Records"]:

        body = json.loads(record["body"])

        detail = body["detail"]

        bucket_name = detail["bucket"]["name"]

        object_key = detail["object"]["key"]

        video_name = os.path.basename(object_key)

        local_video = f"/tmp/{video_name}"

        print(f"INFO | Download video | s3://{bucket_name}/{object_key}")

        s3.download_file(
            bucket_name,
            object_key,
            local_video
        )

        process_video(local_video)

    print("INFO | Processamento finalizado")