import argparse
import os

from collections import defaultdict

import json

import requests
from bottle import Bottle, request, response, run, static_file
import bottle
import difflib
from nltk.tokenize import TreebankWordTokenizer as twt
from paste import httpserver

import time


from backend_api import get_evidence_extraction_with_fixfactuality
from backend_api import get_backend_config
from backend_api import get_generic_qa

from get_example import ArticleGetter
from transformers import AutoTokenizer

import spacy
nlp = spacy.load("en_core_web_md")

bottle.BaseRequest.MEMFILE_MAX = 10240000

parser = argparse.ArgumentParser(description='frontend server')

parser.add_argument(
    '--port',
    dest='port',
    help='port',
    type=int,
    default=5682
)

args = parser.parse_args()

web_root = f"webroot_v8/"

save_output_path = "../datasets/examples/saved"


def process_evidence_extraction_with_fixfactuality(dp):
    PROMPT_STR = "For the given document and claim sentence, find all document sentences providing evidence for claim, and then revise the claim to remove or replace unsupported facts."
    input_string = f"{PROMPT_STR} DOCUMENT:"
    for _i,sent in enumerate(dp["input_lines"]):
        input_string = f"{input_string} SENT{_i} {sent}"
    input_string = f"{input_string} CLAIM: {dp['before_summary_sent']}"

    output_string = f"EVIDENCE:"
    for ev_idx in dp["evidence_labels"]:
        output_string = f"{output_string} SENT{ev_idx}"
    output_string = f"{output_string} REVISION: {dp['after_summary_sent']}"

    dp["input_string"] = input_string
    dp["output_string"] = output_string

    return dp

def showdiff(fr, to):
    differ = difflib.Differ()

    fr_wordspans = list(twt().span_tokenize(fr))
    to_wordspans = list(twt().span_tokenize(to))

    fr_words = []
    last_endpos = 0
    for onespan in fr_wordspans:
        fr_words.append(fr[last_endpos:onespan[1]])
        last_endpos = onespan[1]

    to_words = []
    last_endpos = 0
    for onespan in to_wordspans:
        to_words.append(to[last_endpos:onespan[1]])
        last_endpos = onespan[1]


    line = ""
    deleteonly_line = ""
    normal_spans = []
    deleted_spans = []
    added_spans = []
    deleteonly_spans = []
    addonly_insertionmap = defaultdict(str)

    entries = list(differ.compare(fr_words, to_words))

    entries = [e for e in entries if e[0]!="?"]

    # this loop rearranges words in the diff such that the additions come after deletions
    # this loop is guaranteed to terminate because at each iteration, we either advance one + over - (like checkers) or exit the subroutine
    # since there are limited number of -s that can be hopped over, we will terminate
    # time complexity is O(n^2) but modern computers are fast enough for this
    while True:
        swapped_something = False
        for i in range(len(entries)-1):
            if entries[i][0]=="+" and entries[i+1][0]=="-":
                #swap
                temp = entries[i]
                entries[i] = entries[i+1]
                entries[i+1] = temp
                swapped_something = True
                break
        if not swapped_something:
            break

    for entry in entries:
        if entry[0]=="+":
            text = entry[2:]
            start_idx = len(line)
            end_index = start_idx+len(text)

            # this means we are at the start of a potentially multi-word addition
            if len(deleted_spans)>0:
                if deleted_spans[-1][1]==start_idx:
                    addonly_insertionmap[deleteonly_spans[-1][1]] += text

            # this means we are at word_idx>=1 of a multi-word addition. so just expand the last addition.
            if len(added_spans)>0:
                if added_spans[-1][1]==start_idx:
                    addonly_insertionmap[deleteonly_spans[-1][1]] += text
            else:
                pass

            added_spans.append((start_idx, end_index))
            line+=text



        elif entry[0]=="-":
            text = entry[2:]
            start_idx = len(line)
            end_index = start_idx+len(text)
            deleted_spans.append((start_idx, end_index))
            line+=text

            start_idx = len(deleteonly_line)
            end_index = start_idx+len(text)
            deleteonly_spans.append((start_idx, end_index))
            deleteonly_line+=text

        else:
            text = entry[2:]
            start_idx = len(line)
            end_index = start_idx+len(text)
            normal_spans.append((start_idx, end_index))
            line+=text

            start_idx = len(deleteonly_line)
            end_index = start_idx+len(text)
            deleteonly_line+=text

    return {
        "line": line,
        "normal_spans": normal_spans,
        "deleted_spans": deleted_spans,
        "added_spans": added_spans,
        "deleteonly_line": deleteonly_line,
        "deleteonly_spans": deleteonly_spans,
        "addonly_insertionmap": addonly_insertionmap
    }


