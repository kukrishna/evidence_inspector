import pdb

import argparse
import torch.nn.functional
from transformers import AutoTokenizer, AutoModelForCausalLM
import numpy as np
from copy import deepcopy
from bottle import Bottle, request, response, run, static_file

import json
from transformers import BitsAndBytesConfig


def make_prompt(dp):
    PROMPT_STR = "Based on information from the given document only, answer the question that follows in full sentences."
    input_string = f"{PROMPT_STR} DOCUMENT:"
    for _i,sent in enumerate(dp["input_lines"]):
        input_string = f"{input_string} {sent}"
    input_string = f"{input_string} QUESTION: {dp['question']} ANSWER:"
    dp["input_string"] = input_string

    return dp


def predict_generation(dp, model: AutoModelForCausalLM, tokenizer, nbeams, max_input_len, max_decode_len):
    inputs = tokenizer(dp["input_string"], return_tensors="pt", truncation=True, max_length=max_input_len)
    input_ids = inputs.input_ids.to(model.device)
    attention_mask = inputs.attention_mask.to(model.device)

    # pdb.set_trace()

    gen_output = model.generate(inputs=input_ids,
                                attention_mask = attention_mask,
                                return_dict_in_generate=True,
                                output_scores=False,
                                max_length=input_ids.shape[-1]+max_decode_len,          # have to set again :( cant read from saved model
                                num_beams=nbeams)
    gen_tokids = gen_output["sequences"][0]

    old_numtoks = input_ids.shape[-1]
    gen_tokids = gen_tokids[old_numtoks:]



    # pdb.set_trace()

    if gen_tokids[-1].item()==tokenizer.eos_token_id:
        gen_tokids = gen_tokids[:-1]

    gen_string = tokenizer.decode(gen_tokids)
    print(gen_string)
    dp["prediction"] = gen_string




if __name__=="__main__":

    np.random.seed(1337)

    parser = argparse.ArgumentParser()
    parser.add_argument("--model-name", type=str, required=True)
    parser.add_argument("--port", type=int, default=9003)
    parser.add_argument("--quantize", type=str, default="16bit")
    parser.add_argument("--max-input-len", type=int, default=5000)
    parser.add_argument("--max-decode-len", type=int, default=150)
    args = parser.parse_args()

    model_name = args.model_name
    port = args.port
    quantize = args.quantize
    max_input_len = args.max_input_len
    max_decode_len = args.max_decode_len


    tokenizer = AutoTokenizer.from_pretrained(
        model_name,
        use_fast=False, #todo: enable this?
        trust_remote_code=True
    )

    if tokenizer.pad_token==None:
        tokenizer.pad_token = tokenizer.eos_token


    if quantize=="4bit":
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16
        )

        model = AutoModelForCausalLM.from_pretrained(
            model_name,
            trust_remote_code=True,
            quantization_config=bnb_config,
        )

    elif quantize=="8bit":
        bnb_config = BitsAndBytesConfig(
            load_in_8bit=True,
            # bnb_4bit_use_double_quant=True,
            # bnb_4bit_quant_type="nf4",
            # bnb_4bit_compute_dtype=torch.bfloat16
        )

        model = AutoModelForCausalLM.from_pretrained(
            model_name,
            trust_remote_code=True,
            quantization_config=bnb_config,
        )



    elif quantize=="16bit":
        print("USING 16BIT INFERENCE")
        model = AutoModelForCausalLM.from_pretrained(
            model_name,
            trust_remote_code=True,
            torch_dtype=torch.bfloat16
        ).cuda()

    else:
        print("quanitzation type ", quantize, "not supported!")
        raise NotImplementedError


    # good for making generation fast
    model.config.use_cache=True

    predict_generation({"input_string":"The capital of Pennsylvania is"}, model, tokenizer, 1, 9999, 5)


    app = Bottle()


    @app.hook('after_request')
    def enable_cors():
        """
        You need to add some headers to each request.
        Don't use the wildcard '*' for Access-Control-Allow-Origin in production.
        """
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'PUT, GET, POST, DELETE, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Origin, Accept, Content-Type, X-Requested-With, X-CSRF-Token'


    @app.route("/get_config", method=['GET'])
    def get_config():
        return  {
            "model_name_or_path": model_name,
            "max_input_len": max_input_len,
            "max_decode_len": max_decode_len,
            "precision": quantize,
            "beam_width": nbeams
        }


    @app.route('/predict', method=['POST'])
    def predict():
        dp = request.json
        # pdb.set_trace()
        task = dp["task"]

        newdp = make_prompt(dp)

        predict_generation(newdp, model=model, tokenizer=tokenizer, nbeams=nbeams, max_input_len=max_input_len, max_decode_len=max_decode_len)

        # at this point the newdp are updated in place with results

        if "prediction" not in newdp:
            return {"result": None, "success": False}

        return {"result": newdp["prediction"], "success": True}


    run(app, host="localhost", port=args.port, debug=True)
