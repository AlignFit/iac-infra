# Infraestrutura como Código (IaC) — AlignFit

Gerenciado via AWS CloudFormation. Siga a ordem abaixo para um deploy completo.

---

## Pré-requisitos

- AWS CLI configurada com credenciais válidas
- Conta AWS Academy com `LabRole` disponível
- Acesso SSM configurado (para conexão na EC2 de build)
- Node.js 20+ (apenas se for buildar o frontend localmente)

---

## Ordem de deploy das stacks

```
1. setup.yml       → cria o bucket de artefatos (ZIPs, layers)
2. storage.yml     → cria todos os buckets S3 (Raw, Client, Model, Result)
3. build.yml       → EC2 temporária para build Docker + Lambda Layer (opcional)
4. processing.yml  → SQS, EventBridge, Lambda processadora (YOLO) e Lambda de inferência
5. api.yml         → API Gateway + Lambda upload + Lambda get-result
6. frontend.yml    → EC2 com nginx servindo o build React
7. training.yml    → EC2 com Jupyter Notebook para treinamento de modelos (opcional)
```

---

## 1. Stack Setup

Cria o bucket onde ficam os ZIPs das Lambdas e a Lambda Layer.

```powershell
aws cloudformation deploy `
  --template-file "setup.yml" `
  --stack-name "SetupAlignFitStack" `
  --capabilities "CAPABILITY_NAMED_IAM"
```

---

## 2. Stack Storage

Cria os 4 buckets S3 com EventBridge habilitado e CORS no Raw.

```powershell
aws cloudformation deploy `
  --template-file "storage.yml" `
  --stack-name "StorageAlignFitStack" `
  --capabilities "CAPABILITY_NAMED_IAM"
```

### Upload dos modelos treinados para o bucket Models

```powershell
aws s3 cp ../exercises-dataset/models/ s3://model-s3-{ID_DA_CONTA}/ --recursive
```

### Upload do CSV mestre inicial (base para dataset incremental)

O CSV mestre (`master-dataset.csv`) cresce automaticamente a cada vídeo processado.
Para inicializá-lo com os dados de treino já existentes:

```powershell
aws s3 cp ../exercises-dataset/datasets/raw-dataset.csv s3://result-s3-{ID_DA_CONTA}/master-dataset.csv
```

> **Nota:** Após o upload inicial, cada execução da Lambda processadora (YOLO)
> adiciona automaticamente as novas linhas ao `master-dataset.csv` no bucket Result.
> Baixe no Jupyter para re-treinamento dos modelos.

---

## 3. Subir os ZIPs das Lambdas simples (upload + get_result)

Essas duas Lambdas usam apenas `boto3` (já incluso no runtime Python do Lambda) e não precisam de dependências extras.

```powershell
# Empacotar (rode dentro da pasta iac-infra)
Compress-Archive -Path lambda\upload_video.py   -DestinationPath lambda\zip\upload_video.zip   -Force
Compress-Archive -Path lambda\get_result.py     -DestinationPath lambda\zip\get_result.zip     -Force

# Enviar para o S3
aws s3 cp ./lambda/zip/upload_video.zip s3://setup-bucket-{ID_DA_CONTA}/upload_video.zip
aws s3 cp ./lambda/zip/get_result.zip s3://setup-bucket-{ID_DA_CONTA}/get_result.zip
```

---

## 4. Build da Lambda de Inferência (com dependências)

> **⚠️ IMPORTANTE:** A Lambda `inference` usa `joblib`, `numpy`, `pandas`, `scikit-learn` e `xgboost`.
> Essas bibliotecas não vêm no runtime do Lambda e juntas excedem o limite de 250MB de ZIP.
> A solução é usar uma **Lambda Layer** para as dependências.

### Opção recomendada — Build na EC2 (Amazon Linux 2023)

#### 4.1 Subir a instância de build

```powershell
aws cloudformation deploy `
  --template-file "build.yml" `
  --stack-name "BuildAlignFitStack" `
  --capabilities "CAPABILITY_NAMED_IAM"
