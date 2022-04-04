terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 3.27"
    }
  }

  required_version = ">= 0.14.9"
}

provider "aws" {
  profile = "default"
  region  = "us-east-1"
}


###############################################################################
### SageMaker Security Group
###############################################################################
resource "aws_security_group" "smNotebook" {
  name        = "TF-SM-NOTEBOOK-SG"
  description = "Security group for SageMaker Notebook"
  vpc_id      = local.vpc-id

  tags = {
    Name = "TF-SM-NOTEBOOK-SG"
  }
}

resource "aws_security_group_rule" "glue-dev-endpoint-rule" {
  type              = "egress"
  description       = "Allow outbound SSH traffic to the Glue Dev Endpoint SG"
  from_port         = 22
  to_port           = 22
  protocol          = "tcp"
  security_group_id = "${aws_security_group.smNotebook.id}"
  source_security_group_id = "${aws_security_group.devEndpoint.id}"
}

resource "aws_security_group_rule" "smnb-allow-https-out" {
  type              = "egress"
  description       = "Allow outbound HTTPS traffic to the internet (At minimum needed for access to the S3 bucket ws-glue-jes-prod-us-east-1-assets)"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = "${aws_security_group.smNotebook.id}"
}
###############################################################################


###############################################################################
### SageMaker Notebook Instance
###############################################################################
resource "aws_sagemaker_notebook_instance" "ni" {
  name          = "aws-glue-tf-sm-notebook-instance"
  role_arn      = local.iam_role_arn_nb
  instance_type = "ml.t2.medium"
  platform_identifier = "notebook-al1-v1"
  subnet_id           = local.subnet-id
  security_groups     = [aws_security_group.smNotebook.id]
  direct_internet_access = "Disabled"
  lifecycle_config_name  = aws_sagemaker_notebook_instance_lifecycle_configuration.lc.name

  tags = {
    aws-glue-dev-endpoint = aws_glue_dev_endpoint.example.name
  }
}

resource "aws_sagemaker_notebook_instance_lifecycle_configuration" "lc" {
  name      = "tf-sm-notebook-lifecycle"
  on_create = filebase64("${path.module}/lifecycle_scripts/on_create.sh")
  on_start  = filebase64("${path.module}/lifecycle_scripts/on_start.sh")
}
###############################################################################





###############################################################################
### Glue Developer Endpoint Security Group
###############################################################################
resource "aws_security_group" "devEndpoint" {
  name        = "TF-GLUE-SG"
  description = "Allow traffic local VPC"
  vpc_id      = local.vpc-id

  tags = {
    Name = "TF-GLUE-SG"
  }
}

resource "aws_security_group_rule" "self-referencing-ingress-rule" {
  type              = "ingress"
  description       = "Self-referencing ingress rule"
  from_port         = 0
  to_port           = 65535
  protocol          = "tcp"
  security_group_id = "${aws_security_group.devEndpoint.id}"
  source_security_group_id = "${aws_security_group.devEndpoint.id}"
}

resource "aws_security_group_rule" "self-referencing-egress-rule" {
  type              = "egress"
  description       = "Self-referencing egress rule"
  from_port         = 0
  to_port           = 65535
  protocol          = "tcp"
  security_group_id = "${aws_security_group.devEndpoint.id}"
  source_security_group_id = "${aws_security_group.devEndpoint.id}"
}

resource "aws_security_group_rule" "sagemaker-notebook-rule" {
  type              = "ingress"
  description       = "Allow traffic from the SageMaker Notebook"
  from_port         = 22
  to_port           = 22
  protocol          = "tcp"
  security_group_id = "${aws_security_group.devEndpoint.id}"
  source_security_group_id = "${aws_security_group.smNotebook.id}"
}
###############################################################################


###############################################################################
### Glue Development Endpoint
###############################################################################
resource "aws_glue_dev_endpoint" "example" {
  name     = "MyFirstDevEndpoint"
  role_arn = local.iam_role_arn
  security_group_ids = [aws_security_group.devEndpoint.id]
  subnet_id = local.subnet-id
  glue_version = "1.0"
  arguments =  tomap({"--enable-glue-datacatalog"=" ", "GLUE_PYTHON_VERSION"="3"})

  depends_on = [aws_security_group.devEndpoint, 
                aws_security_group_rule.self-referencing-ingress-rule,
                aws_security_group_rule.self-referencing-egress-rule]
}
###############################################################################

output "dev_endpoint_private_ip" {
  value = aws_glue_dev_endpoint.example.private_address
}

#output "dev_endpoint_eni_id" { value = aws_glue_dev_endpoint.example.network_interface_id }
output "sagemaker_eni_id"    { value = aws_sagemaker_notebook_instance.ni.network_interface_id }


locals {
    iam_role_arn_nb   = "arn:aws:iam::614129417617:role/service-role/AWSGlueServiceSageMakerNotebookRole-Test_Role"
    iam_role_arn      = "arn:aws:iam::614129417617:role/service-role/AWSGlueServiceRole-TestRole"
    subnet-id         = "subnet-069a69e50bd1ebb23"
    vpc-id            = "vpc-00b09e53c6e62a994"
}