import boto3
from io import BytesIO
import json
import datetime
import os
import tempfile
from botocore.config import Config
import requests
import io
from langchain.embeddings import BedrockEmbeddings
from langchain.indexes import VectorstoreIndexCreator
from langchain.vectorstores import FAISS
from langchain_core.prompts import ChatPromptTemplate
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain.chains import create_retrieval_chain
from langchain_community.chat_models import BedrockChat
import concurrent.futures
from langchain.chains import RetrievalQA
from langchain_core.prompts import ChatPromptTemplate


prompt_template = ChatPromptTemplate.from_template("""Please fill in the missing details in the following information::

<context>
{context}
</context>

<instructions>
- The primary applicant is the main individual applying for the immigration process. This person: - Is referred to explicitly as the primary applicant in the application or documents. - Is responsible for initiating the application process. - Has their name, personal details, and qualifications as the focal point of the application.
- Focus only on the primary applicant details. Skip any mention of secondary applicants.
- Ensure the extracted values match the keys provided in the schema.
- If a value is missing in the document, set it as a blank space " ".
- Do not include unnecessary characters or titles (e.g., "Mr.", "Ms.") unless explicitly stated as part of the name.
- Write all date-relevant information in yyyy-mm-dd format.
- For the gender field, ensure it only returns "male" or "female"; do not return abbreviated forms like "m" or "f".
- Return only the JSON.
- If values cannot be found, return the JSON as it is without anything extra at the start or end.
</instructions>
 
Question: {input}""")


s3 = boto3.client('s3')
ssm_client = boto3.client('ssm')


bedrock_runtime = boto3.client( 
        service_name="bedrock-runtime",
        region_name="ap-south-1",
    )

embeddings = BedrockEmbeddings(
        model_id="cohere.embed-english-v3",
        client=bedrock_runtime,
        region_name="ap-south-1",
    )

index_creator = VectorstoreIndexCreator(
        vectorstore_cls=FAISS,
        embedding=embeddings,
    )

llm = BedrockChat(
    model_id="anthropic.claude-3-haiku-20240307-v1:0",
    client=bedrock_runtime,
    region_name="ap-south-1",
    model_kwargs={"temperature": 0.0},
)	

template1 = {
        "applicant_info": {
            "applicant_type": "Primary",
            "firstname": " ",
            "middlename": " ",
            "lastname": " ",
            "gender": "male / female",
            "dateofbirth": ""
        },
        "contact_information_info": {
            "address": {
                "address": "",
                "city": "",
                "zipcode": "",
                "state": "",
                "country": ""
            }
        }
    }


template2 = {
        "passport_info": [
            {
                "passport_number": "",
                "given_name": "",
                "surname": "",
                "dateofbirth": "",
                "gender": "male / female",
                "place_of_birth": "",
                "place_of_issue": "",
                "date_of_issue": "",
                "date_of_expiry": ""
            }
        ]
    }

template3 = {
        "marriage_certificate_info": [
            {
                "bride_name": " ",
                "groom_name": " ",
                "marriage_date": " ",
                "registration_number": " ",
                "date_of_registration": " ",
                "place_of_issue": " "
            }
        ]
    }

template4 = {
        "academics_info": [
            {
                "qualification": " ",
                "course_name": " ",
                "institution_name": " ",
                "institution_country": " ",
                "passing_month": " ",
                "passing_year": " ",
                "grade": " ",
                "total_marks": " ",
                "obtained_marks": " "
            }
        ]
    }

template5 = {
        "transcript_certificate_info": [
            {
                "qualification": " ",
                "institution_name": " ",
                "institution_country": " ",
                "course_name": " ",
                "passing_month": " ",
                "passing_year": " ",
                "grade": " ",
                "total_marks": "",
                "obtained_marks": " "
            }
        ]
    }

template6 = {
        "insurance_info": [
            {
                "insurance_type": "",
                "provider_name": " ",
                "policy_no": " ",
                "policy_type": "//single or couple",
                "policy_startdate": " ",
                "policy_enddate": " ",
                "member_info": [
                    {
                        "member_name": " "
                    }
                ]
            }
        ]
    }

template7 = {
        "english_test_info": {
            "test_type": " ",
            "test_date": " ",
            "valid_until_date": " ",
            "registration_id": " ",
            "name": " ",
            "centre_number": " ",
            "country_of_residence": " ",
            "gender": "male / female",
            "overall_result": " ",
            "result": {
                "listening": " ",
                "reading": " ",
                "writing": " ",
                "speaking": " "
            }
        }
    }


