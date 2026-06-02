# Infraestrutura como Código (IaC)

Este repositório contém os arquivos necessários para criar e gerenciar recursos na AWS usando CloudFormation.

### Rodar a Stack Setup (setup.yml)

Para criar o Bucket que armazena as funções Lambdas:

```bash
aws cloudformation deploy `
   --template-file "setup.yml" `
   --stack-name "SetupAlignFitStack" `
   --capabilities "CAPABILITY_NAMED_IAM" `
```

### Subir os arquivos no Bucket

```bash
aws s3 cp ./lambda/zip s3://setup-bucket-511999689174/ --recursive
```

### Rodar a Stack Storage

```bash
aws cloudformation deploy `
   --template-file "storage.yml" `
   --stack-name "StorageAlignFitStack" `
   --capabilities "CAPABILITY_NAMED_IAM" `
```

### Rodar a Stack Processing

```bash
aws cloudformation deploy `
   --template-file "processing.yml" `
   --stack-name "ProcessingAlignFitStack" `
   --parameter-overrides "SetupBucket=setup-bucket-511999689174" `
   --capabilities "CAPABILITY_NAMED_IAM" `
```

### Rodar a Stack API

```bash
aws cloudformation deploy `
   --template-file "api.yml" `
   --stack-name "ApiAlignFitStack" `
   --parameter-overrides "SetupBucket=setup-bucket-511999689174" `
   --capabilities "CAPABILITY_NAMED_IAM" `
```

# Utils

### Deletar a Stack

```bash
aws cloudformation delete-stack --stack-name AlignFitStack
```

### Verificar a Stack

```bash
aws cloudformation describe-stack-events --stack-name AlignFitStack
```

### Atualizar Lambda

```bash
aws lambda update-function-code `
  --function-name trigger_client_to_dynamo `
  --s3-bucket setup-bucket-{id da conta AWS} `
  --s3-key trigger_client_to_dynamo.zip
```

### Remover arquivos S3

```bash
aws s3 rm s3://raw-bucket-{id da conta AWS}/ --recursive
```
