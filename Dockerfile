# =========================================================
# Imagem Docker para a Lambda video-processor
# =========================================================

FROM public.ecr.aws/lambda/python:3.11

# ── Atualizar pip
RUN pip install --upgrade pip setuptools wheel

# ── Instalar TODAS as dependências que o ultralytics precisa como wheels binários
# A ordem importa: numpy e scipy antes do torch, torch antes do ultralytics
RUN pip install --no-cache-dir --only-binary=:all: \
    --target "${LAMBDA_TASK_ROOT}" \
    "numpy==1.26.4" \
    "scipy==1.11.4"

# ── PyTorch CPU-only
RUN pip install --no-cache-dir --only-binary=:all: \
    --target "${LAMBDA_TASK_ROOT}" \
    "torch==2.2.2" \
    "torchvision==0.17.2" \
    --extra-index-url https://download.pytorch.org/whl/cpu

# ── Dependências do ultralytics que precisam de wheel binário
RUN pip install --no-cache-dir --only-binary=:all: \
    --target "${LAMBDA_TASK_ROOT}" \
    "matplotlib==3.8.4" \
    "seaborn==0.13.2" \
    "psutil>=5.9.8" \
    "py-cpuinfo>=9.0.0" \
    "tqdm>=4.64.0" \
    "requests>=2.23.0" \
    "pyyaml>=5.3.1" \
    "pillow>=7.1.2"

# ── ultralytics sem dependências (todas já instaladas acima)
RUN pip install --no-cache-dir --no-deps \
    --target "${LAMBDA_TASK_ROOT}" \
    "ultralytics==8.3.0"

# ── opencv headless, pandas, boto3
RUN pip install --no-cache-dir --only-binary=:all: \
    --target "${LAMBDA_TASK_ROOT}" \
    "opencv-python-headless==4.10.0.84" \
    "pandas==2.2.3" \
    "boto3==1.35.0"

# ── Copiar o handler da Lambda
COPY iac-infra/lambda/user_dataset_generator.py ${LAMBDA_TASK_ROOT}/user_dataset_generator.py

# ── Copiar o modelo YOLO Pose
COPY exercises-dataset/utils/yolov8n-pose.pt ${LAMBDA_TASK_ROOT}/yolov8n-pose.pt

# ── Definir o handler
CMD ["user_dataset_generator.lambda_handler"]
