# some code taken from https://github.com/allenai/allennlp-server/blob/master/allennlp_server/commands/server_simple.py
import pdb

import requests
import time
import json

# defining the api-endpoint
EVEXT_WITH_FIXFACTUALITY_ENDPOINT = "http://localhost:9922/predict"
BACKEND_CONFIG_ENDPOINT = "http://localhost:9922/get_config"
QA_ENDPOINT = f"http://localhost:9003/predict"


def get_evidence_extraction_with_fixfactuality(input_dict):
    input_dict["task"] = "evidence_extraction_with_fixfactuality"
    r = requests.post(url=EVEXT_WITH_FIXFACTUALITY_ENDPOINT, json=input_dict)
    response = r.text
    output_obj = json.loads(response)["result"]
    return output_obj

def get_backend_config():
    r = requests.get(url=BACKEND_CONFIG_ENDPOINT)
    response = r.text
    output_obj = json.loads(response)
    return output_obj

def get_generic_qa(input_dict):
    input_dict["task"] = "qa"
    r = requests.post(url=QA_ENDPOINT, json=input_dict)
    response = r.text
    output_obj = json.loads(response)["result"]
    return output_obj