```

#### 4.2 Conectar na instância

```powershell
# Obter Instance ID
aws cloudformation describe-stacks `
  --stack-name "BuildAlignFitStack" `
  --query "Stacks[0].Outputs[?OutputKey=='InstanceId'].OutputValue" `
  --output text

# Conectar via SSM
aws ssm start-session --target {INSTANCE_ID}
```

#### 4.3 Dentro da instância — clonar e buildar

```bash
# Aguardar o UserData terminar
cat ~/ready.txt   # deve mostrar "BUILD_INSTANCE_READY"

# Clonar o repositório
cd ~
git clone https://github.com/{SEU_USUARIO}/{SEU_REPO}.git AlingFit
cd AlingFit/iac-infra/lambda
```

#### 4.4 Gerar a Layer + handler ZIP

```bash
chmod +x build_inference_zip.sh
sudo ./build_inference_zip.sh
```

O script gera:
- `zip/inference-layer.zip` — Layer com joblib, numpy, pandas, scikit-learn, xgboost (~70MB comprimido)
- `zip/inference.zip` — Apenas o `inference.py` (~3KB)

#### 4.5 Upload e publicação da Layer

```bash
# Upload da Layer
aws s3 cp zip/inference-layer.zip s3://setup-bucket-$(aws sts get-caller-identity --query Account --output text)/inference-layer.zip

# Publicar a Layer
aws lambda publish-layer-version \
  --layer-name inference-deps \
  --content S3Bucket=setup-bucket-$(aws sts get-caller-identity --query Account --output text),S3Key=inference-layer.zip \
  --compatible-runtimes python3.11
```

**Anote o `LayerVersionArn`** retornado (ex: `arn:aws:lambda:us-east-1:936463224880:layer:inference-deps:1`).

#### 4.6 Upload do handler

```bash
aws s3 cp zip/inference.zip s3://setup-bucket-$(aws sts get-caller-identity --query Account --output text)/inference.zip
```

#### 4.7 (Mesmo acesso) Build e push da imagem Docker para o ECR

Aproveite a mesma EC2 para buildar a imagem Docker da Lambda processadora (YOLO):

```bash
cd ~/AlingFit

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION=us-east-1
REPO=align-fit-processor

# Criar repositório no ECR (apenas na primeira vez)
aws ecr create-repository --repository-name $REPO --region $REGION 2>/dev/null || true

# Autenticar Docker no ECR
aws ecr get-login-password --region $REGION \
  | sudo docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com

# Build da imagem (rodar na raiz do workspace)
docker build -f iac-infra/Dockerfile -t $REPO .

# Tag e push
docker tag $REPO:latest $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$REPO:latest
docker push $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$REPO:latest

echo "✅ Push concluído: $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$REPO:latest"
```

#### 4.8 Terminar a instância de build (evitar custos)

```powershell
aws cloudformation delete-stack --stack-name "BuildAlignFitStack"
```

---

## 5. Stack Processing

Deploya as duas Lambdas de processamento: YOLO (Docker) e Inferência (ZIP + Layer).

```powershell
aws cloudformation deploy `
  --template-file "processing.yml" `
  --stack-name "ProcessingAlignFitStack" `
  --parameter-overrides `
    "EcrImageUri={ID_DA_CONTA}.dkr.ecr.us-east-1.amazonaws.com/align-fit-processor:latest" `
    "SetupBucket=setup-bucket-{ID_DA_CONTA}" `
    "InferenceLayerArn=arn:aws:lambda:us-east-1:{ID_DA_CONTA}:layer:inference-deps:1" `
  --capabilities "CAPABILITY_NAMED_IAM"
```

### Atualização manual da Lambda inference (sem redeploy do stack)

Se já tiver feito deploy do stack antes e só precisa atualizar o código/layer:

```bash
# Atualizar código
aws lambda update-function-code \
  --function-name inference \
  --s3-bucket setup-bucket-{ID_DA_CONTA} \
  --s3-key inference.zip

# Anexar a Layer (aguardar o update-function-code finalizar)
aws lambda update-function-configuration \
  --function-name inference \
  --layers "arn:aws:lambda:us-east-1:{ID_DA_CONTA}:layer:inference-deps:1"
