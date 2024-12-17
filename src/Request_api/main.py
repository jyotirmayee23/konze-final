import json
import boto3
import uuid
import os
from urllib.parse import urlparse

ssm_client = boto3.client('ssm')
lambda_client = boto3.client('lambda')
primary_lambda_arn = os.getenv('PRIMARY_FUNCTION_ARN')
secondary_lambda_arn = os.getenv('SECONDARY_FUNCTION_ARN')
print("@",secondary_lambda_arn)


def invoke_secondary_lambda_async(payload):
    response = lambda_client.invoke(
        FunctionName=secondary_lambda_arn,
        InvocationType='Event',  # Asynchronous invocation
        Payload=json.dumps(payload)
    )
    return response

def invoke_primary_lambda_async(payload):
    response = lambda_client.invoke(
        FunctionName=primary_lambda_arn,
        InvocationType='Event',  # Asynchronous invocation
        Payload=json.dumps(payload)
    )
    return response

def lambda_handler(event, context):
    print("event",event)
    body_dict = json.loads(event['body'])
    link = body_dict.get('link', '').replace('+', ' ')
    print(link)  
    
    parsed_url = urlparse(link)
    bucket_name = parsed_url.netloc.split('.')[0]
    folder_path = parsed_url.path.lstrip('/')
    
        
    print("bucket",bucket_name)
    print("folder",folder_path)
    # body_dict = json.loads(event['body'])
    job_id = str(uuid.uuid4())
    parameter_name = job_id
    print(f"Links received: {link}")
    ssm_client.put_parameter(
        Name=parameter_name,
        Value="In Progress",
        Type='String',  
        Overwrite=True
    )

    payload = {
        "job_id": job_id,
        "folder_path": folder_path,
        "links": link,
    }

    print("2",payload)
    
    # Invoke the secondary Lambda function asynchronously
    invoke_primary_lambda_async(payload)
    invoke_secondary_lambda_async(payload)
    
    # Return the response immediately
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "*",
        },
        "body": json.dumps(job_id),
    }
