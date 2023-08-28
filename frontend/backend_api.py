# some code taken from https://github.com/allenai/allennlp-server/blob/master/allennlp_server/commands/server_simple.py
import pdb

import requests
import time
import json

# defining the api-endpoint
EVEXT_WITH_FIXFACTUALITY_ENDPOINT = "http://localhost:9922"
QA_ENDPOINT = f"http://localhost:9003"

def get_evidence_extraction_with_fixfactuality(input_dict):
    input_dict["task"] = "evidence_extraction_with_fixfactuality"
    r = requests.post(url=f"{EVEXT_WITH_FIXFACTUALITY_ENDPOINT}/predict", json=input_dict)
    response = r.text
    output_obj = json.loads(response)["result"]
    return output_obj

def get_backend_config(type):
    if type=="factcheck_model":
        DEST_ENDPOINT = EVEXT_WITH_FIXFACTUALITY_ENDPOINT
    elif type=="qa_model":
        DEST_ENDPOINT = QA_ENDPOINT
    else:
        raise NotImplementedError

    r = requests.get(url=f"{DEST_ENDPOINT}/get_config")
    response = r.text
    output_obj = json.loads(response)
    return output_obj

def get_generic_qa(input_dict):
    input_dict["task"] = "qa"
    r = requests.post(url=f"{QA_ENDPOINT}/predict", json=input_dict)
    response = r.text
    output_obj = json.loads(response)["result"]
    return output_obj
