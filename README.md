# Infraestrutura como Código (IaC) — AlignFit

Gerenciado via AWS CloudFormation. Siga a ordem abaixo para um deploy completo.

---

## Ordem de deploy das stacks

```
1. setup.yml       → cria o bucket de artefatos
2. storage.yml     → cria todos os buckets S3
3. processing.yml  → SQS, EventBridge, Lambda processadora (YOLO) e Lambda de inferência
4. api.yml         → API Gateway + Lambda upload + Lambda get-result
5. frontend.yml    → EC2 com nginx servindo o build React
```

---

## 1. Stack Setup

Cria o bucket onde ficam os ZIPs das Lambdas e outros artefatos.

```powershell
aws cloudformation deploy `
  --template-file "setup.yml" `
  --stack-name "SetupAlignFitStack" `
  --capabilities "CAPABILITY_NAMED_IAM"
```

---

## 2. Subir os ZIPs das Lambdas para o bucket Setup

```powershell
# Empacotar as Lambdas Python (rode dentro da pasta iac-infra)
Compress-Archive -Path lambda\upload_video.py   -DestinationPath lambda\zip\upload_video.zip   -Force
Compress-Archive -Path lambda\inference.py      -DestinationPath lambda\zip\inference.zip      -Force
Compress-Archive -Path lambda\get_result.py     -DestinationPath lambda\zip\get_result.zip     -Force

# Enviar para o S3
aws s3 cp ./lambda/zip s3://setup-bucket-{ID_DA_CONTA}/ --recursive
```

---

## 3. Build e push da imagem Docker para o ECR (Lambda processadora)

### Opção A — Build remoto na EC2 (recomendado se o Docker local não funcionar)

#### 3.1 Subir a instância de build

```powershell
aws cloudformation deploy `
  --template-file "build.yml" `
  --stack-name "BuildAlignFitStack" `
  --capabilities "CAPABILITY_NAMED_IAM"
```

Aguardar a instância ficar pronta e pegar o IP:

```powershell
aws cloudformation describe-stacks `
  --stack-name "BuildAlignFitStack" `
  --query "Stacks[0].Outputs" `
  --output table
```

#### 3.2 Conectar na instância via SSM (sem chave SSH)

```powershell
# Substitua INSTANCE_ID pelo BuildInstanceId do output acima
aws ssm start-session --target {INSTANCE_ID}
```

> O SSM Session Manager abre um terminal direto no browser ou via CLI,
> sem precisar de par de chaves SSH ou porta 22 aberta.
> Se não tiver o plugin SSM instalado localmente:
> https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html

#### 3.3 Dentro da instância — clonar o repositório

```bash
# Aguardar o UserData terminar (deve aparecer "BUILD_INSTANCE_READY")
cat ~/ready.txt

# Clonar o repositório do projeto
cd ~
git clone https://github.com/{SEU_USUARIO}/{SEU_REPO}.git AlingFit
cd AlingFit
```

#### 3.4 Dentro da instância — autenticar no ECR e fazer o build

```bash
# Definir variáveis (substitua pelo ID real da sua conta)
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION=us-east-1
REPO=align-fit-processor

# Criar repositório no ECR (apenas na primeira vez)
aws ecr create-repository --repository-name $REPO --region $REGION 2>/dev/null || true

# Autenticar Docker no ECR
aws ecr get-login-password --region $REGION \
  | docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com

# Build da imagem (rodar na raiz do workspace — pasta AlingFit)
docker build -f iac-infra/Dockerfile -t $REPO .

# Tag e push
docker tag $REPO:latest $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$REPO:latest
docker push $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$REPO:latest

echo "✅ Push concluído: $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$REPO:latest"
```

#### 3.5 Terminar a instância após o build (evitar custos)

```powershell
# Rodar localmente após sair da sessão SSM
aws cloudformation delete-stack --stack-name "BuildAlignFitStack"
```

---

### Opção B — Build local (se o Docker Desktop estiver funcionando)

```powershell
# Criar repositório no ECR (apenas na primeira vez)
aws ecr create-repository --repository-name align-fit-processor

# Autenticar o Docker no ECR
aws ecr get-login-password --region us-east-1 `
  | docker login --username AWS --password-stdin {ID_DA_CONTA}.dkr.ecr.us-east-1.amazonaws.com

# Build da imagem — rodar na RAIZ do workspace (pasta AlingFit)
docker build -f iac-infra/Dockerfile -t align-fit-processor .

# Tag e push
docker tag align-fit-processor:latest {ID_DA_CONTA}.dkr.ecr.us-east-1.amazonaws.com/align-fit-processor:latest
docker push {ID_DA_CONTA}.dkr.ecr.us-east-1.amazonaws.com/align-fit-processor:latest
```