```

---

## 6. Stack API

```powershell
aws cloudformation deploy `
  --template-file "api.yml" `
  --stack-name "ApiAlignFitStack" `
  --parameter-overrides "SetupBucket=setup-bucket-{ID_DA_CONTA}" `
  --capabilities "CAPABILITY_NAMED_IAM"
```

Após o deploy, anote as URLs dos outputs:

```powershell
aws cloudformation describe-stacks `
  --stack-name "ApiAlignFitStack" `
  --query "Stacks[0].Outputs" `
  --output table
```

Exemplo de outputs:
- `UploadApiUrl`: `https://xxxxxx.execute-api.us-east-1.amazonaws.com/prod/upload`
- `ResultApiUrl`: `https://xxxxxx.execute-api.us-east-1.amazonaws.com/prod/result/{file_id}`

> **⚠️ ATENÇÃO:** A `ResultApiUrl` no output inclui `/{file_id}` como placeholder visual.
> No `.env` do frontend, use **sem** o `/{file_id}` no final:
> ```
> VITE_RESULT_API_URL=https://xxxxxx.execute-api.us-east-1.amazonaws.com/prod/result
> ```
> O frontend concatena o `file_id` programaticamente no código.

---

## 7. Stack Frontend (EC2)

Substitua as URLs pelos outputs reais da stack API.

```powershell
aws cloudformation deploy `
  --template-file "frontend.yml" `
  --stack-name "FrontendAlignFitStack" `
  --parameter-overrides `
    "UploadApiUrl=https://xxxxxx.execute-api.us-east-1.amazonaws.com/prod/upload" `
    "ResultApiUrl=https://xxxxxx.execute-api.us-east-1.amazonaws.com/prod/result" `
    "GitRepoUrl=https://github.com/AlignFit/align-fit-web.git" `
  --capabilities "CAPABILITY_NAMED_IAM"
```

> **Nota:** O parâmetro `GitRepoUrl` define a URL do repositório do frontend.
> Se não informado, usa o default `https://github.com/AlignFit/align-fit-web.git`.

Obter a URL pública do frontend:

```powershell
aws cloudformation describe-stacks `
  --stack-name "FrontendAlignFitStack" `
  --query "Stacks[0].Outputs[?OutputKey=='FrontendUrl'].OutputValue" `
  --output text
```

---

## Redeploy do Frontend

O UserData da EC2 **só executa uma vez**, na criação da instância.

### Opção A — SSH na EC2 (mais rápido)

```powershell
$ip = aws cloudformation describe-stacks `
  --stack-name "FrontendAlignFitStack" `
  --query "Stacks[0].Outputs[?OutputKey=='FrontendPublicIp'].OutputValue" `
  --output text

ssh ec2-user@$ip
```

Dentro da EC2:

```bash
cd /opt/align-fit-web
git pull

# Recriar o .env (caso as URLs tenham mudado)
cat > .env <<EOF
VITE_UPLOAD_API_URL=https://xxxxxx.execute-api.us-east-1.amazonaws.com/prod/upload
VITE_RESULT_API_URL=https://xxxxxx.execute-api.us-east-1.amazonaws.com/prod/result
EOF

npm ci
npm run build
cp -r dist/* /usr/share/nginx/html/
```

### Opção B — Forçar recriação via CloudFormation

Incremente o parâmetro `DeployVersion`:

```powershell
aws cloudformation deploy `
  --template-file "frontend.yml" `
  --stack-name "FrontendAlignFitStack" `
  --parameter-overrides `
    "UploadApiUrl=https://xxxxxx.execute-api.us-east-1.amazonaws.com/prod/upload" `
    "ResultApiUrl=https://xxxxxx.execute-api.us-east-1.amazonaws.com/prod/result" `
    "DeployVersion=2" `
  --capabilities "CAPABILITY_NAMED_IAM"
