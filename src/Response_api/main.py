import json
import boto3
import os

# Initialize AWS clients
ssm_client = boto3.client('ssm')
s3_client = boto3.client('s3')

def lambda_handler(event, context):
    try:
        # Parse the incoming event body
        body_content = event['body']
        body_dict = json.loads(body_content)

        # Extract job_id from the parsed dictionary
        job_id = body_dict.get('job_id')
        print(f"Extracted job_id: {job_id}")
        
        bucket_name = "konze-processing-bucket"
        output_folder_s3_key = f"{job_id}/output/"
        
        group1 = None  # Variable to store primary_response.json content
        group2 = None  # Variable to store secondary_response.json content
        appended_data = []
        
        primary_s3_key = f"{job_id}/output/primary_response.json"
        secondary_s3_key = f"{job_id}/output/secondary_response.json"
        
        # Retrieve job status from SSM Parameter Store
        parameter_name = job_id
        response = ssm_client.get_parameter(Name=parameter_name)

        if 'Parameter' in response and 'Value' in response['Parameter']:
            parameter_value = response['Parameter']['Value']
            print(f"Parameter value retrieved: {parameter_value}")

            # Check if the value is "Extraction completed"
            if parameter_value == "Extraction completed":
                # List objects in the output folder for the given job_id
                objects_in_folder = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=output_folder_s3_key)
                # Get the list of object keys in the output folder
                files_in_output = [obj['Key'] for obj in objects_in_folder.get('Contents', [])]

                # Check if both required files are present
                required_files = ['primary_response.json', 'secondary_response.json']
                missing_files = [file for file in required_files if f"{output_folder_s3_key}{file}" not in files_in_output]

                if missing_files:
                    print(f"Missing files: {', '.join(missing_files)}")
                    return {
                        'statusCode': 202,  # HTTP status code for accepted, indicating retry logic
                        'body': json.dumps({
                            'status': 'retry',
                            'message': "The required files are not ready yet. Please try again in a few minutes."
                        })
                    }
                
                # Both files are present, proceed with fetching them
                try:
                    # Download the primary_response.json file
                    primary_s3_response = s3_client.get_object(Bucket=bucket_name, Key=primary_s3_key)
                    primary_file_content = primary_s3_response['Body'].read().decode('utf-8')
                    group1 = json.loads(primary_file_content)  # Store the content in group1
                    print(f"Retrieved primary JSON data: {group1}")
                except s3_client.exceptions.NoSuchKey:
                    print(f"Primary response file not found: {primary_s3_key}")
                    group1 = None  # If file not found, set group1 to None

                try:
                    # Download the secondary_response.json file
                    secondary_s3_response = s3_client.get_object(Bucket=bucket_name, Key=secondary_s3_key)
                    secondary_file_content = secondary_s3_response['Body'].read().decode('utf-8')
                    group2 = json.loads(secondary_file_content)  # Store the content in group2
                    print(f"Retrieved secondary JSON data: {group2}")
                except s3_client.exceptions.NoSuchKey:
                    print(f"Secondary response file not found: {secondary_s3_key}")
                    group2 = None  # If file not found, set group2 to None
                    
                final_templates = [group1, group2]
                data = json.dumps(final_templates, indent=4)

                # Return only final_templates as the JSON response
                return {
                    'statusCode': 200,
                    'body': data  # Return the formatted final_templates JSON directly
                }

            else:
                # If extraction is not completed, return a message to try again later
                return {
                    "statusCode": 202,
                    "body": json.dumps({
                        "message": f"Extraction not completed yet. Current status: {parameter_value}. Please try again later."
                    })
                }
        else:
            print("Parameter value not found.")
            return {
                "statusCode": 500,
                "body": json.dumps({"error": "Parameter not found in SSM."})
            }

    except Exception as e:
        print(f"Error occurred: {str(e)}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