template8 = {
        "australian_qualification_info": [
            {
                "provider": " ",
                "course": " ",
                "course_level": " ",
                "course_startdate": " ",
                "course_enddate": " ",
                "initial_tuition_fee": " ",
                "initial_non_tuition_fee": " ",
                "total_tuition_fee": " ",
                "given_name": " ",
                "oshc_provided_by_provider": " "
            }
        ]
    }

template9 = {
        "employment_history": [
            {
                "position": " ",
                "employer_name": " ",
                "country": " ",
                "joining_month": " ",
                "joining_year": " ",
                "resignation_month": " ",
                "resignation_year": " "
            }
        ]
    }

    
def upload_final_response_to_s3(local_file_path, bucket_name, job_id):
    try:
        # Define the S3 path (job_id/output/finalresponse.json)
        s3_path = f"{job_id}/output/primary_response.json"

        # Upload the file to S3
        s3.upload_file(local_file_path, bucket_name, s3_path)
        
        print(f"Successfully uploaded Final_response.json to s3://{bucket_name}/{s3_path}")
    except Exception as e:
        print(f"Error uploading to S3: {e}")
        
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
            
def file_exists_in_s3(bucket, key):
        try:
            s3.head_object(Bucket=bucket, Key=key)
            return True
        except s3.exceptions.ClientError:
            return False
            
def lambda_handler(event, context):
    bucket_name = "konze-processing-bucket"
    job_id = event['job_id']
    student = event['student']
    student = student.rstrip('/primary')
    #student = "Dhachainee"
    print("student",student)
    responses = {}
    local_dir = f"/tmp/{job_id}/primaryextract"
    local_dir_transcript = f"/tmp/{job_id}/primaryextract/transcript"
    clear_directory_files(local_dir)
    os.makedirs(local_dir_transcript, exist_ok=True)
    
    clear_directory_files(local_dir_transcript)
    os.makedirs(local_dir_transcript, exist_ok=True)

    # Download files from S3
    s3.download_file(bucket_name, f"{job_id}/embeddings/primary/index.faiss", f"/tmp/{job_id}/primaryextract/index.faiss")
    s3.download_file(bucket_name, f"{job_id}/embeddings/primary/index.pkl", f"/tmp/{job_id}/primaryextract/index.pkl")
    
    # Check and download transcript files if they exist
    if file_exists_in_s3(bucket_name, f"{job_id}/embeddings/primary/transcript_index.faiss"):
        s3.download_file(bucket_name, f"{job_id}/embeddings/primary/transcript_index.faiss", f"/tmp/{job_id}/primaryextract/transcript/index.faiss")
    
    if file_exists_in_s3(bucket_name, f"{job_id}/embeddings/primary/transcript_index.pkl"):
        s3.download_file(bucket_name, f"{job_id}/embeddings/primary/transcript_index.pkl", f"/tmp/{job_id}/primaryextract/transcript/index.pkl")
        faiss_index_transcript = FAISS.load_local(f"/tmp/{job_id}/primaryextract/transcript/", embeddings, allow_dangerous_deserialization=True)
        
    faiss_index = FAISS.load_local(f"/tmp/{job_id}/primaryextract/", embeddings, allow_dangerous_deserialization=True)
    # faiss_index_transcript = FAISS.load_local(f"/tmp/{job_id}/primaryextract/transcript/", embeddings, allow_dangerous_deserialization=True)
    
    date_formate = "IMPORTANT: write all date relevant information in yyyy-mm-dd formate"
    Strict_note = "IMPORTANT: If no document found then return the json with blank space only and no extra words in the start or the ending of the JSON keys"
    
#     primary_basic_prompt = f"""You are an expert document analyzer. IMPORTANT: Extract information of the primary applicant documents.
    