```

> O IP público muda a cada recriação — obtenha o novo IP com o describe acima.

---

## 8. EC2 de Treinamento (Jupyter Notebook + Grafana)

Instância EC2 com Jupyter Notebook e Grafana pré-configurados.

- **Jupyter Notebook** — treinar novos modelos de ML e fazer upload direto para o bucket Models
- **Grafana** — leitura do JSON incremental de resultados para dashboards e métricas

### Deploy

```powershell
aws cloudformation deploy `
  --template-file "training.yml" `
  --stack-name "TrainingAlignFitStack" `
  --parameter-overrides `
    "GitRepoUrl=https://github.com/AlignFit/exercises-dataset.git" `
    "JupyterPassword=alignfit2026" `
  --capabilities "CAPABILITY_NAMED_IAM"
```

### Acessar o Jupyter

Aguarde 3-5 minutos após o deploy e pegue a URL:

```powershell
aws cloudformation describe-stacks `
  --stack-name "TrainingAlignFitStack" `
  --query "Stacks[0].Outputs" `
  --output table
```

Acesse `http://<IP_PUBLICO>:8888` com a senha definida no deploy (padrão: `alignfit2026`).

O Jupyter abre direto na pasta `exercises-dataset/` com acesso a:
- Scripts de treino (`adm/`, `buildClassifierExerciseModel/`)
- Datasets (`datasets/`)
- Modelos existentes (`models/`)
- Vídeos para processamento (`videos/`)

### Acessar o Grafana

Acesse `http://<IP_PUBLICO>:3000` com as credenciais padrão (`admin` / `admin`).

O plugin **Infinity** já vem instalado. Para configurar o datasource:

1. Vá em **Connections → Data sources → Add data source → Infinity**
2. Configure uma query do tipo **JSON** apontando para:
   - URL: A presigned URL do S3, ou use o AWS SDK via backend
   - Alternativa simples: copie o `historico.json` para a EC2 periodicamente:
     ```bash
     aws s3 cp s3://result-s3-{ID_DA_CONTA}/results/historico.json /tmp/historico.json
     ```
   - E aponte o Infinity para `file:///tmp/historico.json`
3. Crie dashboards com as métricas:
   - Total de análises realizadas
   - Exercícios mais enviados
   - Taxa de execuções corretas vs erradas
   - Evolução ao longo do tempo (campo `timestamp`)

### Ambiente pré-instalado

| Biblioteca | Versão |
|---|---|
| Python | 3.11 |
| scikit-learn | 1.5.2 |
| xgboost | >=2.0.0 |
| numpy | 1.26.4 |
| pandas | 2.2.3 |
| ultralytics (YOLO) | 8.3.0 |
| opencv-python-headless | 4.10.0.84 |
| joblib | latest |
| matplotlib | latest |
| seaborn | latest |
| boto3 | latest |
| Grafana | 11.0.0 |

### Upload dos modelos treinados para o S3

No terminal do Jupyter ou via SSH na instância:

```bash
aws s3 cp models/ s3://model-s3-{ID_DA_CONTA}/ --recursive
```

### Terminar a instância (evitar custos)

```powershell
aws cloudformation delete-stack --stack-name "TrainingAlignFitStack"
```

> **⚠️ IMPORTANTE:** A instância não é gratuita. Delete a stack assim que terminar o treinamento.

---

## Dados Incrementais

O sistema mantém dois arquivos incrementais que crescem a cada execução:

### JSON Incremental — `results/historico.json`

**Bucket:** `result-s3-{ID_DA_CONTA}`
**Atualizado por:** Lambda `inference`

Cada vez que um vídeo é analisado, o resultado (exercício, execução, timestamp) é adicionado
a esse arquivo. Estrutura:

```json
[
  {
    "file_id": "uuid",
    "status": "success",
    "exercicio": "desenvolvimento",
    "execucao": "correta",
    "mensagem": "...",
    "timestamp": "2026-06-28T15:30:00+00:00",
    "data": "2026-06-28",
    "hora": "15:30:00"
  },
  ...
]
```

Usado pelo **Grafana** para dashboards e métricas do sistema.

### CSV Incremental — `master-dataset.csv`

**Bucket:** `result-s3-{ID_DA_CONTA}`
**Atualizado por:** Lambda `video-processor` (YOLO)

Contém todos os keypoints extraídos de todos os vídeos já processados. A cada novo vídeo,
as linhas são adicionadas ao final desse CSV. O formato é idêntico ao `raw-dataset.csv` do
repositório `exercises-dataset`.

