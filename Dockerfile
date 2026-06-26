# =========================================================
# Imagem Docker para a Lambda video-processor
#
# Contém:
#   - Python 3.11 (base Lambda)
#   - ultralytics (YOLOv8 Pose)
#   - opencv-python-headless
#   - pandas
#   - boto3
#   - Modelo yolov8n-pose.pt
#   - Handler: user_dataset_generator.lambda_handler
# =========================================================

FROM public.ecr.aws/lambda/python:3.11

# ferramentas básicas
RUN pip install --upgrade pip setuptools wheel

RUN pip install --no-cache-dir --only-binary=:all: \
    numpy==1.26.4 \
    scipy==1.11.4

RUN pip install --no-cache-dir --no-deps \
    ultralytics==8.3.0

# ── Instalar bibliotecas Python ───────────────────────────────────────────────
RUN pip install --no-cache-dir \
    opencv-python-headless==4.10.0.84 \
    pandas==2.2.3 \
    boto3==1.35.0

# ── Copiar o handler da Lambda ────────────────────────────────────────────────
COPY iac-infra/lambda/user_dataset_generator.py ${LAMBDA_TASK_ROOT}/user_dataset_generator.py

# ── Copiar o modelo YOLO Pose ─────────────────────────────────────────────────
# O arquivo yolov8n-pose.pt deve estar em exercises-dataset/utils/
COPY exercises-dataset/utils/yolov8n-pose.pt ${LAMBDA_TASK_ROOT}/yolov8n-pose.pt

# ── Definir o handler ─────────────────────────────────────────────────────────
CMD ["user_dataset_generator.lambda_handler"]
