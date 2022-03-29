# aws-glue-private-development-endpoint

This repo is used to show how to connect an (existing) SageMaker Notebook to a new AWS Glue Development Endpoint.  In this example both the SageMaker Notebook and Glue Dev Endpoint reside in a Private subnet.  The `main.tf` script assumes you already have a VPC, Private Subnet, VPC endpoints in place for Glue+SageMaker, necessary IAM Role and an EC2 deployed to the same private subnet.  

## TODO
- [ ] Setup the VPC Endpoints to the necessary Glue & SageMaker services
- [ ] Complete the Architecture Diagram
- [ ] README: Complete the Steps for Creating the resources
- [ ] Test it all out

## General Approach for attaching an existing SageMaker Notebook to a new Glue Dev Endpoint

* Need to apply a similar lifecycle configuration as a notebook created from Glue 
* Add a tag with the key aws-glue-dev-endpoint and as value the name of the development endpoint.
* You cannot specify your own public_key on the Glue Dev Endpoint.

This is a similar script that would need to be applied for both events in the lifecycle configuration (you need to change the endpoint and notebook names below in the python3 command):

```
#!/bin/bashset -ex[ -e /home/ec2-user/glue_ready ] && exit 0

mkdir /home/ec2-user/glue
cd /home/ec2-user/glue
ASSETS=s3://aws-glue-jes-prod-eu-west-1-assets/sagemaker/assets/
DEV_ENDPOINT_NAME=test-vpc
aws s3 cp ${ASSETS} . --recursive

tar -xf autossh-1.4e.tgz
cd autossh-1.4e./configure
make
sudo make install
pip install pandas==0.22.0

mkdir -p /home/ec2-user/.sparkmagic
cp /home/ec2-user/glue/config.json /home/ec2-user/.sparkmagic/config.json

mkdir -p /home/ec2-user/SageMaker/Glue\ Examples
mv /home/ec2-user/glue/notebook-samples/* /home/ec2-user/SageMaker/Glue\ Examples/

sudo cp /home/ec2-user/glue/autossh.conf /etc/init/
python3 /home/ec2-user/glue/bootstrap.py --devendpointname <yourendpointname> --endpoint https://glue.eu-west-1.amazonaws.com (https://glue.eu-west-1.amazonaws.com/) --notebookname <yournotebookname>
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

3. The Dev Endpoint should move into a "Provisioning status" = "READY" (~10mins). The script should also output a value for the private address of the endpoint. The output variable is "dev_endpoint_private_ip".   Use it to connect to the Dev Endpoint.

```
ssh -i PrivateKeyPair.pem glue@${dev_endpoint_private_ip}
```

Confirm you are able to connect to your endpoint.

```
[ec2-user@ip-10-0-100-62 ~]$ 
[ec2-user@ip-10-0-100-62 ~]$ 
[ec2-user@ip-10-0-100-62 ~]$ ssh -i DemoVPC_Key_Pair.pem glue@ip-10-0-100-18.ec2.internal
The authenticity of host 'ip-10-0-100-18.ec2.internal (10.0.100.18)' can't be established.
ECDSA key fingerprint is SHA256:QqCAZfwHfkUnUZHGaTjVtjRGHweSzin1mBZh3/LqwRg.
ECDSA key fingerprint is MD5:61:73:47:22:34:49:3d:b8:16:11:71:ff:a5:c2:51:6e.
Are you sure you want to continue connecting (yes/no)? yes
Warning: Permanently added 'ip-10-0-100-18.ec2.internal,10.0.100.18' (ECDSA) to the list of known hosts.

       __|  __|_  )
       _|  (     /   Amazon Linux AMI
      ___|\___|___|

https://aws.amazon.com/amazon-linux-ami/2018.03-release-notes/
55 package(s) needed for security, out of 86 available
Run "sudo yum update" to apply all updates.
                                                                    
EEEEEEEEEEEEEEEEEEEE MMMMMMMM           MMMMMMMM RRRRRRRRRRRRRRR    
E::::::::::::::::::E M:::::::M         M:::::::M R::::::::::::::R   
EE:::::EEEEEEEEE:::E M::::::::M       M::::::::M R:::::RRRRRR:::::R 
  E::::E       EEEEE M:::::::::M     M:::::::::M RR::::R      R::::R
  E::::E             M::::::M:::M   M:::M::::::M   R:::R      R::::R
  E:::::EEEEEEEEEE   M:::::M M:::M M:::M M:::::M   R:::RRRRRR:::::R 
  E::::::::::::::E   M:::::M  M:::M:::M  M:::::M   R:::::::::::RR   
  E:::::EEEEEEEEEE   M:::::M   M:::::M   M:::::M   R:::RRRRRR::::R  
  E::::E             M:::::M    M:::M    M:::::M   R:::R      R::::R
  E::::E       EEEEE M:::::M     MMM     M:::::M   R:::R      R::::R
EE:::::EEEEEEEE::::E M:::::M             M:::::M   R:::R      R::::R
E::::::::::::::::::E M:::::M             M:::::M RR::::R      R::::R
EEEEEEEEEEEEEEEEEEEE MMMMMMM             MMMMMMM RRRRRRR      RRRRRR
                                                                    
[glue@ip-172-32-23-41 ~]$ 
```

## Notes to Consider
* When selecting the VPC, it must have access to an S3 endpoint to allow private connections to the S3 service.  This is needed if you define your Python library and dependent jars paths.
* When selecting the VPC, Subnet and Security Groups, you must only select a Security Group that has a "self-referencing" rule.

## Clean up Resources
1. To delete the resources created from the terraform script run the following.the destroy command.
```
terraform destroy
```

## Questions & Comments
If you have any questions or comments on the demo please reach out to me [Devin Lewis - AWS Solutions Architect](mailto:lwdvin@amazon.com?subject=AWS%2FTerraform%20FMS%20Create%20Application%20List%20%28aws-terraform-fms-put-apps-list%29)

Of if you would like to provide personal feedback to me please click [Here](https://feedback.aws.amazon.com/?ea=lwdvin&fn=Devin&ln=Lewis)