Usado no **Jupyter Notebook** para re-treinamento de modelos com dados sempre atualizados:

```bash
# Dentro do Jupyter — baixar o master-dataset atualizado
aws s3 cp s3://result-s3-{ID_DA_CONTA}/master-dataset.csv datasets/user-raw-dataset.csv
```

---

## Troubleshooting

### Lambda inference: `No module named 'joblib'` ou `No module named 'xgboost'`

A Lambda está sem a Layer anexada. Verifique:

```bash
aws lambda get-function-configuration --function-name inference --query "Layers"
```

Se vazio, anexe a layer:

```bash
aws lambda update-function-configuration \
  --function-name inference \
  --layers "arn:aws:lambda:us-east-1:{ID_DA_CONTA}:layer:inference-deps:1"
```

### Lambda inference: ZIP excede 250MB (`Unzipped size must be smaller than 262144000 bytes`)

O `inference.zip` deve conter **apenas** o `inference.py` (~3KB). As dependências ficam na Layer.
Se o ZIP estiver grande, recrie-o:

```bash
cd iac-infra/lambda
rm -f zip/inference.zip
zip -j zip/inference.zip inference.py
ls -lh zip/inference.zip   # deve ser ~2-3KB
```

### Frontend: `Failed to fetch` / CORS bloqueado no polling

**Verifique a URL sendo chamada no DevTools (F12 → Network).**

Se a URL contém `%7Bfile_id%7D` (literal `{file_id}`), o `.env` do frontend está errado.
O valor correto é:

```
VITE_RESULT_API_URL=https://xxxxxx.execute-api.us-east-1.amazonaws.com/prod/result
```

**SEM** `/{file_id}` no final. O código concatena o ID automaticamente.

Após corrigir o `.env`, rebuild e redeploy do frontend (ver seção "Redeploy do Frontend").

### Frontend: CORS no upload PUT para o S3

O bucket Raw já tem CORS configurado no `storage.yml`. Se mesmo assim falhar:

```bash
aws s3api get-bucket-cors --bucket raw-s3-{ID_DA_CONTA}
```

Se vazio, aplique manualmente:

```bash
aws s3api put-bucket-cors --bucket raw-s3-{ID_DA_CONTA} --cors-configuration '{
  "CORSRules": [{
    "AllowedHeaders": ["*"],
    "AllowedMethods": ["PUT"],
    "AllowedOrigins": ["*"],
    "ExposeHeaders": []
  }]
}'
```

### Lambda processadora (YOLO): cold start muito lento (30-60s)

Isso é esperado — a imagem Docker tem ~3GB (ultralytics + PyTorch). Na primeira invocação
o Lambda precisa baixar e inicializar a imagem. Invocações subsequentes (warm) levam ~5s.

Para a banca: faça uma invocação de "aquecimento" antes da demonstração enviando um vídeo curto.

---

## Utils

### Deletar uma stack

```powershell
aws cloudformation delete-stack --stack-name {NOME_DA_STACK}
```

### Verificar eventos de uma stack

```powershell
aws cloudformation describe-stack-events --stack-name {NOME_DA_STACK}
```

### Atualizar código de uma Lambda (após novo zip)

```powershell
aws lambda update-function-code `
  --function-name {NOME_DA_FUNCAO} `
  --s3-bucket setup-bucket-{ID_DA_CONTA} `
  --s3-key {NOME_DO_ARQUIVO}.zip
```

### Remover todos os arquivos de um bucket S3

```powershell
aws s3 rm s3://{NOME_DO_BUCKET}/ --recursive
```

### Ver logs de uma Lambda

```powershell
aws logs tail /aws/lambda/{NOME_DA_FUNCAO} --follow
```

### Testar a Lambda de inferência manualmente

```bash
# Verificar se há resultado salvo para um file_id
aws s3 ls s3://result-s3-{ID_DA_CONTA}/results/

# Ler um resultado específico
aws s3 cp s3://result-s3-{ID_DA_CONTA}/results/{FILE_ID}.json -
```
