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


# prompt_template = ChatPromptTemplate.from_template("""Please fill in the missing details in the following information::
# <context>
# {context}
# </context>
# Question: {input}""")


prompt_template = ChatPromptTemplate.from_template("""Please fill in the missing details in the following information::

<context>
{context}
</context>

<instructions>
- Focus only on the secondary applicant details. Skip any mention of primary applicants.
- Ensure the extracted values match the keys provided in the schema.
- If a value is missing in the document, set it as a blank space " ".
- Do not include unnecessary characters or titles (e.g., "Mr.", "Ms.") unless explicitly stated as part of the name.
- Write all date-relevant information in yyyy-mm-dd format.
- For the gender field, ensure it only returns "male" or "female"; do not return abbreviated forms like "m" or "f".
- only return what is asked without any extra words
- Return only the JSON.
- Important : If values cannot be found, return the JSON as it is without anything extra at the start or end.
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
        "applicant_info": [
            {
                "applicant_type": "secondary ",
                "firstname": " ",
                "middlename": " ",
                "lastname": " ",
                "gender": "male / female",
                "dateofbirth": " ",
                "contact_information_info": {
                    "address": {
                        "address": " ",
                        "city": " ",
                        "zipcode": " ",
                        "state": " ",
                        "country": " "
                    }
                }
            }
        ]
    }   


template2 = {
        "passport_info": [
            {
                "passport_number": "",
                "given_name": " ",
                "surname": " ",
                "dateofbirth": " ",
                "gender": "male / female",
                "place_of_birth": " ",
                "place_of_issue": " ",
                "date_of_issue": " ",
                "date_of_expiry": " "
            }
        ]
    }


template3 = {
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

template4 = {
        "transcript_certificate_info": [
            {
                "qualification": " ",
                "institution_name": " ",
                "institution_country": " ",
                "course_name": " ",
                "passing_month": " ",
                "passing_year": " ",
                "grade": " ",
                "total_marks": " ",
                "obtained_marks": " "
            }
        ]
    }

template5 = {
        "insurance_info": [
            {
                "insurance_type": " ",
                "provider_name": " ",
                "policy_no": " ",
                "policy_type": " ",
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


template6 = {
        "english_test_info": [
            {
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
        ]
    }

template7 = {
        "australian_qualification_info": {
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
    }


template8 = {
        "employment_history": [
            {
                "position": " ",
                "employer_name": " ",
                "country": " ",
                "joining-month": " ",
                "joining-year": " ",
                "resignation-month": " ",
                "resignation-year": " "
            }
        ]
    }


    
def upload_final_response_to_s3(local_file_path, bucket_name, job_id):
    try:
        # Define the S3 path (job_id/output/finalresponse.json)
        s3_path = f"{job_id}/output/secondary_response.json"

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
            
def lambda_handler(event, context):
    bucket_name = "konze-processing-bucket"
    job_id = event['job_id']
    student = event['student']
    student = student.rstrip('/secondary')
    #student = "Dhachainee"
    print("student",student)
    responses = {}
    local_dir = f"/tmp/{job_id}/secondextract"
    clear_directory_files(local_dir)
    os.makedirs(local_dir, exist_ok=True)

    # Download files from S3
    s3.download_file(bucket_name, f"{job_id}/embeddings/secondary/index.faiss", f"/tmp/{job_id}/secondextract/index.faiss")
    s3.download_file(bucket_name, f"{job_id}/embeddings/secondary/index.pkl", f"/tmp/{job_id}/secondextract/index.pkl")
    
    faiss_index = FAISS.load_local(f"/tmp/{job_id}/secondextract", embeddings, allow_dangerous_deserialization=True)
    
    date_formate = "IMPORTANT: write all date relevant information in yyyy-mm-dd formate"
    Strict_note = "IMPORTANT: If no document found then return the json with blank space only and no extra words in the start or the ending of the JSON keys"


    secondary_basic_prompt = f"""You are an expert document analyzer. IMPORTANT: Extract information of the secondary applicant documents .EXCEPT {student}.
    
INSTRUCTIONS:
1.The secondary applicant is any individual listed in the application other than the primary applicant, {student}. A secondary applicant: - Has their own set of independent documents like their own passport, academic records, etc.. - Is not marked as a dependent, witness, or reference. - Must have verifiable information distinct from {student}.
2. If a person is only mentioned in {student} documents but has no separate documents, DO NOT include them.
3. IMPORTANT: If any chance you cannot find the value of a key, keep only blank space  " " for any missing information. 
4. Return data ONLY in the specified JSON format
"""
    
    prompt1 = f"""{secondary_basic_prompt} IMPORTANT: Identify and extract information ONLY for the secondary applicant, who is NOT {student}. Ensure the extracted information pertains SOLELY to the secondary applicant's independent documents. DO NOT INCLUDE any details related to {student}, dependent, witness, etc . even if found in overlapping contexts or mixed documents."""

    prompt2 = f"""{secondary_basic_prompt} Note: Extract passport details for the secondary applicant ONLY. If the secondary applicant does not have passport details, leave the response blank. IMPORTANT: Verify that NO data related to {student} is included in the response."""

    prompt3 = f"""{secondary_basic_prompt} If the knowledge base contains more than one qualification, such as class 10th (SSC/Intermediate), class 12th (HSC), or university degrees, provide the information for each in the JSONs within the array for secodary applicants . DO NOT INCLUDE any information or qualifications of {student}, even if overlapping in documents."""

    prompt4 = f"""{secondary_basic_prompt} Extract transcript information ONLY if the word 'transcript' is explicitly mentioned on the document. Ensure the information is related to the secondary applicant ONLY. DO NOT INCLUDE any transcript information related to {student}."""

    prompt5 = f"""{secondary_basic_prompt} Extract insurance information for the secondary applicant ONLY if it is explicitly stated and does not belong to {student}. Policy type can be single or couple. IMPORTANT: Verify that NO insurance information related to {student} is included in the response."""

    prompt6 = f"""{secondary_basic_prompt} Identify English test information for the secondary applicant ONLY. If the information pertains to {student}, exclude it. Return the details in `english_test_info` ONLY if it belongs to the secondary applicant."""

    prompt7 = f"""
    You are an expert Immigration Assistant tasked with extracting secondary applicants CoE (Confirmation of Enrolment) information. Do not refer any other qualitifcation other than COE

    IMPORTANT:
    1. If the Australian tuition fee starts with "Sau," interpret "S" as "$" and format as "$au <amount>" (e.g., "$au 5000").
    2. If the tuition fee is "0," return "$au 0."
    3. Apply similar rules for other currencies:
    - Australian: "$au"
    - US: "$us"
    - Brazilian: "$BZ"
    - Other currencies: "$<currency code>" 
    4. Do not consider visa documents for answering.
    5. Do not return any extra keywords at the start or at the end. """

    prompt8 = f"""{secondary_basic_prompt} IMPORTANT: Retrieve information ONLY from the secondary applicant's experience letter. Verify and ensure the extracted data does not belong to {student}. If the data overlaps with {student}, DO NOT INCLUDE it in the response."""
    
    appended_data = []
    responses = {}
    group1 = {}  # For templates 1-8
    group2 = {}

    # Sample templates list (ensure templates are defined properly)
    templates = [
        template1, template2, template3, template4,
        template5, template6, template7, template8
    ]
    prompts = [
        prompt1, prompt2, prompt3, prompt4, prompt5, prompt6,
        prompt7, prompt8
    ]
    
    for idx, template in enumerate(templates):
        # print("%",template)
        prompt = prompts[idx]
        document_chain = create_stuff_documents_chain(llm,prompt_template)
        retriever = faiss_index.as_retriever(search_kwargs={"k":18})
        retrieval_chain = create_retrieval_chain(retriever, document_chain)
        data_json_str = json.dumps(template, indent=2)
        response1 = retrieval_chain.invoke({"input": f"Understand and fill the answer for this {data_json_str}.and follow this instruction{prompt}.{date_formate}.Do not return anything extra than the JSON at the start or the ending of JSON , even if you dont find the answer then return JSON as it is without anything extra.striclty do no attach any extra keywords to the given JSON"})
        data = response1["answer"]
        
        if isinstance(data, str):
            try:
                data = json.loads(data)  # Convert JSON string to a Python dictionary
            except json.JSONDecodeError:
                print("Error parsing JSON, data remains as a string",data)
                
        if isinstance(data, dict):
            for key, value in data.items():
                # If value is a list, add individual items to the dictionary under the same key
                if isinstance(value, list):
                    group_data = []
                    for item in value:
                        group_data.append(item)  # Append list items to the group dictionary
                    if idx < 9:  # Templates 1-8
                        group1[key] = group_data
                    else:  # Templates 9-16
                        group2[key] = group_data
                else:
                    if idx < 9:  # Templates 1-8
                        group1[key] = value
                    else:  # Templates 9-16
                        group2[key] = value

    # final_templates = [group1, group2]
    
    local_file_path = f"/tmp/{job_id}/secondextract/secondary_response.json"
    with open(local_file_path, 'w') as f:
        json.dump(group1, f, indent=4)

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
