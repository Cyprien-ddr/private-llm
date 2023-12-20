#!/usr/bin/env python3
import glob
import sys
from typing import Union, Any, List
import os
import transformers
import numpy as np

from langchain import HuggingFacePipeline
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer
from langchain.document_loaders import UnstructuredFileLoader, UnstructuredExcelLoader, UnstructuredWordDocumentLoader, UnstructuredPowerPointLoader
from langchain.text_splitter import CharacterTextSplitter
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.prompts import ChatPromptTemplate
from langchain.schema.output_parser import StrOutputParser
from langchain.vectorstores import FAISS
from langchain.embeddings import HuggingFaceEmbeddings
from langchain.schema.runnable import RunnablePassthrough
sys.path.append(os.path.abspath(os.path.dirname(__file__) + "/../"))
from ipa_libs.config import configs

os.environ["HF_AUTH"] = configs["hugging_face"]["token"]
os.environ["LANGCHAIN_TRACING_V2"] = configs["langsmith"]['tracing_v2']
os.environ["LANGCHAIN_ENDPOINT"] = configs["langsmith"]['endpoint']
os.environ["LANGCHAIN_API_KEY"] = configs["langsmith"]['api_key']
os.environ["LANGCHAIN_PROJECT"] = configs["langsmith"]['project']

comments = []

def init_bnb_config(
        load_in_4bit: bool = True,
        bnb_4bit_quant_type: str = 'nf4',
        bnb_4bit_use_double_quant: bool = True,
        bnb_4bit_compute_dtype: Union[type, str] = 'bfloat16',
) -> transformers.BitsAndBytesConfig:
    """
    Initializes a configuration object for the BitsAndBytes model from the Transformers library.

    :param load_in_4bit: boolean value indicating whether to load in 4-bit
    :param bnb_4bit_quant_type: the quantization type for 4-bit
    :param bnb_4bit_use_double_quant: boolean value indicating whether to use double quantization for 4-bit
    :param bnb_4bit_compute_dtype: the compute dtype for 4-bit
    :return: the initialized BitsAndBytesConfig object
    """
    if not isinstance(load_in_4bit, bool):
        raise ValueError("load_in_4bit must be a boolean value.")
    if not isinstance(bnb_4bit_quant_type, str):
        raise ValueError("bnb_4bit_quant_type must be a string.")
    if not isinstance(bnb_4bit_use_double_quant, bool):
        raise ValueError("bnb_4bit_use_double_quant must be a boolean value.")
    if not isinstance(bnb_4bit_compute_dtype, (type, str)):
        raise ValueError("bnb_4bit_compute_dtype must be a valid data type.")

    bnb_config = transformers.BitsAndBytesConfig(
        load_in_4bit=load_in_4bit,
        bnb_4bit_quant_type=bnb_4bit_quant_type,
        bnb_4bit_use_double_quant=bnb_4bit_use_double_quant,
        bnb_4bit_compute_dtype=bnb_4bit_compute_dtype
    )
    return bnb_config

def list_layers(model):
    for name, param in model.named_parameters():
        print(name)
        
def init_model(
        bnb_config: transformers.BitsAndBytesConfig,
        model_id: str = 'meta-llama/Llama-2-13b-chat-hf',
) -> HuggingFacePipeline:
    """
    This code defines a function named init_model that initializes a HuggingFace pipeline for text generation using a pre-trained language model.
    The function loads the model and tokenizer from the HuggingFace model hub, configures the model for quantization, and sets up the text generation pipeline.

    :param model_id: The ID of the model to be used.
    :param bnb_config: The configuration for BitsAndBytes.
    :return: The initialized HuggingFacePipeline.
    """
    hf_auth = os.environ.get('HF_AUTH')
    model_config = transformers.AutoConfig.from_pretrained(
        model_id,
        use_auth_token=hf_auth
    )

    model = transformers.AutoModelForCausalLM.from_pretrained(
        model_id,
        trust_remote_code=True,
        config=model_config,
        quantization_config=bnb_config,
        device_map='auto', # O signifie que l'accélérateur passera tout les calculs au GPU indice 0, auto signifie qu'il déterminera tout seul pour chaque layer quel unité de calcul utiliser (gpu ou cpu)
        use_auth_token=hf_auth
    )
    #list_layers(model)
    model.eval()

    tokenizer = transformers.AutoTokenizer.from_pretrained(
        model_id,
        use_auth_token=hf_auth
    )

    generate_text = transformers.pipeline(
        model=model,
        tokenizer=tokenizer,
        return_full_text=True,
        task='text-generation',
        temperature=0.01,
        max_new_tokens=512,
        repetition_penalty=1.1,
        do_sample=True,
    )

    llm = HuggingFacePipeline(pipeline=generate_text)
    return llm


