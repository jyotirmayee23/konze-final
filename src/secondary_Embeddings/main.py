import boto3
import os
import json
import concurrent.futures
from langchain.embeddings import BedrockEmbeddings
from langchain.vectorstores import FAISS
from langchain.document_loaders import TextLoader, PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import DirectoryLoader

# Clients
s3 = boto3.client('s3')
ssm_client = boto3.client('ssm')
lambda_client = boto3.client('lambda')

third_lambda_arn = os.getenv('SECONDARY_EXTRACTION_FUNCTION_ARN')
print("@", third_lambda_arn)

bedrock_runtime = boto3.client(
    service_name="bedrock-runtime",
    region_name="ap-south-1",
)

embeddings = BedrockEmbeddings(
    model_id="cohere.embed-english-v3",
    client=bedrock_runtime,
    region_name="ap-south-1",
)

def custom_loader(file_path):
    """
    Custom loader to handle different file types
    """
    extension = os.path.splitext(file_path)[1].lower()
    if extension == '.pdf':
        return PyPDFLoader(file_path)
    elif extension == '.txt':
        return TextLoader(file_path, encoding='utf-8')
    else:
        raise ValueError(f"Unsupported file type: {extension}")

def download_files_from_s3(bucket_name, folder_path, local_dir):
    """
    Download files from S3 with pagination support
    """
    paginator = s3.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=bucket_name, Prefix=folder_path):
        for obj in page.get('Contents', []):
            file_key = obj['Key']
            file_name = os.path.basename(file_key)
            local_file_path = os.path.join(local_dir, file_name)
            s3.download_file(bucket_name, file_key, local_file_path)
            print(f"Downloaded {file_key} to {local_file_path}")

def process_single_file(file_path, embeddings):
    """
    Process a single file and generate its embeddings
    
    Args:
        file_path (str): Path to the file
        embeddings (BedrockEmbeddings): Embedding model
    
    Returns:
        list: Processed documents
    """
    try:
        # Load the document
        loader = custom_loader(file_path)
        docs = loader.load()
        
        # Split documents into chunks
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=10)
        documents = text_splitter.split_documents(docs)
        print("documents",documents)
        return documents
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return []
    
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
    # print("1", event)
    job_id = event['job_id']
    print("job_id",job_id)
    student = event['folder_path']
    bucket_name = "konze-processing-bucket"
    folder_path = f"{job_id}/textfiles/secondary"  # S3 folder where the text files are stored

    # Temporary local folder to download the files
    local_dir = f"/tmp/{job_id}/secondembed"
    os.makedirs(local_dir, exist_ok=True)

    clear_directory_files(local_dir)

    # Download text files from S3
    download_files_from_s3(bucket_name, folder_path, local_dir)

    # Get list of files
    file_paths = [
        os.path.join(local_dir, file) 
        for file in os.listdir(local_dir) 
        if os.path.isfile(os.path.join(local_dir, file))
    ]
    
    print("file paths ", file_paths)

    # Parallel document processing
    all_documents = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(file_paths), 10)) as executor:
        # Submit processing tasks for each file
        futures = [
            executor.submit(process_single_file, file_path, embeddings) 
            for file_path in file_paths
        ]
        
        # Collect results
        for future in concurrent.futures.as_completed(futures):
            all_documents.extend(future.result())
            print("all documents ", all_documents)

    # Generate FAISS embeddings from the documents
    if all_documents:
        vector = FAISS.from_documents(all_documents, embeddings)
        
        # Save the embeddings locally
        faiss_path = f"/tmp/{job_id}/secondembed/index.faiss"
        pickle_path = f"/tmp/{job_id}/secondembed/index.pkl"
        vector.save_local(folder_path=f"/tmp/{job_id}/secondembed/", index_name="index")

        # Upload embeddings to S3
        s3.upload_file(faiss_path, bucket_name, f"{job_id}/embeddings/secondary/index.faiss")
        s3.upload_file(pickle_path, bucket_name, f"{job_id}/embeddings/secondary/index.pkl")
        print(f"Uploaded embeddings")

        # Set job status in SSM
        ssm_client.put_parameter(
            Name=job_id,
            Value="Vector Generated",
            Type='String',
            Overwrite=True
        )
        
        os.makedirs(local_dir, exist_ok=True)

        # Trigger the next Lambda function asynchronously
        payload = {
            "job_id": job_id ,
            "student": student
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
            "body": json.dumps("Embeddings generated and uploaded to S3."),
        }
    else:
        return {
            "statusCode": 400,
            "body": json.dumps("No documents found or processed."),
        }

def invoke_secondary_lambda_async(payload):
    response = lambda_client.invoke(
        FunctionName=third_lambda_arn,
        InvocationType='Event',  # Asynchronous invocation
        Payload=json.dumps(payload)
    )
    return response