if __name__ == "__main__":
    article_getter = ArticleGetter()
    app = Bottle()

    while True:
        try:
            factcheck_backend_config = get_backend_config("factcheck_model")
            print("Contact established with backend! proceeding...")
            break
        except requests.exceptions.ConnectionError:
            print("Waiting for backend to start. Will ping again in 5 seconds...")
            time.sleep(5)

    qa_backend_config = None
    try:
        qa_backend_config = get_backend_config("qa_model")
    except requests.exceptions.ConnectionError:
        print("QA model unreachable. Starting without it...")


    tokenizer_name_or_path = factcheck_backend_config["tokenizer_name_or_path"]
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_name_or_path)

    @app.hook('after_request')
    def enable_cors():
        """
        You need to add some headers to each request.
        Don't use the wildcard '*' for Access-Control-Allow-Origin in production.
        """
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'PUT, GET, POST, DELETE, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Origin, Accept, Content-Type, X-Requested-With, X-CSRF-Token'


    @app.route('/')
    def serve_job():
        html_str = open(os.path.join(web_root,"index.html")).read()
        return html_str

    @app.route('/get_config', method=['GET'])
    def get_config():
        return {
            "factcheck_model": factcheck_backend_config,
            "qa_model": qa_backend_config
        }

    @app.route('/get_all_ids', method=['GET'])
    def get_all_ids():
        output = [{"label": x, "val":j} for (j,x) in enumerate(article_getter.get_all_ids())]
        return {"all_ids": output}

    @app.route('/static/<filename:path>')
    def send_static(filename):
        return static_file(filename, root=web_root)


    @app.route('/get_example/<jobid>')
    def get_intial_conversation(jobid):
        jobid = int(jobid)
        one_dp = article_getter.get_article(jobid)

        return_obj_formatted = {}
        return_obj_formatted["job_id"] = one_dp["id"]
        return_obj_formatted["input_lines"] = one_dp["input_lines"]
        return_obj_formatted["output_lines"] = one_dp["output_lines"]

        for i in range(len(return_obj_formatted["input_lines"])):
            return_obj_formatted["input_lines"][i] = return_obj_formatted["input_lines"][i].strip()

        for i in range(len(return_obj_formatted["output_lines"])):
            return_obj_formatted["output_lines"][i] = return_obj_formatted["output_lines"][i].strip()

        if "question" in one_dp:
            return_obj_formatted["question"] = one_dp["question"]

        return return_obj_formatted


    @app.route('/get_qa', method=['POST'])
    def get_qa():
        bundle = request.forms.get("bundle")
        bytes_string = bytes(bundle, encoding="raw_unicode_escape")
        bundle = bytes_string.decode("utf-8", "strict")
        bundle = json.loads(bundle)

        article_lines = bundle["article_lines"]
        question = bundle["question"]
        article_lines = [x["txt"] for x in article_lines]

        try:
            qa_output = get_generic_qa({
                  'input_lines': article_lines,
                  'question': question,
                  'id': 'xxxxx',
                })
        except requests.exceptions.ConnectionError:
            return {"success": False, "reason": "QA model not reachable..."}

        qa_output = qa_output.replace("\n", " ").strip()
        doc = nlp(qa_output)
        sents = [str(s) for s in doc.sents]

        return {"success": True, "prediction": sents}

    @app.route('/get_ev_with_fixfactuality', method=['POST'])
    def get_factuality():
        bundle = request.forms.get("bundle")
        bytes_string = bytes(bundle, encoding="raw_unicode_escape")
        bundle = bytes_string.decode("utf-8", "strict")
        bundle = json.loads(bundle)

        article_lines = bundle["article_lines"]
        summary_line = bundle["summary_line"]

        num_frontspaces = len(summary_line)-len(summary_line.lstrip())
        summary_line = summary_line.strip()

        article_lines = [x["txt"] for x in article_lines]

        ev_fixfactuality_output = get_evidence_extraction_with_fixfactuality({
              'input_lines': article_lines,
              'before_summary_sent': summary_line,
              'after_summary_sent': "dummmy",
              'id': 'xxxxx',
              'evidence_labels': [0]
            })

        output = ev_fixfactuality_output["prediction"]

        fixed_output = output.split("REVISION:")[1].strip()
        ev_sentids = output.split("REVISION:")[0].split("EVIDENCE: ")[1].strip()

        print("BEFORE:", summary_line)
        print("AFTER:", fixed_output)

        ev_labels = []
        for one_sentid in ev_sentids.split(" "):
            this_idx = one_sentid.split("SENT")[-1]
            ev_labels.append(int(this_idx))

        diff_bw_two = showdiff(fr=summary_line, to=fixed_output)
        todelete_spans = diff_bw_two["deleteonly_spans"]
        addonly_insertionmap = diff_bw_two["addonly_insertionmap"]

        # converting from tuples to list to modify
        todelete_spans = [list(x) for x in todelete_spans]

        replacement_strings = []
        for onespan in todelete_spans:
            endpos = onespan[-1]
            if endpos in addonly_insertionmap:
                replacement_strings.append(addonly_insertionmap[endpos])
            else:
                replacement_strings.append("")


        # filter the replacements to disallow certain ones that are problematic (e.g. unks, only spaces)
        filtered_todelete_spans = []
        filtered_replacement_strings = []
        for (onespan, repstr) in zip(todelete_spans, replacement_strings):
            # if unk then skip
            if "<unk>" in repstr:
                print("FILTER ALERT: skipped replacement of ", repstr)
                continue

            # if the difference is only whitespace then skip
            l,r = onespan
            before_str = summary_line[l:r]
            if before_str.strip()==repstr.strip():
                print(f"FILTER ALERT: skipped replacement of identical except whitespace *{before_str}* *{repstr}*")
                continue

            filtered_todelete_spans.append(onespan)
            filtered_replacement_strings.append(repstr)


        todelete_spans = filtered_todelete_spans
        replacement_strings = filtered_replacement_strings


        fused_todelete_spans = []
        fused_replacement_strings = []
        for (onespan, repl) in zip(todelete_spans, replacement_strings):
            if len(fused_todelete_spans)==0 or onespan[0]!=fused_todelete_spans[-1][1]:
                fused_todelete_spans.append(onespan)
                fused_replacement_strings.append(repl)
            else:
                fused_todelete_spans[-1][1] = onespan[1]
                fused_replacement_strings[-1] += repl

        assert len(fused_todelete_spans)==len(fused_replacement_strings)

        # adjust for the spaces at the beginning
        for j in range(len(fused_todelete_spans)):
            fused_todelete_spans[j][0] += num_frontspaces
            fused_todelete_spans[j][1] += num_frontspaces

        return {"evidence_labels": ev_labels,
                "todelete_spans": fused_todelete_spans,
                "replacement_strings": fused_replacement_strings}


    @app.route('/save_example', method=['POST'])
    def save_example():
        bundle_str = request.forms.get("bundle")
        bytes_string = bytes(bundle_str, encoding="raw_unicode_escape")
        bundle_str = bytes_string.decode("utf-8", "strict")

        save_obj = json.loads(bundle_str)

        _id = save_obj["id"]

        # pdb.set_trace()

        output_fpath = f"{save_output_path}/{_id}.json"

        if os.path.exists(output_fpath):
            return {'success': False, 'reason': 'Object already exists with that ID'}

        else:
            with open(output_fpath, "w", encoding="utf-8") as w:
                json.dump(save_obj, w, ensure_ascii=False)
            return {'success': True, 'reason': 'Object saved successfully'}


    @app.route("/sent_tokenize", method=['POST'])
    def sent_tokenize():
        new_doc = request.forms.get("doc")
        bytes_string = bytes(new_doc, encoding="raw_unicode_escape")
        new_doc = bytes_string.decode("utf-8", "strict")
        new_doc = new_doc.strip()
        new_doc = new_doc.replace("\n"," ")
        doc = nlp(new_doc)
        sents = [str(s) for s in doc.sents]

        newtxt = "\n".join(sents)

        return {"prediction":newtxt}

    @app.route("/check_length", method=['POST'])
    def check_length():
        new_doc = request.forms.get("doc")
        bytes_string = bytes(new_doc, encoding="raw_unicode_escape")
        new_doc = bytes_string.decode("utf-8", "strict")
        new_doc = new_doc.strip()
        input_lines = new_doc.split("\n")

        dummy_dp = {
              'input_lines': input_lines,
              'before_summary_sent': "dummy",
              'after_summary_sent': "dummmy",
              'id': 'xxxxx',
              'evidence_labels': [0]
            }

        newdp = process_evidence_extraction_with_fixfactuality(dummy_dp)
        inputs = tokenizer(newdp["input_string"], return_tensors="np", truncation=False)
        inp_shape = inputs["input_ids"].shape
        input_length = inp_shape[-1]

        curr_len = input_length
        allowed_len = factcheck_backend_config["max_input_len"]-factcheck_backend_config["max_decode_len"]
        to_return = {"curr_len":curr_len, "allowed_len":allowed_len, "okay": curr_len<=allowed_len}

        print(to_return)
        return to_return


    # singlethreaded
    # run(app, host="localhost", port=args.port, threaded=True)

    # multithreaded
    httpserver.serve(app, host='localhost', port=args.port)





