
import boto3
import json
import os
import fitz
from concurrent.futures import ThreadPoolExecutor, as_completed
from botocore.exceptions import ClientError
from urllib.parse import urlparse
import logging

# Initialize boto3 clients
lambda_client = boto3.client('lambda')
s3_client = boto3.client('s3')
textract = boto3.client('textract')

secondary_lambda_arn = os.getenv('PRIMARY_EMBEDDING_FUNCTION_ARN')

def invoke_secondary_lambda_async(payload):
    response = lambda_client.invoke(
        FunctionName=secondary_lambda_arn,
        InvocationType='Event',  # Asynchronous invocation
        Payload=json.dumps(payload)
    )
    return response

def process_page(page_number, local_path, textract_client):
    ("process page statrted")
    pdf_document = fitz.open(local_path)
    page = pdf_document.load_page(page_number)
    pix = page.get_pixmap()
    img_bytes = pix.tobytes("png")
    
    response = textract_client.detect_document_text(
        Document={'Bytes': img_bytes}
    )

    page_text = " ".join(item['Text'] for item in response['Blocks'] if item['BlockType'] == 'LINE')

    return page_number, page_text  # Return page number with the result

def process_pdf(local_path, textract_client, job_id):
    aggregated_text = ""
    confidence_scores = []
    print("local path process pdf",local_path)

    with ThreadPoolExecutor() as executor:
        pdf_document = fitz.open(local_path)
        futures = {executor.submit(process_page, page_number, local_path, textract_client): page_number for page_number in range(len(pdf_document))}

        # Collect results and sort by page number
        results = sorted((future.result() for future in as_completed(futures)), key=lambda x: x[0])
        for page_number, text in results:  # Unpack the sorted results
            aggregated_text += text + " "  # Append text in sequence with a space after each block
            
    output_directory = f"/tmp/{job_id}_output/konzeprimary"
    
    text_filename = os.path.splitext(os.path.basename(local_path))[0] + '.txt'
    text_file_path = os.path.join(output_directory, text_filename)

        # Write extracted text to file
    with open(text_file_path, 'w') as text_file:
        text_file.write(aggregated_text)

        # Upload the text file to S3
    s3_upload_path = f"{job_id}/textfiles/primary/{text_filename}"
    upload_file_to_s3(text_file_path, 'konze-processing-bucket', s3_upload_path)

    
    return aggregated_text

def upload_file_to_s3(file_path, bucket_name, s3_path):
    s3_client.upload_file(file_path, bucket_name, s3_path)
    print(f"Uploaded {file_path} to s3://{bucket_name}/{s3_path}")

def list_files_in_s3(bucket_name, folder_path):
    s3_client = boto3.client('s3')
    response = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=folder_path)
    return [obj['Key'] for obj in response.get('Contents', [])]


def download_files_from_s3(bucket_name, folder_path, local_dir):
    s3_client = boto3.client('s3')
    files = list_files_in_s3(bucket_name, folder_path)

    for file_key in files:
        local_file_path = os.path.join(local_dir, os.path.relpath(file_key, folder_path))
        local_file_dir = os.path.dirname(local_file_path)
        
        # Ensure the directory exists
        if not os.path.exists(local_file_dir):
            os.makedirs(local_file_dir)

        logging.info(f"Downloading {file_key} to {local_file_path}")

        try:
            s3_client.download_file(bucket_name, file_key, local_file_path)
            logging.info(f"Downloaded {file_key} to {local_file_path}")
        except OSError as e:
            logging.error(f"Failed to download {file_key} to {local_file_path}: {e}")
            # Handle the error appropriately, e.g., retry, skip, etc.
        except Exception as e:
            logging.error(f"Unexpected error occurred while downloading {file_key} to {local_file_path}: {e}")
            # Handle other potential exceptions


def list_files_in_directory(directory):
    try:
        files = os.listdir(directory)
        num_files = len(files)
        
        if num_files == 0:
            print(f"No files in directory: {directory}")
        else:
            print(f"Number of files in directory {directory}: {num_files}")
            # print(f"Files in directory {directory}:")
            for file in files:
                print(file)
    except Exception as e:
        print(f"Error listing files in directory {directory}: {str(e)}")


def clear_directory_files(directory):
    # Check if the directory exists
    if not os.path.exists(directory):
        print(f"Directory does not exist: {directory}")
        return
    
    # Get the list of all files in the directory
    files = os.listdir(directory)
    
    # If the directory is empty, return
    if not files:
        print(f"No files to delete in directory: {directory}")
        return
    
    for file in files:
        file_path = os.path.join(directory, file)
        
        # Check if it is a file and remove it
        if os.path.isfile(file_path):
            os.remove(file_path)
            print(f"Deleted file: {file_path}")

def lambda_handler(event, context):
    job_id = event['job_id']
    links = event.get('links', [])
    print("links", links)
    parsed_url = urlparse(links)
    bucket_name = parsed_url.netloc.split('.')[0]
    folder_path = parsed_url.path.lstrip('/')

    folder_path = os.path.join(folder_path.rstrip('/'), 'primary')
    # folder_path = folder_path.rstrip('/')
    print("bucket", bucket_name)
    print("folder", folder_path)
    
    local_dir = f"/tmp/{job_id}/konzeprimary"
    clear_directory_files(local_dir)
    print("Temporary directory:", local_dir)
    os.makedirs(local_dir, exist_ok=True)
    
    output_directory = f"/tmp/{job_id}_output/konzeprimary"
    clear_directory_files(output_directory)
    print("Output directory:", output_directory)
    
    os.makedirs(output_directory, exist_ok=True)
    
    download_files_from_s3(bucket_name, folder_path, local_dir)
    
    pdf_files = [
        os.path.join(local_dir, pdf_file) 
        for pdf_file in os.listdir(local_dir) 
        if pdf_file.endswith('.pdf')
    ]
    
    print("pdf files ", pdf_files)

    aggregated_text = ""
    overall_confidences = []
    
    for pdf_file in pdf_files:
        try:
            avg_confidence = process_pdf(pdf_file, textract, job_id)
            print("text created successfully")

        except Exception as e:
            print(f"Error processing PDF file {pdf_file}: {e}")
            continue


    clear_directory_files(local_dir)
    clear_directory_files(output_directory)
    
    payload = {
        "job_id": job_id,
        "folder_path" : folder_path
    }

    invoke_secondary_lambda_async(payload)

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "*",
        },
        "body": json.dumps("in progress"),
    }
