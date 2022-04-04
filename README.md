# aws-glue-private-development-endpoint

This repo is used to show how to connect an (existing) SageMaker Notebook to a new AWS Glue Development Endpoint.  In this example both the SageMaker Notebook and Glue Dev Endpoint reside in a Private subnet.  The `main.tf` script assumes you already have a VPC, Private Subnet, VPC endpoints, necessary IAM Role and an EC2 deployed to the same private subnet.  

## TODO
- [X] Determine Routing between the SG Notbeook and Glue Dev Endpoint (VPC Endpoints needed?)
- [ ] Complete the Architecture Diagram
- [ ] README: Complete the Steps for Creating the resources
- [X] Determine if you can specify your own private/public key on the Glue Dev Endpoint.
- [ ] Test it all out

## General Approach for attaching an existing SageMaker Notebook to a new Glue Dev Endpoint

* Need to apply a similar lifecycle configuration as a notebook created from Glue 
* Add a tag with the key aws-glue-dev-endpoint and as value the name of the development endpoint.
* (Optional) In order for the SageMaker Notebook to display on the Glue-->Dev Endpoints-->Notebooks page you must prefix the name of your notbook with "aws-glue-".

This is a similar script that would need to be applied for both events in the lifecycle configuration (you need to change the endpoint and notebook names below in the python3 command):

```
#!/bin/bash
set -ex
[ -e /home/ec2-user/glue_ready ] && exit 0

mkdir -p /home/ec2-user/glue
cd /home/ec2-user/glue

# Write dev endpoint in a file which will be used by daemon scripts
glue_endpoint_file="/home/ec2-user/glue/glue_endpoint.txt"

if [ -f $glue_endpoint_file ] ; then
    rm $glue_endpoint_file
fi
echo "https://glue.us-east-1.amazonaws.com" >> $glue_endpoint_file

ASSETS=s3://aws-glue-jes-prod-us-east-1-assets/sagemaker/assets/

aws s3 cp ${ASSETS} . --recursive

bash "/home/ec2-user/glue/Miniconda2-4.5.12-Linux-x86_64.sh" -b -u -p "/home/ec2-user/glue/miniconda"

source "/home/ec2-user/glue/miniconda/bin/activate"

tar -xf autossh-1.4e.tgz
cd autossh-1.4e
./configure
make
sudo make install
sudo cp /home/ec2-user/glue/autossh.conf /etc/init/

mkdir -p /home/ec2-user/.sparkmagic
cp /home/ec2-user/glue/config.json /home/ec2-user/.sparkmagic/config.json

mkdir -p /home/ec2-user/SageMaker/Glue\ Examples
mv /home/ec2-user/glue/notebook-samples/* /home/ec2-user/SageMaker/Glue\ Examples/

# ensure SageMaker notebook has permission for the dev endpoint
aws glue get-dev-endpoint --endpoint-name <yourendpointname> --endpoint https://glue.us-east-1.amazonaws.com

# Run daemons as cron jobs and use flock make sure that daemons are started only iff stopped
(crontab -l; echo "* * * * * /usr/bin/flock -n /tmp/lifecycle-config-v2-dev-endpoint-daemon.lock /usr/bin/sudo /bin/sh /home/ec2-user/glue/lifecycle-config-v2-dev-endpoint-daemon.sh 2>&1 | tee -a /var/log/sagemaker-lifecycle-config-v2-dev-endpoint-daemon.log") | crontab -

(crontab -l; echo "* * * * * /usr/bin/flock -n /tmp/lifecycle-config-reconnect-dev-endpoint-daemon.lock /usr/bin/sudo /bin/sh /home/ec2-user/glue/lifecycle-config-reconnect-dev-endpoint-daemon.sh 2>&1 | tee -a /var/log/sagemaker-lifecycle-config-reconnect-dev-endpoint-daemon.log") | crontab -

CONNECTION_CHECKER_FILE=/home/ec2-user/glue/dev_endpoint_connection_checker.py
if [ -f "$CONNECTION_CHECKER_FILE" ]; then
    # wait for async dev endpoint connection to come up
    echo "Checking DevEndpoint connection."
    python3 $CONNECTION_CHECKER_FILE
fi

source "/home/ec2-user/glue/miniconda/bin/deactivate"

rm -rf "/home/ec2-user/glue/Miniconda2-4.5.12-Linux-x86_64.sh"

sudo touch /home/ec2-user/glue_ready
```

## Architecture
![alt text](https://github.com/gravelgrinder/aws-glue-private-dev-endpoint-sagemaker-nb/blob/main/architecture-diagram.png?raw=true)

## Create Resources
1. Run the following to Initialize the Terraform environment.

```
terraform init
```

2. Provision the resources in the `main.tf` script

```
terraform apply
```

3. The Dev Endpoint should move into a "Provisioning status" = "READY" (~10mins). The Sagemaker Notebook should also change into a Status = "InService".

4. Confirm you are connect to your Dev Endpoint from your SageMaker Notebook.

## Notes to Consider
* When selecting the VPC, it must have access to an S3 endpoint to allow private connections to the S3 service.  This is needed if you define your Python library and dependent jars paths.
* When selecting the VPC, Subnet and Security Groups, you must only select a Security Group that has a "self-referencing" rule.

## Clean up Resources
1. To delete the resources created from the terraform script run the following.the destroy command.
```
terraform destroy
```


## Helpful Resources
[Customize a Notebook Instance Using a Lifecycle Configuration Script](https://docs.aws.amazon.com/sagemaker/latest/dg/notebook-lifecycle-config.html)
[GitHub SageMaker Notebook Instance Lifecycle Config Samples](https://github.com/aws-samples/amazon-sagemaker-notebook-instance-lifecycle-config-samples)
[Required Ports for Dev Endpoint and Notebooks](https://docs.aws.amazon.com/glue/latest/dg/start-development-endpoint.html)

AWSCLI Command to Describe Differences Between SageMaker Notebooks
```
aws sagemaker describe-notebook-instance --notebook-instance-name aws-glue-tf-sm-notebook-instance
aws sagemaker describe-notebook-instance --notebook-instance-name aws-glue-console-created-nb
```

AWSCLI Command to Download the Sagemaker S3 Assets
```
mkdir -p sagemaker/assets; cd sagemaker/assets
aws s3 cp s3://aws-glue-jes-prod-us-east-1-assets/sagemaker/assets/ . --recursive
```

## Questions & Comments
If you have any questions or comments on the demo please reach out to me [Devin Lewis - AWS Solutions Architect](mailto:lwdvin@amazon.com?subject=AWS%2FTerraform%20FMS%20Create%20Application%20List%20%28aws-terraform-fms-put-apps-list%29)

Of if you would like to provide personal feedback to me please click [Here](https://feedback.aws.amazon.com/?ea=lwdvin&fn=Devin&ln=Lewis)
