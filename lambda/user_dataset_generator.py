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
# AWS — via variáveis de ambiente (definidas no CFN)
# =========================================================

s3 = boto3.client("s3")

RAW_BUCKET     = os.environ.get("RAW_BUCKET")
TRUSTED_BUCKET = os.environ.get("TRUSTED_BUCKET")

# =========================================================
# CONFIGURAÇÕES
# =========================================================

# Modelo YOLO Pose (deve estar na raiz da imagem Docker)
MODEL_PATH = "/var/task/yolov8n-pose.pt"

# Processar 1 frame a cada N frames
FRAME_SKIP = 5

# Confiança mínima para aceitar um keypoint
MIN_KEYPOINT_CONF = 0.5

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
# CARREGAR MODELO — no cold start da Lambda
# =========================================================

print("INFO | Carregando YOLO Pose")

model = YOLO(MODEL_PATH)

print("INFO | Modelo carregado")

# =========================================================
# SELECIONAR PESSOA PRINCIPAL
# Retorna o índice da pessoa com maior área de bounding box
# (a mais próxima da câmera / mais central no frame)
# =========================================================

def select_main_person(result):
    if result.boxes is None or len(result.boxes.xyxy) == 0:
        return 0

    areas = []

    for box in result.boxes.xyxy.cpu().numpy():
        x1, y1, x2, y2 = box[:4]
        areas.append((x2 - x1) * (y2 - y1))

    return int(areas.index(max(areas)))

# =========================================================
# PROCESSAMENTO
# =========================================================

def process_video(video_path):

    video_name = os.path.basename(video_path)

    output_csv = f"/tmp/{video_name}.csv"

    if not os.path.exists(video_path):
        print(f"ERRO | Video nao encontrado | {video_path}")
        raise FileNotFoundError(f"Video nao encontrado: {video_path}")

    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        raise RuntimeError(f"Nao foi possivel abrir o video: {video_path}")

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

        if result.keypoints is None or len(result.keypoints.xy) == 0:
            frame_id += 1
            continue

        keypoints      = result.keypoints.xy.cpu().numpy()
        keypoints_conf = result.keypoints.conf.cpu().numpy() \
            if result.keypoints.conf is not None else None

        # =================================================
        # SELECIONAR APENAS A PESSOA PRINCIPAL
        # =================================================

        main_idx = select_main_person(result)

        if main_idx >= len(keypoints):
            frame_id += 1
            continue

        person_keypoints = keypoints[main_idx]
        person_conf      = keypoints_conf[main_idx] \
            if keypoints_conf is not None else None

        row = {
            "video":     video_name,
            "frame":     frame_id,
            "person_id": 0,
        }

        # =================================================
        # KEYPOINTS NORMALIZADOS (com filtro de confiança)
        # =================================================

        for kp_id, (x, y) in enumerate(person_keypoints):

            body_part = KEYPOINT_NAMES[kp_id]

            conf = float(person_conf[kp_id]) \
                if person_conf is not None else 1.0

            if conf >= MIN_KEYPOINT_CONF:
                row[f"{body_part}_x"] = float(x / width)
                row[f"{body_part}_y"] = float(y / height)
            else:
                # Keypoint com baixa confiança → marcado como ausente
                row[f"{body_part}_x"] = None
                row[f"{body_part}_y"] = None

        all_data.append(row)

        frame_id += 1

    # =====================================================
    # FINALIZAR VÍDEO
    # =====================================================

    cap.release()

    # =====================================================
    # VALIDAR DADOS
    # =====================================================

    if not all_data:
        raise ValueError(
            f"Nenhum keypoint detectado no video: {video_name}. "
            "Verifique se o corpo está visível no vídeo."
        )

    # =====================================================
    # CRIAR DATAFRAME
    # =====================================================

    df = pd.DataFrame(all_data)

    # =====================================================
    # SALVAR CSV
    # =====================================================

    df.to_csv(output_csv, index=False)

    # =====================================================
    # ENVIAR CSV PARA TRUSTED
    # =====================================================

    trusted_key = f"datasets/{video_name}.csv"

    s3.upload_file(output_csv, TRUSTED_BUCKET, trusted_key)

    # =====================================================
    # ATUALIZAR CSV MESTRE INCREMENTAL
    # =====================================================

    # Salvo em "incremental/" para NÃO disparar a regra EventBridge
    # que monitora "datasets/" (essa regra aciona a Lambda de inferência)
    MASTER_CSV_KEY = "incremental/master-dataset.csv"

    try:
        master_tmp = f"/tmp/master-dataset.csv"
        s3.download_file(TRUSTED_BUCKET, MASTER_CSV_KEY, master_tmp)
        master_df = pd.read_csv(master_tmp)
        master_df = pd.concat([master_df, df], ignore_index=True)
        print(f"INFO | CSV mestre atualizado | +{len(df)} linhas → total {len(master_df)}")
    except Exception:
        # Primeira execução — CSV mestre não existe ainda, usar df atual
        master_df = df
        print(f"INFO | CSV mestre criado | {len(master_df)} linhas")

    master_csv_path = f"/tmp/master-dataset-out.csv"
    master_df.to_csv(master_csv_path, index=False)
    s3.upload_file(master_csv_path, TRUSTED_BUCKET, MASTER_CSV_KEY)

    try:
        os.remove(master_tmp)
    except (OSError, UnboundLocalError):
        pass
    try:
        os.remove(master_csv_path)
    except OSError:
        pass

    # =====================================================
    # CLEANUP TEMPORÁRIO
    # =====================================================

    try:
        os.remove(video_path)
        os.remove(output_csv)
    except OSError:
        pass

    # =====================================================
    # FINALIZAÇÃO
    # =====================================================

    print(f"INFO | Video processado       | {video_name}")
    print(f"INFO | Frames com keypoints   | {len(df)}")
    print(f"INFO | CSV enviado            | s3://{TRUSTED_BUCKET}/{trusted_key}")

    return trusted_key

# =========================================================
# HANDLER
# =========================================================

def lambda_handler(event, context):

    print("INFO | Evento recebido")

    for record in event["Records"]:

        body = json.loads(record["body"])

        detail = body["detail"]

        bucket_name = detail["bucket"]["name"]
        object_key  = detail["object"]["key"]

        video_name  = os.path.basename(object_key)
        local_video = f"/tmp/{video_name}"

        print(f"INFO | Download video | s3://{bucket_name}/{object_key}")

        s3.download_file(bucket_name, object_key, local_video)

        try:
            process_video(local_video)
        except Exception as e:
            print(f"ERRO | Falha ao processar {video_name} | {e}")
            raise  # Re-raise para acionar a DLQ após 3 tentativas

    print("INFO | Processamento finalizado")