# INSTRUCTIONS:
# 1.The primary applicant is the main individual applying for the immigration process. This person: - Is referred to explicitly as the primary applicant in the application or documents. - Is responsible for initiating the application process. - Has their name, personal details, and qualifications as the focal point of the application.
# """
    
    prompt1 = f"""You are an Immigration Assistant tasked with extracting details of the {student} only."""

    prompt2 = f"""You are an Immigration Assistant tasked with extracting the {student}'s passport information based on the provided JSON schema. If the {student} has two passports, with the first passport's expiry date earlier than the second, extract and fill the details for both passports accordingly within the array."""

    prompt3 = f"""You are an expert assistant tasked with extracting {student}'s marriage certificate information based on the provided JSON schema."""

    prompt4 = f"""You are an Immigration Assistant tasked with extracting {student}'s qualification information based on the provided JSON schema. If the knowledge base contains more than one qualification, such as class 10th (SSC/Intermediate), class 12th (HSC), or university degrees, provide the information for each in the JSONs within the array. Do not include information about PTE, CoE, or any other small certificates."""

    prompt5 =  f"""You are an Immigration Assistant tasked with extracting {student}'s transcript information. Leave any missing information as a blank space " ". Return only the JSON with its values, without any additional statements."""

    prompt6 = f"""You are an Immigration Assistant tasked with extracting the insurance information or policy details for {student}. possible values of the insurance type can be Overseas Student Health Cover (OSHC) or OVHC"""

    prompt7 = f"""You are an Immigration Assistant tasked with extracting {student}'s English test information."""

    prompt8 = f"""
    You are an expert Immigration Assistant tasked with extracting {student}'s CoE (Confirmation of Enrolment) information. Do not refer any other qualitifcation other than COE

    IMPORTANT:
    1. If the Australian tuition fee starts with "Sau," interpret "S" as "$" and format as "$au <amount>" (e.g., "$au 5000").
    2. If the tuition fee is "0," return "$au 0."
    3. Apply similar rules for other currencies:
    - Australian: "$au"
    - US: "$us"
    - Brazilian: "$BZ"
    - Other currencies: "$<currency code>" 
    4. Do not consider visa documents for answering.
    5. Do not return any extra keywords at the start or at the end."""

    prompt9 = f"""You are an expert Immigration Assistant tasked with extracting {student}'s employment history"""

    appended_data = []
    responses = {}
    group1 = {}  # For templates 1-8
    # group2 = {}

    # Sample templates list (ensure templates are defined properly)
    templates = [
        template1, template2, template3, template4,
        template5, template6, template7, template8, template9
    ]
    prompts = [
        prompt1, prompt2, prompt3, prompt4, prompt5, prompt6,
        prompt7, prompt8, prompt9
    ]
    
    for idx, template in enumerate(templates):
        prompt = prompts[idx]
        document_chain = create_stuff_documents_chain(llm,prompt_template)
        if idx == 4:
            retriever = faiss_index_transcript.as_retriever(search_kwargs={"k":18})
        else :
            retriever = faiss_index.as_retriever(search_kwargs={"k":18})
        retrieval_chain = create_retrieval_chain(retriever, document_chain)
        data_json_str = json.dumps(template, indent=2)
        response1 = retrieval_chain.invoke({"input": f"Understand and fill the answer for this {data_json_str}.and follow this instruction{prompt}.{date_formate}.IMPORTANT : Do not return anything extra than the JSON at the start or the ending of JSON , even if you dont find the answer then return JSON as it is without anything extra keywords"})
        data = response1["answer"]
        # print("data",data)
        
        if isinstance(data, str):
            try:
                data = json.loads(data) # Convert JSON string to a Python dictionary
            except json.JSONDecodeError:
                print("Error parsing JSON, data remains as a string",data)
                
        if isinstance(data, dict):
            for key, value in data.items():
                # If value is a list, add individual items to the dictionary under the same key
                if isinstance(value, list):
                    group_data = []
                    for item in value:
                        group_data.append(item)  # Append list items to the group dictionary
                        print("group data",group_data)
                    if idx < 9:  # Templates 1-8
                        group1[key] = group_data
                        print("group 1",group1[key])
                    else:  # Templates 9-16
                        group2[key] = group_data
                else:
                    if idx < 9:  # Templates 1-8
                        group1[key] = value
                    else:  # Templates 9-16
                        group2[key] = value

    # final_templates = [group1, group2]
    local_file_path = f"/tmp/{job_id}/primaryextract/primary_response.json"
    with open(local_file_path, 'w') as f:
        json.dump(group1, f, indent=4)
        
    test = json.dumps(group1, indent=4)
    # Upload final response to S3
    upload_final_response_to_s3(local_file_path, bucket_name, job_id)

    # Update status in SSM Parameter Store
    ssm_client.put_parameter(
        Name=job_id,
        Value="Extraction completed",
        Type='String',
        Overwrite=True,
    )

    clear_directory_files(local_dir)
    clear_directory_files(local_dir_transcript)

    # Return response
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "*",
        },
        "body": json.dumps(responses),
    }