> **Atenção:** o build instala PyTorch CPU + ultralytics, o que pode levar 10–20 minutos
> e gerar uma imagem de ~4GB. Isso é esperado. O push para o ECR também levará alguns minutos.

---

## 4. Stack Storage

```powershell
aws cloudformation deploy `
  --template-file "storage.yml" `
  --stack-name "StorageAlignFitStack" `
  --capabilities "CAPABILITY_NAMED_IAM"
```

### Upload dos modelos treinados para o bucket Models

```powershell
aws s3 cp exercises-dataset/models/ s3://models-bucket-{ID_DA_CONTA}/ --recursive
```

---

## 5. Stack Processing

```powershell
aws cloudformation deploy `
  --template-file "processing.yml" `
  --stack-name "ProcessingAlignFitStack" `
  --parameter-overrides `
    "EcrImageUri={ID_DA_CONTA}.dkr.ecr.us-east-1.amazonaws.com/align-fit-processor:latest" `
    "SetupBucket=setup-bucket-{ID_DA_CONTA}" `
  --capabilities "CAPABILITY_NAMED_IAM"
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

Após o deploy, anote as URLs dos outputs `UploadApiUrl` e `ResultApiUrl`:

```powershell
aws cloudformation describe-stacks `
  --stack-name "ApiAlignFitStack" `
  --query "Stacks[0].Outputs"
```

---

## 7. Stack Frontend (EC2)

Substitua os valores de `UploadApiUrl` e `ResultApiUrl` pelos outputs da stack API.
Substitua também a URL do `git clone` no `frontend.yml` pelo repositório real antes de fazer deploy.

```powershell
aws cloudformation deploy `
  --template-file "frontend.yml" `
  --stack-name "FrontendAlignFitStack" `
  --parameter-overrides `
    "UploadApiUrl=https://g6r8f8o5ta.execute-api.us-east-1.amazonaws.com/prod/upload" `
    "ResultApiUrl=https://g6r8f8o5ta.execute-api.us-east-1.amazonaws.com/prod/result" `
  --capabilities "CAPABILITY_NAMED_IAM"
```

Obter a URL pública do frontend:

```powershell
aws cloudformation describe-stacks `
  --stack-name "FrontendAlignFitStack" `
  --query "Stacks[0].Outputs[?OutputKey=='FrontendUrl'].OutputValue" `
  --output text
```

### ⚠️ Como funciona o redeploy do frontend

O UserData da EC2 **só executa uma vez**, na criação da instância.
Rodar `cloudformation deploy` novamente **não atualiza** o frontend se nenhum recurso mudou no template.

Existem duas formas de atualizar o frontend após o primeiro deploy:

---

#### Opção A — SSH na EC2 (mais rápido, recomendado para iterações rápidas)

```powershell
# Obter o IP da instância
$ip = aws cloudformation describe-stacks `
  --stack-name "FrontendAlignFitStack" `
  --query "Stacks[0].Outputs[?OutputKey=='FrontendPublicIp'].OutputValue" `
  --output text

# Conectar
ssh ec2-user@$ip
```

Dentro da EC2:

```bash
cd /opt/align-fit-web
git pull
npm run build
cp -r dist/* /usr/share/nginx/html/
```

---

#### Opção B — Forçar recriação da EC2 via CloudFormation

Incremente o parâmetro `DeployVersion` a cada redeploy.
O CloudFormation detecta a mudança de tag e recria a instância do zero, re-executando o UserData completo.

```powershell
aws cloudformation deploy `
  --template-file "frontend.yml" `
  --stack-name "FrontendAlignFitStack" `
  --parameter-overrides `
    "UploadApiUrl=https://{API_ID}.execute-api.us-east-1.amazonaws.com/prod/upload" `
    "ResultApiUrl=https://{API_ID}.execute-api.us-east-1.amazonaws.com/prod/result" `
    "DeployVersion=2" `
  --capabilities "CAPABILITY_NAMED_IAM"
```

> A cada novo redeploy incremente `DeployVersion` (`2`, `3`, `4`...).
> O IP público da instância vai mudar — obtenha o novo IP com o comando de describe acima.

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