def user_documents(directory: str) -> list[Any]:
    """
    The user_documents function takes a directory path as input and returns a list of documents.
    It searches for PDF, DOCX, DOC, and TXT files in the specified directory and loads the contents of these files using different loaders.
    The function then splits the loaded documents into smaller chunks using a text splitter and returns the chunked documents.

    :param directory: A string representing the path to the directory containing the documents.
    :return: A list of documents that have been split into smaller chunks.
    """
    documents = []

    loaders = {
        '.pdf': UnstructuredFileLoader,
        '.docx': UnstructuredWordDocumentLoader,
        '.doc': UnstructuredWordDocumentLoader,
        '.txt': UnstructuredFileLoader,
        '.xlsx': UnstructuredExcelLoader,
        '.pptx': UnstructuredPowerPointLoader,
        '.ppt': UnstructuredPowerPointLoader,
        '.md': UnstructuredFileLoader,
        '.csv': UnstructuredFileLoader,
    }

    file_extensions = ['.pdf', '.docx', '.doc', '.txt', '.xlsx', '.pptx', '.ppt', '.md', '.csv']
    files = []
    for extension in file_extensions:
        files.extend(glob.glob(os.path.join(directory, '*' + extension)))

    for file in files:
        file_extension = os.path.splitext(file)[1]
        if file_extension in loaders:
            loader = loaders[file_extension](file)
            documents.extend(loader.load())

    text_splitter = CharacterTextSplitter(chunk_size=2000,
                                          chunk_overlap=30, separator="\n")
    chunked_documents = text_splitter.split_documents(documents=documents)

    if len(documents) == 0:
        raise Exception(
            "Aucun contenu n'a pu être extrait de tous les documents fournis.")
    else:
        for doc in documents:
            if doc.page_content == '':
              if not 'page' in doc.metadata:
                  page = '0'
              else:
                  page = str(doc.metadata['page'])
              comments.append('Pas de contenu extrait de la page ' + page + ' du document ' + doc.metadata['source'])

    return chunked_documents

# (1) Fonction non utilisée, conservée en vue de tests éventuels de remplacement du chunk actuel CharacterTextSplitter
def split_docs(docs):
    rec_text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=0,
        separators=["\n\n", "\n", "."]
    )

    chunks = [text for data in docs for text in rec_text_splitter.split_text(data.page_content)]

    return chunks


def pre_rerank(docs: List[Any], question: str) -> List[List[str]]:
    """
    Pre-reranks the documents based on the given question.

    :param docs: The list of documents to be pre-reranked.
    :param question: The question to be used for pre-reranking.
    :return: A list of lists containing the question and the page content for each document.
    """
    contents = [[question, data.page_content] for data in docs]
    return contents


def rerank(contents: list[list[str]]):
    tokenizer = AutoTokenizer.from_pretrained('BAAI/bge-reranker-large')
    model = AutoModelForSequenceClassification.from_pretrained('BAAI/bge-reranker-large')
    model.eval()

    with torch.no_grad():
        inputs = tokenizer(contents, padding=True, truncation=True, return_tensors='pt', max_length=512)
        scores = model(**inputs, return_dict=True).logits.view(-1, ).float()

    scores = scores.tolist()

    sorted_indices = np.argsort(scores)

    top3_indices = sorted_indices[-3:][::-1]

    context = ""
    for index in top3_indices:
        context += str(contents[index][1])

    return context


def llm(question: str, data_base, model):

    docs = data_base.similarity_search(question, k=25)
    contents = pre_rerank(docs, question)

    context = rerank(contents)

    template = """Answer the question based only on the context,\n """ + context + """ 
        
        Question: """ + question + """ 
        Answer in French:
        """
    prompt = ChatPromptTemplate.from_template(template)
    chain = (
            {"question": RunnablePassthrough()}
            | prompt
            | model
            | StrOutputParser()
    )
    return chain.invoke(question)


def query(query, docs_path):
      try:
        model = init_model(init_bnb_config())
        embeddings = HuggingFaceEmbeddings(model_name='sentence-transformers/all-MiniLM-L6-v2')
        docs = user_documents(docs_path)
        # voir commentaire (1) 
        # docs = split_docs(docs)
        db = FAISS.from_documents(docs, embeddings)
        return llm(query, db, model), '\n'.join(comments)
      except Exception as error:
        return f'Erreur du LLM : {error}', '\n'.join(comments)


if __name__ == "__main__":
    model = init_model(init_bnb_config())
    embeddings = HuggingFaceEmbeddings(model_name='sentence-transformers/all-MiniLM-L6-v2')
    docs = user_documents(input("Enter the path to the documents dir"))
    # voir commentaire (1) 
    # docs = split_docs(docs)
    db = FAISS.from_documents(docs, embeddings)
    query = input("Type in your query (type 'exit' to quit):\n")
    while query != "exit":
        result = llm(query, db, model)
        print(result)
        query = input("Type in your query (type 'exit' to quit):\n")
