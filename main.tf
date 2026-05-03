resource "aws_s3_bucket" "dataset" {
  bucket = "align-fit-dataset" 

  tags = {
    Name        = "dataset"
    Environment = "prod"
  }
}

resource "aws_s3_bucket_public_access_block" "block" {
  bucket = aws_s3_bucket.dataset.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}